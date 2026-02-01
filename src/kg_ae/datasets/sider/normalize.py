"""
SIDER dataset normalizer.

Transforms bronze Parquet files to silver format with canonical IDs.
"""

from pathlib import Path

import polars as pl
from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseNormalizer

console = Console()


class SiderNormalizer(BaseNormalizer):
    """Normalize SIDER data to canonical format."""

    source_key = "sider"

    def normalize(self) -> dict[str, Path]:
        """
        Normalize SIDER bronze data to silver.

        Creates:
        - drugs.parquet: Drug entities with STITCH IDs
        - adverse_events.parquet: Unique adverse event terms
        - drug_ae_pairs.parquet: Drug-AE associations with frequencies

        Returns:
            Dict mapping table names to output file paths
        """
        console.print("[bold cyan]SIDER Normalizer[/]")
        results = {}

        # Load bronze data
        drug_names = pl.read_parquet(self.bronze_dir / "drug_names.parquet")
        side_effects = pl.read_parquet(self.bronze_dir / "side_effects.parquet")
        frequencies = pl.read_parquet(self.bronze_dir / "frequencies.parquet")

        # 1. Normalize drugs
        drugs_path = self._normalize_drugs(drug_names)
        results["drugs"] = drugs_path

        # 2. Normalize adverse events (unique terms)
        ae_path = self._normalize_adverse_events(side_effects)
        results["adverse_events"] = ae_path

        # 3. Normalize drug-AE pairs with frequency data
        pairs_path = self._normalize_drug_ae_pairs(side_effects, frequencies)
        results["drug_ae_pairs"] = pairs_path

        # Summary table
        table = Table(title="SIDER Normalize Summary", show_header=True)
        table.add_column("Table", style="cyan")
        table.add_column("File", style="dim")
        for name, path in results.items():
            table.add_row(name, path.name)
        console.print(table)

        return results

    def _normalize_drugs(self, drug_names: pl.DataFrame) -> Path:
        """Create normalized drug entities."""
        dest = self.silver_dir / "drugs.parquet"

        # STITCH IDs have format CIDxxxxxxxxx
        # Extract numeric part as pubchem_cid (STITCH flat IDs = PubChem CID + 100000000)
        drugs = drug_names.with_columns([
            # Extract numeric part from STITCH ID
            pl.col("stitch_id").str.replace("CID", "").cast(pl.Int64).alias("stitch_numeric"),
        ]).with_columns([
            # STITCH flat ID = PubChem CID + 100000000
            (pl.col("stitch_numeric") - 100000000).alias("pubchem_cid"),
        ]).select([
            "stitch_id",
            "stitch_numeric",
            "pubchem_cid",
            pl.col("drug_name").alias("preferred_name"),
        ]).unique(subset=["stitch_id"])

        drugs.write_parquet(dest)
        console.print(f"    [green]✓[/] drugs: {len(drugs):,} unique drugs")
        return dest

    def _normalize_adverse_events(self, side_effects: pl.DataFrame) -> Path:
        """Create normalized adverse event entities."""
        dest = self.silver_dir / "adverse_events.parquet"

        # Get unique AE terms with their UMLS CUIs
        # Use PT (Preferred Term) level when available, otherwise LLT
        ae_terms = (
            side_effects
            .filter(pl.col("meddra_type") == "PT")  # Prefer preferred terms
            .select([
                "umls_cui_meddra",
                "side_effect_name",
            ])
            .unique()
            .with_columns([
                pl.col("side_effect_name").alias("ae_label"),
                pl.lit("UMLS").alias("ae_ontology"),
                pl.col("umls_cui_meddra").alias("ae_code"),
            ])
            .select(["ae_code", "ae_label", "ae_ontology"])
        )

        ae_terms.write_parquet(dest)
        console.print(f"    [green]✓[/] adverse_events: {len(ae_terms):,} unique AEs")
        return dest

    def _normalize_drug_ae_pairs(
        self, side_effects: pl.DataFrame, frequencies: pl.DataFrame
    ) -> Path:
        """Create normalized drug-AE association pairs."""
        dest = self.silver_dir / "drug_ae_pairs.parquet"

        # Get unique drug-AE pairs from side_effects (all associations)
        pairs_base = (
            side_effects
            .filter(pl.col("meddra_type") == "PT")  # Use preferred terms
            .select([
                "stitch_id_flat",
                "umls_cui_meddra",
                "side_effect_name",
            ])
            .unique()
        )

        # Get frequency data where available (aggregate by drug-AE pair)
        freq_data = (
            frequencies
            .filter(pl.col("meddra_type") == "PT")
            .group_by(["stitch_id_flat", "umls_cui_meddra"])
            .agg([
                pl.col("frequency_lower").mean().alias("freq_lower_avg"),
                pl.col("frequency_upper").mean().alias("freq_upper_avg"),
                pl.col("frequency").first().alias("frequency_text"),
            ])
        )

        # Join pairs with frequency data
        pairs = (
            pairs_base
            .join(
                freq_data,
                on=["stitch_id_flat", "umls_cui_meddra"],
                how="left",
            )
            .with_columns([
                # Compute average frequency where available
                ((pl.col("freq_lower_avg") + pl.col("freq_upper_avg")) / 2)
                .alias("frequency_score"),
            ])
            .select([
                pl.col("stitch_id_flat").alias("stitch_id"),
                pl.col("umls_cui_meddra").alias("ae_code"),
                "side_effect_name",
                "frequency_text",
                "frequency_score",
            ])
        )

        pairs.write_parquet(dest)
        console.print(f"    [green]✓[/] drug_ae_pairs: {len(pairs):,} associations")
        return dest
