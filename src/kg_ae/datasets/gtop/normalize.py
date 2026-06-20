"""Guide to Pharmacology (gtop) normalizer (bronze -> silver): drug-target interactions."""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseNormalizer

console = Console()


class GtopNormalizer(BaseNormalizer):
    """Normalize gtop interactions to silver drug-target rows."""

    source_key = "gtop"

    def normalize(self) -> dict[str, Path]:
        console.print("[bold cyan]gtop Normalizer[/]")
        src = self.bronze_dir / "interactions.parquet"
        if not src.exists():
            console.print("  [yellow][!][/] missing bronze interactions; skipping")
            return {}
        df = pl.read_parquet(src)
        out = (
            df.filter(
                pl.col("target_species").str.contains("(?i)human").fill_null(True)
                if "target_species" in df.columns
                else pl.lit(True)
            )
            .select(
                [
                    pl.col("ligand_name").str.to_lowercase().str.strip_chars().alias("drug_name"),
                    pl.col("target_gene_symbol").str.strip_chars().alias("gene_symbol"),
                    pl.col("target_uniprot_id").alias("uniprot_id"),
                    pl.col("action").alias("action"),
                    pl.col("interaction_type").alias("interaction_type"),
                    pl.col("affinity_median").cast(pl.Float64, strict=False).alias("affinity_median"),
                ]
            )
            .filter(pl.col("drug_name").is_not_null() & pl.col("gene_symbol").is_not_null())
            .unique(["drug_name", "gene_symbol"])
        )
        out_path = self.silver_dir / "interactions.parquet"
        out.write_parquet(out_path)
        console.print(f"  [green][ok][/] interactions: {out.height:,} drug-target rows")
        return {"interactions": out_path}
