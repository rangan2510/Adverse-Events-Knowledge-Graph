"""
DrugCentral normalizer.

Converts bronze Parquet to silver with canonical IDs.
"""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseNormalizer

console = Console()


class DrugCentralNormalizer(BaseNormalizer):
    """Normalize DrugCentral data to silver layer with canonical IDs."""

    source_key = "drugcentral"

    def normalize(self) -> dict[str, Path]:
        """
        Normalize bronze DrugCentral data to silver.

        Returns:
            Dict mapping table names to silver Parquet paths
        """
        console.print("[bold cyan]DrugCentral Normalizer[/]")
        results = {}

        # Normalize drug entities
        drugs_path = self._normalize_drugs()
        if drugs_path:
            results["drugs"] = drugs_path

        # Normalize gene/target entities
        genes_path = self._normalize_genes()
        if genes_path:
            results["genes"] = genes_path

        # Normalize drug-target interactions
        interactions_path = self._normalize_interactions()
        if interactions_path:
            results["interactions"] = interactions_path

        return results

    def _normalize_drugs(self) -> Path | None:
        """
        Normalize drug entities from structures + approved files.

        Combines structure data (SMILES, InChIKey) with approval status.
        """
        structures_path = self.bronze_dir / "structures.parquet"
        approved_path = self.bronze_dir / "approved.parquet"

        if not structures_path.exists():
            return None

        dest = self.silver_dir / "drugs.parquet"

        # Load structures - this has DrugCentral IDs and structure info
        df_struct = pl.read_parquet(structures_path)

        # Rename columns to canonical names
        # Expected columns: ID, INN, CAS_RN, SMILES, InChIKey
        col_map = {
            "ID": "drugcentral_id",
            "INN": "preferred_name",
            "CAS_RN": "cas_rn",
            "SMILES": "smiles",
            "InChIKey": "inchikey",
        }
        # Only rename columns that exist
        existing_renames = {k: v for k, v in col_map.items() if k in df_struct.columns}
        df = df_struct.rename(existing_renames)

        # Add approval status if available
        if approved_path.exists():
            df_approved = pl.read_parquet(approved_path)
            # Join on DrugCentral ID if column exists
            if "drugcentral_id" in df.columns and "ID" in df_approved.columns:
                df_approved = df_approved.rename({"ID": "drugcentral_id"})
                df_approved = df_approved.select(["drugcentral_id"]).with_columns(pl.lit(True).alias("is_approved"))
                df = df.join(df_approved, on="drugcentral_id", how="left")
                df = df.with_columns(pl.col("is_approved").fill_null(False))

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] drugs: {len(df):,} rows → {dest.name}")
        return dest

    def _normalize_genes(self) -> Path | None:
        """
        Extract unique gene/protein targets from interaction data.
        """
        targets_path = self.bronze_dir / "targets.parquet"
        if not targets_path.exists():
            return None

        dest = self.silver_dir / "genes.parquet"

        df = pl.read_parquet(targets_path)

        # Extract unique targets
        # Columns: GENE, SWISSPROT, TARGET_NAME, TARGET_CLASS, ACCESSION
        gene_cols = []
        for col in ["GENE", "SWISSPROT", "TARGET_NAME", "TARGET_CLASS", "ACCESSION"]:
            if col in df.columns:
                gene_cols.append(col)

        if not gene_cols:
            console.print("  [yellow][warn][/] No gene columns found in targets")
            return None

        # Get unique genes with their info
        df_genes = df.select(gene_cols).unique()

        # Rename to canonical - ACCESSION is the real UniProt ID, SWISSPROT is entry name
        col_map = {
            "GENE": "symbol",
            "ACCESSION": "uniprot_id",  # P12345 format
            "SWISSPROT": "swissprot_entry",  # ABC1_HUMAN format
            "TARGET_NAME": "target_name",
            "TARGET_CLASS": "target_class",
        }
        existing_renames = {k: v for k, v in col_map.items() if k in df_genes.columns}
        df_genes = df_genes.rename(existing_renames)

        # Filter to rows with valid gene symbol
        df_genes = df_genes.filter(pl.col("symbol").is_not_null())

        # Handle multi-value fields (take first)
        if "uniprot_id" in df_genes.columns:
            df_genes = df_genes.with_columns(pl.col("uniprot_id").str.split("|").list.first())
        if "symbol" in df_genes.columns:
            df_genes = df_genes.with_columns(pl.col("symbol").str.split("|").list.first())

        df_genes.write_parquet(dest)
        console.print(f"    [green]✓[/] genes: {len(df_genes):,} rows → {dest.name}")
        return dest

    def _normalize_interactions(self) -> Path | None:
        """
        Normalize drug-target interactions.
        """
        targets_path = self.bronze_dir / "targets.parquet"
        if not targets_path.exists():
            return None

        dest = self.silver_dir / "interactions.parquet"

        df = pl.read_parquet(targets_path)

        # Rename columns to canonical
        col_map = {
            "STRUCT_ID": "drugcentral_id",
            "DRUG_NAME": "drug_name",
            "GENE": "gene_symbol",
            "ACCESSION": "uniprot_id",  # P12345 format
            "SWISSPROT": "swissprot_entry",  # entry name
            "ACTION_TYPE": "action_type",
            "ACT_VALUE": "activity_value",
            "ACT_UNIT": "activity_unit",
            "ACT_TYPE": "activity_type",
            "ORGANISM": "organism",
            "TARGET_NAME": "target_name",
            "TARGET_CLASS": "target_class",
            "MOA": "mechanism_of_action",
        }
        existing_renames = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(existing_renames)

        # Filter to human targets only for MVP
        if "organism" in df.columns:
            df = df.filter(pl.col("organism") == "Homo sapiens")

        # Handle multi-value fields (take first)
        if "gene_symbol" in df.columns:
            df = df.with_columns(pl.col("gene_symbol").str.split("|").list.first())
        if "uniprot_id" in df.columns:
            df = df.with_columns(pl.col("uniprot_id").str.split("|").list.first())

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] interactions: {len(df):,} rows → {dest.name}")
        return dest
