"""
Command-line interface for kg_ae.

Commands:
- etl: Interactive ETL pipeline runner
- build-kg: Run ETL pipelines to build the knowledge graph
- query: Query the graph for drug-AE relationships
- explain: Generate mechanistic explanations for drug-AE pairs
- export: Export subgraphs to JSON/GraphML
"""

from typing import Annotated

import typer
from rich.console import Console

app = typer.Typer(
    name="kg-ae",
    help="Drug-Adverse Event Knowledge Graph CLI",
    no_args_is_help=True,
)
console = Console()


@app.command()
def init_db():
    """Initialize the database schema (create kg.* tables)."""
    from kg_ae.db import init_schema

    console.print("[bold blue]Initializing database schema...[/]")
    init_schema()
    console.print("[bold green]Done. Schema created successfully[/]")


@app.command()
def etl(
    interactive: bool = typer.Option(
        True, "--interactive/--batch", "-i/-b",
        help="Interactive mode with live dashboard"
    ),
    dataset: str | None = typer.Option(
        None, "--dataset", "-d", help="Run specific dataset only"
    ),
    tier: int | None = typer.Option(
        None, "--tier", "-t", help="Run specific tier (1-4)"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force re-download/re-process"
    ),
):
    """Run ETL pipeline with live status dashboard."""
    from kg_ae.etl.runner import ETLRunner

    runner = ETLRunner()

    if interactive and not dataset and not tier:
        runner.run_interactive()
    elif dataset:
        runner.run_dataset(dataset, include_deps=True, force=force)
    elif tier:
        runner.run_tier(tier, force=force)
    else:
        runner.run_all(force=force)


@app.command()
def download(
    source: str = typer.Argument(
        ..., help="Data source to download (e.g., sider, drugcentral)"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Re-download even if exists"
    ),
):
    """Download raw data from a source."""
    from kg_ae.etl.runner import ETLRunner

    runner = ETLRunner()
    runner.run_dataset(source, include_deps=False, force=force, phases=["download"])


@app.command()
def ingest(
    source: str = typer.Argument(..., help="Data source to ingest"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force re-process"
    ),
):
    """Parse and load a data source into the graph."""
    from kg_ae.etl.runner import ETLRunner

    runner = ETLRunner()
    runner.run_dataset(source, include_deps=True, force=force)


@app.command()
def query(
    drugs: Annotated[list[str], typer.Option("--drug", "-d", help="Drug names to query")],
    conditions: Annotated[
        list[str] | None, typer.Option("--condition", "-c", help="Patient conditions")
    ] = None,
):
    """Query the graph for drug-AE relationships."""
    console.print(f"[bold blue]Querying for drugs: {drugs}[/]")
    if conditions:
        console.print(f"[bold blue]With conditions: {conditions}[/]")
    # TODO: Implement query logic
    console.print("[yellow]Not implemented yet[/]")


if __name__ == "__main__":
    app()
