"""
ETL Pipeline Runner.

Runs dataset ETL phases (download -> parse -> normalize) and logs each step as a
single structured line via structlog (no live dashboard). Downloads can run in
parallel; parse/normalize run in dependency order.

Usage:
    from kg_ae.etl.runner import ETLRunner
    runner = ETLRunner()
    runner.run_all()              # Run everything
    runner.run_dataset("sider")   # Run a dataset with deps
    runner.run_tier(1)            # Run a tier
"""

from __future__ import annotations

import importlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum

from kg_ae.config import settings
from kg_ae.etl.logging import configure_logging, get_logger

configure_logging(settings.log_level)
log = get_logger("kg_ae.etl")


class StepStatus(Enum):
    """Status of an ETL step."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ETLStep:
    """A single ETL step (download, parse, or normalize)."""

    dataset: str
    phase: str  # download, parse, normalize
    description: str
    status: StepStatus = StepStatus.PENDING
    error: str | None = None
    duration: float | None = None
    row_count: int | None = None


@dataclass
class Dataset:
    """A dataset with its ETL phases and dependencies."""

    key: str
    name: str
    dependencies: list[str] = field(default_factory=list)
    has_normalize: bool = False
    tier: int = 1  # 1=foundational, 2=extension, 3=association, 4=advanced
    # license_tier gates which sources may appear in a given build:
    #   "commercial" - permissive (e.g. CC BY 4.0, public domain), OK for product builds
    #   "research"   - non-commercial / no explicit license, research/airgap use only
    license_tier: str = "commercial"
    license_name: str | None = None


# Dataset registry with dependencies
DATASETS: dict[str, Dataset] = {
    # Tier 1: Foundational (no dependencies)
    "hgnc": Dataset("hgnc", "HGNC Gene Nomenclature", [], has_normalize=False, tier=1, license_name="CC0"),
    "drugcentral": Dataset("drugcentral", "DrugCentral", [], has_normalize=True, tier=1, license_name="CC BY-SA 4.0"),
    # Tier 2: Extensions (depend on Tier 1)
    "opentargets": Dataset(
        "opentargets", "Open Targets Platform", ["hgnc"], has_normalize=True, tier=2, license_name="CC0"
    ),
    "reactome": Dataset("reactome", "Reactome Pathways", ["hgnc"], has_normalize=True, tier=2, license_name="CC0"),
    "gtop": Dataset(
        "gtop",
        "Guide to Pharmacology",
        ["hgnc", "drugcentral"],
        has_normalize=True,
        tier=2,
        license_name="CC BY-SA 4.0",
    ),
    # Tier 3: Associations (depend on Tier 1-2)
    "sider": Dataset(
        "sider",
        "SIDER Drug-ADR",
        ["drugcentral"],
        has_normalize=True,
        tier=3,
        license_tier="research",  # CC BY-NC-SA: non-commercial
        license_name="CC BY-NC-SA 4.0",
    ),
    "onsides": Dataset(
        "onsides",
        "OnSIDES Drug-ADE (labels)",
        ["drugcentral"],
        has_normalize=True,
        tier=3,
        license_tier="commercial",  # MIT
        license_name="MIT",
    ),
    "openfda": Dataset(
        "openfda", "openFDA FAERS", ["drugcentral"], has_normalize=True, tier=3, license_name="CC0 (US Gov)"
    ),
    "ctd": Dataset(
        "ctd",
        "CTD Toxicogenomics",
        ["hgnc", "drugcentral"],
        has_normalize=True,
        tier=3,
        license_tier="research",  # CTD: free for academic/research use
        license_name="CTD terms (research)",
    ),
    "string": Dataset("string", "STRING PPI", ["hgnc"], has_normalize=True, tier=3, license_name="CC BY 4.0"),
    "clingen": Dataset("clingen", "ClinGen Validity", ["hgnc"], has_normalize=True, tier=3, license_name="CC0"),
    "hpo": Dataset(
        "hpo", "Human Phenotype Ontology", ["hgnc"], has_normalize=True, tier=3, license_name="HPO (custom, open)"
    ),
    # Tier 4: Advanced (depend on earlier tiers)
    "chembl": Dataset("chembl", "ChEMBL Bioactivity", ["hgnc", "drugcentral"], tier=4, license_name="CC BY-SA 3.0"),
    "bindingdb": Dataset(
        "bindingdb",
        "BindingDB Affinities",
        ["hgnc", "drugcentral"],
        has_normalize=True,
        tier=4,
        license_tier="commercial",  # CC BY 4.0
        license_name="CC BY 4.0",
    ),
    "twosides": Dataset(
        "twosides",
        "TWOSIDES Drug-Drug AE",
        ["drugcentral"],
        has_normalize=True,
        tier=4,
        license_tier="research",  # no explicit license
        license_name="None stated (research)",
    ),
    "faers": Dataset(
        "faers", "FDA FAERS Reports", ["drugcentral"], has_normalize=True, tier=4, license_name="CC0 (US Gov)"
    ),
}

# Execution order respecting dependencies
EXECUTION_ORDER = [
    # Tier 1
    "hgnc",
    "drugcentral",
    # Tier 2
    "opentargets",
    "reactome",
    "gtop",
    # Tier 3
    "sider",
    "onsides",
    "openfda",
    "ctd",
    "string",
    "clingen",
    "hpo",
    # Tier 4
    "chembl",
    "bindingdb",
    "twosides",
    "faers",
]


class ETLRunner:
    """ETL pipeline runner. Logs each step as a single structlog line."""

    def __init__(self):
        self.steps: dict[str, dict[str, ETLStep]] = {}  # dataset -> phase -> step
        self._init_steps()

    def _init_steps(self) -> None:
        """Initialize all ETL steps."""
        for key, dataset in DATASETS.items():
            # The graph is now built from silver Parquet by `kg-ae build-graph`,
            # so ETL ends at normalize; there is no per-dataset SQL "load" phase.
            phases = ["download", "parse"]
            if dataset.has_normalize:
                phases.append("normalize")

            self.steps[key] = {}
            for phase in phases:
                self.steps[key][phase] = ETLStep(
                    dataset=key,
                    phase=phase,
                    description=f"{dataset.name} - {phase.title()}",
                )

    def _get_module(self, dataset_key: str):
        """Dynamically import a dataset module."""
        return importlib.import_module(f"kg_ae.datasets.{dataset_key}")

    def _run_step(
        self,
        dataset_key: str,
        phase: str,
        force: bool = False,
    ) -> bool:
        """
        Run a single ETL step. Logs one structlog line on completion.

        Returns True if successful, False otherwise.
        """
        step = self.steps[dataset_key][phase]
        step.status = StepStatus.RUNNING
        log.info("etl.step", dataset=dataset_key, phase=phase, status="running")

        start_time = time.time()

        try:
            module = self._get_module(dataset_key)

            if phase == "download":
                cls_name = f"{dataset_key.title().replace('_', '')}Downloader"
                downloader_cls = getattr(module, cls_name, None)
                if not downloader_cls:
                    # Try common naming patterns
                    for name in dir(module):
                        if name.endswith("Downloader"):
                            downloader_cls = getattr(module, name)
                            break
                if downloader_cls:
                    downloader = downloader_cls()
                    downloader.download(force=force)

            elif phase == "parse":
                parser_cls = getattr(module, f"{dataset_key.title().replace('_', '')}Parser", None)
                if not parser_cls:
                    for name in dir(module):
                        if name.endswith("Parser"):
                            parser_cls = getattr(module, name)
                            break
                if parser_cls:
                    parser = parser_cls()
                    parser.parse()

            elif phase == "normalize":
                cls_name = f"{dataset_key.title().replace('_', '')}Normalizer"
                normalizer_cls = getattr(module, cls_name, None)
                if not normalizer_cls:
                    for name in dir(module):
                        if name.endswith("Normalizer"):
                            normalizer_cls = getattr(module, name)
                            break
                if normalizer_cls:
                    normalizer = normalizer_cls()
                    normalizer.normalize()

            step.status = StepStatus.DONE
            step.duration = time.time() - start_time
            log.info("etl.step", dataset=dataset_key, phase=phase, status="done", duration=step.duration)
            return True

        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.duration = time.time() - start_time
            log.error(
                "etl.step", dataset=dataset_key, phase=phase, status="error", duration=step.duration, detail=str(e)
            )
            return False


    def _resolve_dependencies(self, dataset_key: str) -> list[str]:
        """Get ordered list of datasets needed (including dependencies)."""
        needed = set()

        def add_deps(key: str):
            if key in needed:
                return
            dataset = DATASETS.get(key)
            if not dataset:
                return
            for dep in dataset.dependencies:
                add_deps(dep)
            needed.add(key)

        add_deps(dataset_key)

        # Return in execution order
        return [k for k in EXECUTION_ORDER if k in needed]

    def _run_phases_sequential(self, datasets: list[str], force: bool, phases: list[str] | None = None) -> bool:
        """Run all phases for the given datasets in order. Stop on first failure."""
        for ds_key in datasets:
            ds_phases = list(self.steps[ds_key].keys())
            if phases:
                ds_phases = [p for p in ds_phases if p in phases]
            for phase in ds_phases:
                if not self._run_step(ds_key, phase, force):
                    log.error("etl.stopped", dataset=ds_key, phase=phase)
                    return False
        return True

    def _downloader(self, dataset_key: str):
        """Instantiate a dataset's downloader (or None if absent)."""
        module = self._get_module(dataset_key)
        cls = getattr(module, f"{dataset_key.title().replace('_', '')}Downloader", None)
        if cls is None:
            for name in dir(module):
                if name.endswith("Downloader"):
                    cls = getattr(module, name)
                    break
        return cls() if cls else None

    def download_parallel(self, datasets: list[str], force: bool = False) -> bool:
        """Download datasets efficiently.

        Declarative downloaders (those exposing ``download_specs``) are pooled
        into a single aria2c batch -> one process handles all files in parallel
        with per-file multi-connection splits, resume, and retries. Imperative
        downloaders (paginated APIs, directory listings) run concurrently on a
        thread pool. Downloads have no inter-dataset dependencies.
        """
        from kg_ae.etl.aria2 import DownloadSpec, fetch_specs

        targets = [d for d in datasets if "download" in self.steps[d]]
        if not targets:
            return True

        batch_specs: list[DownloadSpec] = []
        imperative: list[str] = []
        downloaders: dict[str, object] = {}

        for d in targets:
            dl = self._downloader(d)
            downloaders[d] = dl
            specs = dl.download_specs() if dl else []
            if specs:
                pending = specs if force else [s for s in specs if not s.dest.exists()]
                batch_specs.extend(pending)
                for s in specs:
                    if s not in pending:
                        log.info("etl.download.cached", dataset=d, file=s.dest.name)
            else:
                imperative.append(d)

        ok = True

        # 1. One aria2c batch for all declarative file specs.
        if batch_specs:
            log.info("etl.download.batch", files=len(batch_specs))
            declarative_keys = [d for d in targets if downloaders.get(d) and downloaders[d].download_specs()]
            for d in declarative_keys:
                self.steps[d]["download"].status = StepStatus.RUNNING
            _downloaded, failed = fetch_specs(batch_specs)
            failed_sources = {s.source for s in failed}
            for d in declarative_keys:
                if d in failed_sources:
                    ok = False
                    self.steps[d]["download"].status = StepStatus.FAILED
                    log.error("etl.step", dataset=d, phase="download", status="error")
                else:
                    self.steps[d]["download"].status = StepStatus.DONE
                    log.info("etl.step", dataset=d, phase="download", status="done")

        # 2. Imperative downloaders (APIs / listings) in parallel.
        if imperative:
            workers = max(1, min(settings.download_concurrency, len(imperative)))
            log.info("etl.download.imperative", datasets=len(imperative), workers=workers)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(self._run_step, d, "download", force): d for d in imperative}
                for fut in as_completed(futures):
                    if not fut.result():
                        ok = False
        return ok

    def run_dataset(
        self,
        dataset_key: str,
        include_deps: bool = True,
        force: bool = False,
        phases: list[str] | None = None,
    ) -> bool:
        """Run ETL for a specific dataset (and optionally its dependencies)."""
        if dataset_key not in DATASETS:
            log.error("etl.unknown_dataset", dataset=dataset_key)
            return False

        datasets_to_run = self._resolve_dependencies(dataset_key) if include_deps else [dataset_key]
        return self._run_phases_sequential(datasets_to_run, force, phases)

    def run_tier(self, tier: int, force: bool = False) -> bool:
        """Run all datasets in a specific tier (plus dependencies)."""
        datasets = [k for k, v in DATASETS.items() if v.tier == tier]
        all_needed = set()
        for ds in datasets:
            all_needed.update(self._resolve_dependencies(ds))
        ordered = [k for k in EXECUTION_ORDER if k in all_needed]
        return self._run_phases_sequential(ordered, force)

    def run_all(self, force: bool = False) -> bool:
        """Run the complete ETL pipeline: parallel downloads, then parse + normalize."""
        if not self.download_parallel(EXECUTION_ORDER, force=force):
            return False
        for ds_key in EXECUTION_ORDER:
            for phase in self.steps[ds_key]:
                if phase == "download":
                    continue
                if not self._run_step(ds_key, phase, force):
                    return False
        return True

