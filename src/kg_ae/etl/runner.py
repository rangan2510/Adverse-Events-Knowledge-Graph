"""
Interactive ETL Pipeline Runner.

Provides a live dashboard showing:
- All ETL steps with status (pending, running, done, failed, skipped)
- Dependencies between datasets
- Progress tracking for current operation
- Selective execution with dependency resolution

Usage:
    from kg_ae.etl.runner import ETLRunner
    runner = ETLRunner()
    runner.run_interactive()  # Full interactive menu
    runner.run_all()          # Run everything
    runner.run_dataset("sider")  # Run specific dataset with deps
"""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from enum import Enum

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, TaskID
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text


class StepStatus(Enum):
    """Status of an ETL step."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ETLStep:
    """A single ETL step (download, parse, normalize, or load)."""

    dataset: str
    phase: str  # download, parse, normalize, load
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


# Dataset registry with dependencies
DATASETS: dict[str, Dataset] = {
    # Tier 1: Foundational (no dependencies)
    "hgnc": Dataset("hgnc", "HGNC Gene Nomenclature", [], has_normalize=False, tier=1),
    "drugcentral": Dataset("drugcentral", "DrugCentral", [], has_normalize=True, tier=1),
    # Tier 2: Extensions (depend on Tier 1)
    "opentargets": Dataset("opentargets", "Open Targets Platform", ["hgnc"], has_normalize=True, tier=2),
    "reactome": Dataset("reactome", "Reactome Pathways", ["hgnc"], has_normalize=True, tier=2),
    "gtop": Dataset("gtop", "Guide to Pharmacology", ["hgnc", "drugcentral"], tier=2),
    # Tier 3: Associations (depend on Tier 1-2)
    "sider": Dataset("sider", "SIDER Drug-ADR", ["drugcentral"], has_normalize=True, tier=3),
    "openfda": Dataset("openfda", "openFDA FAERS", ["drugcentral"], tier=3),
    "ctd": Dataset("ctd", "CTD Toxicogenomics", ["hgnc", "drugcentral"], tier=3),
    "string": Dataset("string", "STRING PPI", ["hgnc"], tier=3),
    "clingen": Dataset("clingen", "ClinGen Validity", ["hgnc"], tier=3),
    "hpo": Dataset("hpo", "Human Phenotype Ontology", ["hgnc"], tier=3),
    # Tier 4: Advanced (depend on earlier tiers)
    "chembl": Dataset("chembl", "ChEMBL Bioactivity", ["hgnc", "drugcentral"], tier=4),
    "faers": Dataset("faers", "FDA FAERS Reports", ["drugcentral"], tier=4),
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
    "openfda",
    "ctd",
    "string",
    "clingen",
    "hpo",
    # Tier 4
    "chembl",
    "faers",
]


class ETLRunner:
    """Interactive ETL pipeline runner with live status display."""

    def __init__(self):
        self.console = Console()
        self.steps: dict[str, dict[str, ETLStep]] = {}  # dataset -> phase -> step
        self._init_steps()
        self._progress: Progress | None = None
        self._current_task: TaskID | None = None

    def _init_steps(self) -> None:
        """Initialize all ETL steps."""
        for key, dataset in DATASETS.items():
            phases = ["download", "parse"]
            if dataset.has_normalize:
                phases.append("normalize")
            phases.append("load")

            self.steps[key] = {}
            for phase in phases:
                self.steps[key][phase] = ETLStep(
                    dataset=key,
                    phase=phase,
                    description=f"{dataset.name} - {phase.title()}",
                )

    def _get_status_icon(self, status: StepStatus) -> str:
        """Get icon for step status."""
        return {
            StepStatus.PENDING: "[dim][ ][/]",
            StepStatus.RUNNING: "[yellow][>][/]",
            StepStatus.DONE: "[green][ok][/]",
            StepStatus.FAILED: "[red][!][/]",
            StepStatus.SKIPPED: "[dim][-][/]",
        }[status]

    def _get_status_style(self, status: StepStatus) -> str:
        """Get style for step status."""
        return {
            StepStatus.PENDING: "dim",
            StepStatus.RUNNING: "yellow bold",
            StepStatus.DONE: "green",
            StepStatus.FAILED: "red",
            StepStatus.SKIPPED: "dim",
        }[status]

    def _build_dashboard(self, current_dataset: str | None = None) -> Panel:
        """Build the live dashboard display."""
        # Main table showing all datasets and their phases
        table = Table(
            title="ETL Pipeline Status",
            show_header=True,
            header_style="bold cyan",
            expand=True,
        )

        table.add_column("Tier", style="dim", width=4, justify="center")
        table.add_column("Dataset", width=20)
        table.add_column("Download", width=10, justify="center")
        table.add_column("Parse", width=10, justify="center")
        table.add_column("Normalize", width=10, justify="center")
        table.add_column("Load", width=10, justify="center")
        table.add_column("Dependencies", style="dim", width=25)

        for key in EXECUTION_ORDER:
            dataset = DATASETS[key]
            ds_steps = self.steps[key]

            # Highlight current dataset
            name_style = "bold yellow" if key == current_dataset else ""

            # Build phase cells
            def phase_cell(phase: str, steps_dict: dict = ds_steps) -> str:
                if phase not in steps_dict:
                    return "[dim]-[/]"
                step = steps_dict[phase]
                icon = self._get_status_icon(step.status)
                if step.duration is not None:
                    return f"{icon} {step.duration:.1f}s"
                return icon

            deps = ", ".join(dataset.dependencies) if dataset.dependencies else "-"

            table.add_row(
                str(dataset.tier),
                Text(dataset.name, style=name_style),
                phase_cell("download", ds_steps),
                phase_cell("parse", ds_steps),
                phase_cell("normalize", ds_steps),
                phase_cell("load", ds_steps),
                deps,
            )

        # Legend
        legend = Text()
        legend.append("Legend: ", style="bold")
        legend.append("[ ] pending  ", style="dim")
        legend.append("[>] running  ", style="yellow")
        legend.append("[ok] done  ", style="green")
        legend.append("[!] failed  ", style="red")
        legend.append("[-] skipped", style="dim")

        # Combine into panel
        content = Group(table, Text(""), legend)
        return Panel(content, title="[bold blue]Drug-AE Knowledge Graph ETL[/]", border_style="blue")

    def _get_module(self, dataset_key: str):
        """Dynamically import a dataset module."""
        return importlib.import_module(f"kg_ae.datasets.{dataset_key}")

    def _run_step(
        self,
        dataset_key: str,
        phase: str,
        live: Live | None = None,
        force: bool = False,
    ) -> bool:
        """
        Run a single ETL step.

        Returns True if successful, False otherwise.
        """
        step = self.steps[dataset_key][phase]
        step.status = StepStatus.RUNNING
        if live:
            live.update(self._build_dashboard(dataset_key))

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

            elif phase == "load":
                loader_cls = getattr(module, f"{dataset_key.title().replace('_', '')}Loader", None)
                if not loader_cls:
                    for name in dir(module):
                        if name.endswith("Loader"):
                            loader_cls = getattr(module, name)
                            break
                if loader_cls:
                    loader = loader_cls()
                    result = loader.load()
                    if isinstance(result, dict):
                        step.row_count = sum(v for v in result.values() if isinstance(v, int))

            step.status = StepStatus.DONE
            step.duration = time.time() - start_time
            return True

        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            step.duration = time.time() - start_time
            self.console.print(f"[red]Error in {dataset_key}/{phase}: {e}[/]")
            return False

        finally:
            if live:
                live.update(self._build_dashboard(dataset_key))

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

    def run_dataset(
        self,
        dataset_key: str,
        include_deps: bool = True,
        force: bool = False,
        phases: list[str] | None = None,
    ) -> bool:
        """
        Run ETL for a specific dataset.

        Args:
            dataset_key: Dataset to run
            include_deps: Also run dependencies first
            force: Force re-download/re-process
            phases: Specific phases to run (default: all)

        Returns:
            True if all steps succeeded
        """
        if dataset_key not in DATASETS:
            self.console.print(f"[red]Unknown dataset: {dataset_key}[/]")
            return False

        datasets_to_run = self._resolve_dependencies(dataset_key) if include_deps else [dataset_key]

        with Live(self._build_dashboard(), console=self.console, refresh_per_second=4) as live:
            for ds_key in datasets_to_run:
                ds_phases = list(self.steps[ds_key].keys())
                if phases:
                    ds_phases = [p for p in ds_phases if p in phases]

                for phase in ds_phases:
                    success = self._run_step(ds_key, phase, live, force)
                    if not success:
                        self.console.print(f"[red]Pipeline stopped: error in {ds_key}/{phase}[/]")
                        return False

        return True

    def run_tier(self, tier: int, force: bool = False) -> bool:
        """Run all datasets in a specific tier."""
        datasets = [k for k, v in DATASETS.items() if v.tier == tier]

        # Also need dependencies from lower tiers
        all_needed = set()
        for ds in datasets:
            all_needed.update(self._resolve_dependencies(ds))

        ordered = [k for k in EXECUTION_ORDER if k in all_needed]

        with Live(self._build_dashboard(), console=self.console, refresh_per_second=4) as live:
            for ds_key in ordered:
                for phase in self.steps[ds_key]:
                    success = self._run_step(ds_key, phase, live, force)
                    if not success:
                        return False

        return True

    def run_all(self, force: bool = False) -> bool:
        """Run the complete ETL pipeline."""
        with Live(self._build_dashboard(), console=self.console, refresh_per_second=4) as live:
            for ds_key in EXECUTION_ORDER:
                for phase in self.steps[ds_key]:
                    success = self._run_step(ds_key, phase, live, force)
                    if not success:
                        return False

        return True

    def run_interactive(self) -> None:
        """Run interactive menu for pipeline execution."""
        while True:
            self.console.clear()
            self.console.print(self._build_dashboard())
            self.console.print()

            self.console.print("[bold]Options:[/]")
            self.console.print("  [cyan]1[/] - Run complete pipeline")
            self.console.print("  [cyan]2[/] - Run specific dataset")
            self.console.print("  [cyan]3[/] - Run by tier")
            self.console.print("  [cyan]4[/] - Run specific phase across datasets")
            self.console.print("  [cyan]5[/] - Reset status")
            self.console.print("  [cyan]q[/] - Quit")
            self.console.print()

            choice = Prompt.ask("Select option", choices=["1", "2", "3", "4", "5", "q"], default="q")

            if choice == "q":
                break

            elif choice == "1":
                force = Confirm.ask("Force re-download/re-process?", default=False)
                self.run_all(force=force)
                Prompt.ask("Press Enter to continue")

            elif choice == "2":
                self.console.print("\n[bold]Available datasets:[/]")
                for i, key in enumerate(EXECUTION_ORDER, 1):
                    ds = DATASETS[key]
                    deps = f" (deps: {', '.join(ds.dependencies)})" if ds.dependencies else ""
                    self.console.print(f"  [cyan]{i:2}[/] - {ds.name}{deps}")

                idx = Prompt.ask("\nDataset number", default="1")
                try:
                    ds_key = EXECUTION_ORDER[int(idx) - 1]
                    include_deps = Confirm.ask("Include dependencies?", default=True)
                    force = Confirm.ask("Force re-download?", default=False)
                    self.run_dataset(ds_key, include_deps=include_deps, force=force)
                except (ValueError, IndexError):
                    self.console.print("[red]Invalid selection[/]")
                Prompt.ask("Press Enter to continue")

            elif choice == "3":
                self.console.print("\n[bold]Tiers:[/]")
                self.console.print("  [cyan]1[/] - Foundational (HGNC, DrugCentral)")
                self.console.print("  [cyan]2[/] - Extensions (Open Targets, Reactome, GtoPdb)")
                self.console.print("  [cyan]3[/] - Associations (SIDER, openFDA, CTD, STRING, ...)")
                self.console.print("  [cyan]4[/] - Advanced (ChEMBL, FAERS)")

                tier = Prompt.ask("\nTier number", choices=["1", "2", "3", "4"], default="1")
                force = Confirm.ask("Force re-download?", default=False)
                self.run_tier(int(tier), force=force)
                Prompt.ask("Press Enter to continue")

            elif choice == "4":
                self.console.print("\n[bold]Phases:[/]")
                self.console.print("  [cyan]1[/] - Download only")
                self.console.print("  [cyan]2[/] - Parse only")
                self.console.print("  [cyan]3[/] - Normalize only")
                self.console.print("  [cyan]4[/] - Load only")

                phase_choice = Prompt.ask("\nPhase", choices=["1", "2", "3", "4"], default="1")
                phase_map = {"1": "download", "2": "parse", "3": "normalize", "4": "load"}
                phase = phase_map[phase_choice]

                force = Confirm.ask("Force re-process?", default=False)

                with Live(self._build_dashboard(), console=self.console, refresh_per_second=4) as live:
                    for ds_key in EXECUTION_ORDER:
                        if phase in self.steps[ds_key]:
                            self._run_step(ds_key, phase, live, force)

                Prompt.ask("Press Enter to continue")

            elif choice == "5":
                self._init_steps()
                self.console.print("[green]Status reset[/]")
                Prompt.ask("Press Enter to continue")

    def show_status(self) -> None:
        """Display current pipeline status."""
        self.console.print(self._build_dashboard())


def main():
    """Entry point for CLI."""
    runner = ETLRunner()
    runner.run_interactive()


if __name__ == "__main__":
    main()
