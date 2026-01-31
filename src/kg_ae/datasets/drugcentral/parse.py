"""
DrugCentral dataset parser.

Parses raw DrugCentral files to bronze Parquet format.
"""

from pathlib import Path

import polars as pl

from kg_ae.datasets.base import BaseParser


class DrugCentralParser(BaseParser):
    """Parse DrugCentral TSV/CSV files to Parquet."""

    source_key = "drugcentral"

    def parse(self) -> dict[str, Path]:
        """
        Parse DrugCentral raw files to bronze Parquet.

        Returns:
            Dict mapping table names to Parquet file paths
        """
        results = {}

        # Parse drug structures (ID mapping)
        structures_path = self._parse_structures()
        if structures_path:
            results["structures"] = structures_path

        # Parse drug-target interactions
        targets_path = self._parse_targets()
        if targets_path:
            results["targets"] = targets_path

        # Parse approved drugs
        approved_path = self._parse_approved()
        if approved_path:
            results["approved"] = approved_path

        return results

    def _parse_structures(self) -> Path | None:
        """Parse structures.smiles.tsv to Parquet."""
        src = self.raw_dir / "structures.smiles.tsv"
        if not src.exists():
            return None

        dest = self.bronze_dir / "structures.parquet"

        # structures.smiles.tsv has header row
        df = pl.read_csv(src, separator="\t")

        df.write_parquet(dest)
        print(f"  [parsed] structures: {len(df):,} rows → {dest.name}")
        return dest

    def _parse_targets(self) -> Path | None:
        """Parse drug.target.interaction.tsv.gz to Parquet."""
        src = self.raw_dir / "drug.target.interaction.tsv.gz"
        if not src.exists():
            return None

        dest = self.bronze_dir / "targets.parquet"

        # TSV with header
        df = pl.read_csv(src, separator="\t")

        df.write_parquet(dest)
        print(f"  [parsed] targets: {len(df):,} rows → {dest.name}")
        return dest

    def _parse_approved(self) -> Path | None:
        """Parse FDA+EMA+PMDA_Approved.csv to Parquet."""
        src = self.raw_dir / "FDA+EMA+PMDA_Approved.csv"
        if not src.exists():
            return None

        dest = self.bronze_dir / "approved.parquet"

        # CSV with header
        df = pl.read_csv(src)

        df.write_parquet(dest)
        print(f"  [parsed] approved: {len(df):,} rows → {dest.name}")
        return dest
