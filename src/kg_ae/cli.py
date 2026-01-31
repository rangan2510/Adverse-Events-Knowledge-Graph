"""
Command-line interface for kg_ae.

Commands:
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
    console.print("[bold green]✓ Schema created successfully[/]")


@app.command()
def download(
    source: str = typer.Argument(..., help="Data source to download (e.g., sider, drugcentral)"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-download even if exists"),
):
    """Download raw data from a source."""
    console.print(f"[bold blue]Downloading {source}...[/]")
    # TODO: Dispatch to appropriate downloader
    console.print(f"[yellow]Not implemented yet: download {source}[/]")


@app.command()
def ingest(
    source: str = typer.Argument(..., help="Data source to ingest"),
):
    """Parse and load a data source into the graph."""
    console.print(f"[bold blue]Ingesting {source}...[/]")
    # TODO: Dispatch to appropriate ETL pipeline
    console.print(f"[yellow]Not implemented yet: ingest {source}[/]")


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
