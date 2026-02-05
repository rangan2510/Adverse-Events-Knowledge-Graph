"""
GtoPdb dataset parser.

Parses GtoPdb TSV files to bronze Parquet format.
All files have a comment line at the top that needs to be skipped.
"""

from pathlib import Path

import polars as pl
from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseParser

console = Console()


class GtoPdbParser(BaseParser):
    """Parse GtoPdb TSV files to Parquet."""

    source_key = "gtop"

    def parse(self) -> dict[str, Path]:
        """
        Parse GtoPdb raw files to bronze Parquet.

        Returns:
            Dict mapping table names to Parquet file paths
        """
        console.print("[bold cyan]GtoPdb Parser[/]")
        results = {}

        # Parse ligands (drugs)
        ligands_path = self._parse_ligands()
        if ligands_path:
            results["ligands"] = ligands_path

        # Parse targets
        targets_path = self._parse_targets()
        if targets_path:
            results["targets"] = targets_path

        # Parse HGNC mapping
        hgnc_map_path = self._parse_hgnc_mapping()
        if hgnc_map_path:
            results["hgnc_mapping"] = hgnc_map_path

        # Parse interactions
        interactions_path = self._parse_interactions()
        if interactions_path:
            results["interactions"] = interactions_path

        # Summary table
        table = Table(title="GtoPdb Parse Summary", show_header=True)
        table.add_column("Table", style="cyan")
        table.add_column("File", style="dim")
        for name, path in results.items():
            table.add_row(name, path.name)
        console.print(table)

        return results

    def _read_gtopdb_tsv(self, path: Path, separator: str = "\t") -> pl.DataFrame | None:
        """
        Read a GtoPdb TSV file, skipping the version comment line.

        Args:
            path: Path to TSV file
            separator: Field separator

        Returns:
            DataFrame or None if file not found
        """
        if not path.exists():
            console.print(f"  [dim][skip] {path.name} not found[/]")
            return None

        # Skip the first comment line
        return pl.read_csv(
            path,
            separator=separator,
            skip_rows=1,
            infer_schema_length=5000,
            truncate_ragged_lines=True,
            quote_char='"',
        )

    def _parse_ligands(self) -> Path | None:
        """Parse ligands.tsv to Parquet."""
        src = self.raw_dir / "ligands.tsv"
        df = self._read_gtopdb_tsv(src)
        if df is None:
            return None

        dest = self.bronze_dir / "ligands.parquet"

        # Select and rename relevant columns
        df = df.select(
            [
                pl.col("Ligand ID").alias("ligand_id"),
                pl.col("Name").alias("name"),
                pl.col("Species").alias("species"),
                pl.col("Type").alias("ligand_type"),
                pl.col("Approved").alias("approved"),
                pl.col("PubChem SID").alias("pubchem_sid"),
                pl.col("PubChem CID").alias("pubchem_cid"),
                pl.col("ChEMBL ID").alias("chembl_id"),
                pl.col("UniProt ID").alias("uniprot_id"),
                pl.col("Ensembl ID").alias("ensembl_id"),
                pl.col("INN").alias("inn"),
                pl.col("Synonyms").alias("synonyms"),
                pl.col("SMILES").alias("smiles"),
                pl.col("InChIKey").alias("inchikey"),
                pl.col("IUPAC name").alias("iupac_name"),
            ]
        )

        # Filter to small molecules and approved drugs (most useful)
        # Keep all types for now but flag approved
        # GtoPdb uses 'yes' for approved drugs
        df = df.with_columns(
            [
                pl.when(pl.col("approved").str.to_lowercase() == "yes")
                .then(pl.lit(True))
                .otherwise(pl.lit(False))
                .alias("is_approved"),
            ]
        )

        df.write_parquet(dest)
        approved_count = df.filter(pl.col("is_approved")).height
        console.print(f"    [green]✓[/] ligands: {len(df):,} total, {approved_count:,} approved")
        return dest

    def _parse_targets(self) -> Path | None:
        """Parse targets_and_families.tsv to Parquet."""
        src = self.raw_dir / "targets_and_families.tsv"
        df = self._read_gtopdb_tsv(src)
        if df is None:
            return None

        dest = self.bronze_dir / "targets.parquet"

        # Get actual columns present (they vary by version)
        cols = df.columns
        selected_cols = []

        col_map = {
            "Target id": "target_id",
            "Target name": "target_name",
            "Target abbreviated name": "target_abbrev",
            "Family id": "family_id",
            "Family name": "family_name",
            "Type": "target_type",
            "Human Ensembl Gene": "human_ensembl_gene",
            "Human Entrez Gene": "human_entrez_gene",
            "Human SwissProt": "human_swissprot",
        }

        for orig_col, new_col in col_map.items():
            if orig_col in cols:
                selected_cols.append(pl.col(orig_col).alias(new_col))

        if not selected_cols:
            console.print("  [yellow][warn][/] No expected columns found in targets file")
            console.print(f"  Available columns: {cols[:10]}...")
            return None

        df = df.select(selected_cols)

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] targets: {len(df):,} rows")
        return dest

    def _parse_hgnc_mapping(self) -> Path | None:
        """Parse GtP_to_HGNC_mapping.csv to Parquet."""
        src = self.raw_dir / "GtP_to_HGNC_mapping.csv"
        df = self._read_gtopdb_tsv(src, separator=",")
        if df is None:
            return None

        dest = self.bronze_dir / "hgnc_mapping.parquet"

        df = df.select(
            [
                pl.col("HGNC Symbol").alias("hgnc_symbol"),
                pl.col("HGNC ID").alias("hgnc_numeric_id"),  # numeric part only
                pl.col("IUPHAR Name").alias("iuphar_name"),
                pl.col("IUPHAR ID").alias("iuphar_id"),  # = target_id
            ]
        )

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] hgnc_mapping: {len(df):,} rows")
        return dest

    def _parse_interactions(self) -> Path | None:
        """Parse interactions.tsv to Parquet."""
        src = self.raw_dir / "interactions.tsv"
        df = self._read_gtopdb_tsv(src)
        if df is None:
            return None

        dest = self.bronze_dir / "interactions.parquet"

        # Select key columns for drug-target interactions
        cols = df.columns
        col_map = {
            "Target": "target_name",
            "Target ID": "target_id",
            "Target Gene Symbol": "target_gene_symbol",
            "Target UniProt ID": "target_uniprot_id",
            "Target Ensembl Gene ID": "target_ensembl_gene_id",
            "Target Species": "target_species",
            "Ligand ID": "ligand_id",
            "Ligand": "ligand_name",
            "Ligand Type": "ligand_type",
            "Ligand PubChem SID": "ligand_pubchem_sid",
            "Approved": "approved",
            "Type": "interaction_type",
            "Action": "action",
            "Action comment": "action_comment",
            "Selectivity": "selectivity",
            "Endogenous": "endogenous",
            "Primary Target": "primary_target",
            "Affinity Units": "affinity_units",
            "Affinity Median": "affinity_median",
            "Affinity High": "affinity_high",
            "Affinity Low": "affinity_low",
            "PubMed ID": "pubmed_id",
        }

        selected_cols = []
        for orig_col, new_col in col_map.items():
            if orig_col in cols:
                selected_cols.append(pl.col(orig_col).alias(new_col))

        df = df.select(selected_cols)

        # Filter to human targets only
        if "target_species" in df.columns:
            df = df.filter(pl.col("target_species") == "Human")

        # Convert affinity to numeric
        for col in ["affinity_median", "affinity_high", "affinity_low"]:
            if col in df.columns:
                df = df.with_columns([pl.col(col).cast(pl.Float64, strict=False).alias(col)])

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] interactions: {len(df):,} human interactions")
        return dest
