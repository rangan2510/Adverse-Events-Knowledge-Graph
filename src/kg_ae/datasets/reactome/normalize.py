"""
Reactome normalizer.

Converts bronze Parquet to silver with canonical IDs.
Filters to Homo sapiens only.
"""

from pathlib import Path

import polars as pl
from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseNormalizer

console = Console()


class ReactomeNormalizer(BaseNormalizer):
    """Normalize Reactome data to silver layer with canonical IDs."""

    source_key = "reactome"

    def normalize(self) -> dict[str, Path]:
        """
        Normalize bronze Reactome data to silver.

        Returns:
            Dict mapping table names to silver Parquet paths
        """
        console.print("[bold cyan]Reactome Normalizer[/]")
        results = {}

        # Normalize pathways (human only)
        pathways_path = self._normalize_pathways()
        if pathways_path:
            results["pathways"] = pathways_path

        # Normalize gene-pathway relationships
        gene_pathways_path = self._normalize_gene_pathways()
        if gene_pathways_path:
            results["gene_pathways"] = gene_pathways_path

        # Normalize pathway hierarchy
        hierarchy_path = self._normalize_hierarchy()
        if hierarchy_path:
            results["hierarchy"] = hierarchy_path

        # Summary table
        if results:
            table = Table(title="Reactome Normalize Summary", show_header=True)
            table.add_column("Table", style="cyan")
            table.add_column("File", style="dim")
            for name, path in results.items():
                table.add_row(name, path.name)
            console.print(table)

        return results

    def _normalize_pathways(self) -> Path | None:
        """
        Normalize pathway entities (human only).
        """
        pathways_path = self.bronze_dir / "pathways.parquet"
        if not pathways_path.exists():
            return None

        dest = self.silver_dir / "pathways.parquet"

        df = pl.read_parquet(pathways_path)

        # Filter to human pathways only
        df = df.filter(pl.col("species") == "Homo sapiens")

        # Rename to canonical
        df = df.rename(
            {
                "pathway_id": "reactome_id",
                "pathway_name": "label",
            }
        ).select(["reactome_id", "label"])

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] pathways: {len(df):,} rows")
        return dest

    def _normalize_gene_pathways(self) -> Path | None:
        """
        Normalize gene-pathway relationships from UniProt mapping.
        """
        uniprot_path = self.bronze_dir / "uniprot_pathways.parquet"
        if not uniprot_path.exists():
            return None

        dest = self.silver_dir / "gene_pathways.parquet"

        df = pl.read_parquet(uniprot_path)

        # Filter to human only
        df = df.filter(pl.col("species") == "Homo sapiens")

        # Rename to canonical
        df = df.rename(
            {
                "pathway_id": "reactome_id",
                "pathway_name": "pathway_label",
            }
        )

        # Select relevant columns
        df = df.select(
            [
                "uniprot_id",
                "reactome_id",
                "pathway_label",
                "evidence_code",
            ]
        )

        # Get unique gene-pathway pairs
        df = df.unique(subset=["uniprot_id", "reactome_id"])

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] gene_pathways: {len(df):,} rows")
        return dest

    def _normalize_hierarchy(self) -> Path | None:
        """
        Normalize pathway hierarchy (parent-child relationships).
        """
        hierarchy_path = self.bronze_dir / "hierarchy.parquet"
        pathways_path = self.silver_dir / "pathways.parquet"

        if not hierarchy_path.exists():
            return None

        dest = self.silver_dir / "hierarchy.parquet"

        df = pl.read_parquet(hierarchy_path)

        # If we have pathways, filter hierarchy to human pathways
        if pathways_path.exists():
            human_pathways = pl.read_parquet(pathways_path).select("reactome_id")
            human_ids = set(human_pathways["reactome_id"].to_list())

            # Keep only relations where both parent and child are human pathways
            df = df.filter(pl.col("parent_pathway_id").is_in(human_ids) & pl.col("child_pathway_id").is_in(human_ids))

        # Rename to canonical
        df = df.rename(
            {
                "parent_pathway_id": "parent_reactome_id",
                "child_pathway_id": "child_reactome_id",
            }
        )

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] hierarchy: {len(df):,} rows")
        return dest
