"""
Open Targets normalizer.

Converts bronze Parquet to silver with canonical IDs.
"""

from pathlib import Path

import polars as pl
from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseNormalizer

console = Console()


class OpenTargetsNormalizer(BaseNormalizer):
    """Normalize Open Targets data to silver layer with canonical IDs."""

    source_key = "opentargets"

    def normalize(self) -> dict[str, Path]:
        """
        Normalize bronze Open Targets data to silver.

        Returns:
            Dict mapping table names to silver Parquet paths
        """
        console.print("[bold cyan]Open Targets Normalizer[/]")
        results = {}

        # Normalize diseases
        diseases_path = self._normalize_diseases()
        if diseases_path:
            results["diseases"] = diseases_path

        # Normalize gene-disease associations
        associations_path = self._normalize_associations()
        if associations_path:
            results["associations"] = associations_path

        # Create gene lookup from targets
        genes_path = self._normalize_genes()
        if genes_path:
            results["genes"] = genes_path

        # Summary table
        if results:
            table = Table(title="Open Targets Normalize Summary", show_header=True)
            table.add_column("Table", style="cyan")
            table.add_column("File", style="dim")
            for name, path in results.items():
                table.add_row(name, path.name)
            console.print(table)

        return results

    def _normalize_diseases(self) -> Path | None:
        """
        Normalize disease entities, extracting MONDO/DOID mappings.
        """
        diseases_path = self.bronze_dir / "diseases.parquet"
        if not diseases_path.exists():
            return None

        dest = self.silver_dir / "diseases.parquet"

        df = pl.read_parquet(diseases_path)

        # Rename columns to canonical
        df = df.rename(
            {
                "id": "efo_id",  # Open Targets uses EFO IDs
                "name": "label",
            }
        )

        # Extract MONDO and DOID from dbXRefs list
        # dbXRefs is a list of strings like ["MONDO:0005148", "DOID:9352", ...]
        if "dbXRefs" in df.columns:
            df = df.with_columns(
                [
                    # Extract MONDO ID
                    pl.col("dbXRefs")
                    .list.eval(pl.element().filter(pl.element().str.starts_with("MONDO:")))
                    .list.first()
                    .alias("mondo_id"),
                    # Extract DOID
                    pl.col("dbXRefs")
                    .list.eval(pl.element().filter(pl.element().str.starts_with("DOID:")))
                    .list.first()
                    .alias("doid"),
                ]
            )

        # Select final columns
        df = df.select(
            [
                "efo_id",
                "label",
                pl.col("mondo_id").fill_null(""),
                pl.col("doid").fill_null(""),
                "description",
            ]
        )

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] diseases: {len(df):,} rows")
        return dest

    def _normalize_associations(self) -> Path | None:
        """
        Normalize gene-disease associations.
        """
        associations_path = self.bronze_dir / "associations.parquet"
        if not associations_path.exists():
            return None

        dest = self.silver_dir / "associations.parquet"

        df = pl.read_parquet(associations_path)

        # Rename columns to canonical
        df = df.rename(
            {
                "targetId": "ensembl_gene_id",
                "diseaseId": "efo_id",
            }
        )

        # Filter to high-confidence associations (score > 0.1)
        df = df.filter(pl.col("score") > 0.1)

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] associations: {len(df):,} rows")
        return dest

    def _normalize_genes(self) -> Path | None:
        """
        Normalize gene/target data for ID mapping.
        """
        targets_path = self.bronze_dir / "targets.parquet"
        if not targets_path.exists():
            return None

        dest = self.silver_dir / "genes.parquet"

        df = pl.read_parquet(targets_path)

        # Rename columns
        df = df.rename(
            {
                "id": "ensembl_gene_id",
                "approvedSymbol": "symbol",
                "approvedName": "name",
            }
        )

        # Extract UniProt ID from proteinIds list
        # proteinIds is a list of structs with id and source fields
        if "proteinIds" in df.columns:
            df = df.with_columns(
                [
                    pl.col("proteinIds")
                    .list.eval(
                        pl.element()
                        .struct.field("id")
                        .filter(pl.element().struct.field("source") == "uniprot_swissprot")
                    )
                    .list.first()
                    .alias("uniprot_id"),
                ]
            )
        else:
            df = df.with_columns(pl.lit(None).alias("uniprot_id"))

        # Select final columns
        df = df.select(
            [
                "ensembl_gene_id",
                "symbol",
                "name",
                "uniprot_id",
            ]
        )

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] genes: {len(df):,} rows")
        return dest
