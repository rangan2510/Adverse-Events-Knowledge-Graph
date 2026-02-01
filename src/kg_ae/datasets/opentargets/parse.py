"""
Open Targets dataset parser.

Parses raw Open Targets Parquet files to bronze format.
"""

from pathlib import Path

import polars as pl
from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseParser

console = Console()


class OpenTargetsParser(BaseParser):
    """Parse Open Targets Parquet files to bronze."""

    source_key = "opentargets"

    def parse(self) -> dict[str, Path]:
        """
        Parse Open Targets raw Parquet files to bronze.

        Open Targets data is already in Parquet format, so this mainly
        consolidates partitioned files and selects relevant columns.

        Returns:
            Dict mapping table names to Parquet file paths
        """
        console.print("[bold cyan]Open Targets Parser[/]")
        results = {}

        # Parse associations
        assoc_path = self._parse_associations()
        if assoc_path:
            results["associations"] = assoc_path

        # Parse diseases
        disease_path = self._parse_diseases()
        if disease_path:
            results["diseases"] = disease_path

        # Parse targets (genes)
        target_path = self._parse_targets()
        if target_path:
            results["targets"] = target_path

        # Summary table
        if results:
            table = Table(title="Open Targets Parse Summary", show_header=True)
            table.add_column("Table", style="cyan")
            table.add_column("File", style="dim")
            for name, path in results.items():
                table.add_row(name, path.name)
            console.print(table)

        return results

    def _parse_associations(self) -> Path | None:
        """Parse association_overall_direct to consolidated Parquet."""
        src_dir = self.raw_dir / "association_overall_direct"
        if not src_dir.exists():
            return None

        dest = self.bronze_dir / "associations.parquet"

        # Read all parquet files in directory
        parquet_files = list(src_dir.glob("*.parquet"))
        if not parquet_files:
            console.print(f"  [yellow][warning][/] No parquet files in {src_dir}")
            return None

        # Use lazy loading for efficiency with large datasets
        df = pl.scan_parquet(src_dir / "*.parquet")
        
        # Select key columns and collect
        df = df.select([
            "targetId",
            "diseaseId", 
            "score",
        ]).collect()

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] associations: {len(df):,} rows")
        return dest

    def _parse_diseases(self) -> Path | None:
        """Parse disease dataset to consolidated Parquet."""
        src_dir = self.raw_dir / "disease"
        if not src_dir.exists():
            return None

        dest = self.bronze_dir / "diseases.parquet"

        parquet_files = list(src_dir.glob("*.parquet"))
        if not parquet_files:
            console.print(f"  [yellow][warning][/] No parquet files in {src_dir}")
            return None

        df = pl.scan_parquet(src_dir / "*.parquet")

        # Select key columns - check what's available
        # Common columns: id, name, description, synonyms, dbXRefs
        df = df.select([
            "id",
            "name",
            "description",
            "dbXRefs",  # Contains MONDO, DOID, etc.
        ]).collect()

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] diseases: {len(df):,} rows")
        return dest

    def _parse_targets(self) -> Path | None:
        """Parse target dataset to consolidated Parquet."""
        src_dir = self.raw_dir / "target"
        if not src_dir.exists():
            return None

        dest = self.bronze_dir / "targets.parquet"

        parquet_files = list(src_dir.glob("*.parquet"))
        if not parquet_files:
            console.print(f"  [yellow][warning][/] No parquet files in {src_dir}")
            return None

        df = pl.scan_parquet(src_dir / "*.parquet")

        # Select key columns for gene identity
        # id = Ensembl gene ID, approvedSymbol = HGNC symbol
        df = df.select([
            "id",
            "approvedSymbol",
            "approvedName",
            "proteinIds",  # Contains UniProt IDs
        ]).collect()

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] targets: {len(df):,} rows")
        return dest
