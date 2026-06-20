"""
Command-line interface for kg_ae.

Commands:
- etl: Interactive ETL pipeline runner (downloads + parses + normalizes sources)
- build-graph: Build the file-based JSON knowledge graph from silver Parquet
- stage: Staging pipeline (download/normalize/build/verify) -> ship the JSON artifact
- query: Ask a natural-language pharmacovigilance question (LangChain agent)
- doctor: Print the active LLM/compliance configuration
"""

import typer
from rich.console import Console

app = typer.Typer(
    name="kg-ae",
    help="Drug-Adverse Event Knowledge Graph CLI",
    no_args_is_help=True,
)

# Staging sub-app: produces the shippable JSON graph artifact.
stage_app = typer.Typer(name="stage", help="Staging pipeline (download/normalize/build/verify)", no_args_is_help=True)
app.add_typer(stage_app)

console = Console()


@stage_app.command("download")
def stage_download_cmd(
    license_tier: str = typer.Option("research", "--license-tier", help="research|commercial"),
    force: bool = typer.Option(False, "--force", "-f"),
):
    """Download raw data for all selected datasets."""
    from kg_ae.etl.stage import stage_download

    stage_download(license_tier, force=force)


@stage_app.command("normalize")
def stage_normalize_cmd(
    license_tier: str = typer.Option("research", "--license-tier", help="research|commercial"),
    force: bool = typer.Option(False, "--force", "-f"),
):
    """Parse + normalize raw data into silver Parquet."""
    from kg_ae.etl.stage import stage_normalize

    stage_normalize(license_tier, force=force)


@stage_app.command("build")
def stage_build_cmd():
    """Build + validate the JSON graph from silver Parquet."""
    from kg_ae.etl.stage import stage_build

    stage_build()


@stage_app.command("verify")
def stage_verify_cmd():
    """Run canary QA checks on the built graph (exits non-zero on failure)."""
    from kg_ae.etl.stage import stage_verify

    if not stage_verify():
        raise typer.Exit(code=1)


@stage_app.command("all")
def stage_all_cmd(
    license_tier: str = typer.Option("research", "--license-tier", help="research|commercial"),
    force: bool = typer.Option(False, "--force", "-f"),
):
    """Run the full staging pipeline (download -> normalize -> build -> verify)."""
    from kg_ae.etl.stage import run_all

    if not run_all(license_tier, force=force):
        raise typer.Exit(code=1)


@app.command()
def build_graph():
    """Build the file-based JSON knowledge graph from silver Parquet."""
    from kg_ae.graph import build_graph as _build

    console.print("[bold blue]Building JSON knowledge graph...[/]")
    _build()
    console.print("[bold green]Done.[/]")


@app.command()
def etl(
    dataset: str | None = typer.Option(None, "--dataset", "-d", help="Run specific dataset only"),
    tier: int | None = typer.Option(None, "--tier", "-t", help="Run specific tier (1-4)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-download/re-process"),
):
    """Run the ETL pipeline (download -> parse -> normalize), logging each step."""
    from kg_ae.etl.runner import ETLRunner

    runner = ETLRunner()

    if dataset:
        runner.run_dataset(dataset, include_deps=True, force=force)
    elif tier:
        runner.run_tier(tier, force=force)
    else:
        runner.run_all(force=force)


@app.command()
def download(
    source: str = typer.Argument(..., help="Data source to download (e.g., sider, drugcentral)"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-download even if exists"),
):
    """Download raw data from a source."""
    from kg_ae.etl.runner import ETLRunner

    runner = ETLRunner()
    runner.run_dataset(source, include_deps=False, force=force, phases=["download"])


@app.command()
def ingest(
    source: str = typer.Argument(..., help="Data source to ingest"),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-process"),
):
    """Parse and load a data source into the graph."""
    from kg_ae.etl.runner import ETLRunner

    runner = ETLRunner()
    runner.run_dataset(source, include_deps=True, force=force)


@app.command()
def query(
    question: str = typer.Argument(None, help="Natural-language pharmacovigilance question"),
    ensemble: int = typer.Option(None, "--ensemble", "-e", help="Number of agents to reconcile"),
    max_iterations: int = typer.Option(None, "--max-iterations", "-n", help="Max ReAct iterations"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Interactive prompt loop"),
    openrouter_api_key: str = typer.Option(
        None,
        "--openrouter-api-key",
        help="OpenRouter API key. Overrides OPENROUTER_API_KEY / .env (handy when no .env is present).",
        envvar="OPENROUTER_API_KEY",
    ),
):
    """Ask a natural-language pharmacovigilance question via the LangChain agent."""
    import os

    from kg_ae.config import settings
    from kg_ae.llm import run_agent
    from kg_ae.llm.llm_client import llm_summary

    # Let the key be passed explicitly (e.g. a container with no .env file).
    if openrouter_api_key:
        os.environ["OPENROUTER_API_KEY"] = openrouter_api_key
        settings.llm_api_key = openrouter_api_key

    console.print(f"[dim]{llm_summary()}[/]")

    def _answer(q: str) -> None:
        result = run_agent(q, ensemble_size=ensemble, max_iterations=max_iterations)
        console.print()
        console.print(result.answer)

    if interactive or not question:
        console.print("[cyan]Interactive mode. Type 'quit' or 'exit' to stop.[/]")
        while True:
            try:
                q = console.input("\n[bold green]Query>[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye![/]")
                break
            if not q:
                continue
            if q.lower() in ("quit", "exit", "q"):
                console.print("[dim]Goodbye![/]")
                break
            try:
                _answer(q)
            except Exception as e:  # noqa: BLE001 - surface agent errors to the user
                console.print(f"[red]Error: {e}[/]")
        return

    _answer(question)


@app.command()
def doctor():
    """Print the active LLM and compliance configuration."""
    from kg_ae.config import settings
    from kg_ae.llm.llm_client import llm_summary

    console.print(f"[bold]LLM:[/] {llm_summary()}")
    errors = settings.validate_compliance()
    if errors:
        console.print("[bold red]Compliance violations:[/]")
        for e in errors:
            console.print(f"  [red]- {e}[/]")
    else:
        console.print("[green]Compliance OK[/]")


if __name__ == "__main__":
    app()
