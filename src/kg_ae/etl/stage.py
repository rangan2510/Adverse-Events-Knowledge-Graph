"""
Staging pipeline: produce the shippable JSON graph artifact.

The staging container (online) runs these steps to turn raw public data into
``data/graph/*.json``, which is then baked into the airgapped runtime image.
Steps:

    download  -> data/raw      (network)
    normalize -> data/silver   (parse + normalize; no network)
    build     -> data/graph    (build + validate the JSON artifact)
    verify    -> canary QA on the built graph (gate before shipping)

``run_all`` chains them. Each step is also exposed as a CLI subcommand and a
thin script shim under scripts/.

A ``license_tier`` filter lets a build exclude non-commercial / unlicensed
sources (e.g. SIDER) for a product track. Default includes everything
(research posture), which is appropriate for the hospital research deployment.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from kg_ae.etl.runner import DATASETS, EXECUTION_ORDER, ETLRunner

console = Console()

# Ordered by least->most permissive so "commercial" is the strict subset.
LICENSE_TIERS = ("commercial", "research")


def _selected_datasets(license_tier: str) -> list[str]:
    """Return dataset keys allowed under the given license tier, in exec order."""
    if license_tier == "commercial":
        allowed = {k for k, d in DATASETS.items() if d.license_tier == "commercial"}
    else:
        allowed = set(DATASETS.keys())
    return [k for k in EXECUTION_ORDER if k in allowed]


def stage_download(license_tier: str = "research", force: bool = False) -> None:
    """Download raw data for all selected datasets (in parallel)."""
    runner = ETLRunner()
    keys = _selected_datasets(license_tier)
    console.print(f"[bold blue]Staging download[/] ({license_tier}): {', '.join(keys)}")
    runner.download_parallel(keys, force=force)


def stage_normalize(license_tier: str = "research", force: bool = False) -> None:
    """Parse + normalize raw data into silver Parquet for all selected datasets."""
    runner = ETLRunner()
    keys = _selected_datasets(license_tier)
    console.print(f"[bold blue]Staging normalize[/] ({license_tier}): {', '.join(keys)}")
    for key in keys:
        phases = ["parse"]
        if DATASETS[key].has_normalize:
            phases.append("normalize")
        runner.run_dataset(key, include_deps=False, force=force, phases=phases)


def stage_build() -> dict[str, int]:
    """Build + validate the JSON graph from silver Parquet."""
    from kg_ae.graph import build_graph

    console.print("[bold blue]Staging build[/]: building JSON graph from silver")
    return build_graph()


# Canary checks: (label, callable -> bool). Each must hold on a healthy graph.
def _canaries() -> list[tuple[str, bool]]:
    from kg_ae.graph import get_store
    from kg_ae.tools import get_drug_targets, resolve_drugs

    store = get_store()
    counts = store.counts()
    results: list[tuple[str, bool]] = []

    results.append(("graph has drugs", counts.get("Drug", 0) > 0))
    results.append(("graph has genes", counts.get("Gene", 0) > 0))
    results.append(("graph has edges", counts.get("edges", 0) > 0))

    # Atorvastatin -> HMGCR is a known true edge (statin target).
    resolved = resolve_drugs(["atorvastatin"]).get("atorvastatin")
    ator_ok = resolved is not None
    results.append(("resolve atorvastatin", ator_ok))
    if ator_ok:
        symbols = {t.gene_symbol for t in get_drug_targets(resolved.key)}
        results.append(("atorvastatin targets HMGCR", "HMGCR" in symbols))
    else:
        results.append(("atorvastatin targets HMGCR", False))

    return results


def stage_verify() -> bool:
    """Run canary QA checks on the built graph. Returns True if all pass."""
    console.print("[bold blue]Staging verify[/]: running canary checks")
    checks = _canaries()
    table = Table(title="Graph QA")
    table.add_column("Check", style="cyan")
    table.add_column("Result", justify="center")
    all_ok = True
    for label, ok in checks:
        table.add_row(label, "[green]ok[/]" if ok else "[red]FAIL[/]")
        all_ok = all_ok and ok
    console.print(table)
    if all_ok:
        console.print("[green][ok][/green] All canary checks passed")
    else:
        console.print("[red][!][/red] Canary checks FAILED")
    return all_ok


def run_all(license_tier: str = "research", force: bool = False) -> bool:
    """Run the full staging pipeline. Returns True if verification passes."""
    stage_download(license_tier, force=force)
    stage_normalize(license_tier, force=force)
    stage_build()
    return stage_verify()
