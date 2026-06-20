"""HPO normalizer (bronze -> silver): gene-disease (phenotype) associations."""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseNormalizer

console = Console()


class HpoNormalizer(BaseNormalizer):
    """Normalize HPO genes_to_phenotype to silver gene-disease rows.

    HPO links genes to diseases (disease_id) and phenotype terms. We use the
    gene -> disease relation (via disease_id + a human-readable label when
    available) as gene-disease associations.
    """

    source_key = "hpo"

    def normalize(self) -> dict[str, Path]:
        console.print("[bold cyan]HPO Normalizer[/]")
        g2p = self.bronze_dir / "genes_to_phenotype.parquet"
        dp = self.bronze_dir / "disease_phenotype.parquet"
        if not g2p.exists():
            console.print("  [yellow][!][/] missing bronze genes_to_phenotype; skipping")
            return {}
        df = pl.read_parquet(g2p)

        # disease_id -> disease_name from disease_phenotype, if available.
        label_map = None
        if dp.exists():
            d = pl.read_parquet(dp)
            if "database_id" in d.columns and "disease_name" in d.columns:
                label_map = d.select(
                    [pl.col("database_id").alias("disease_id"), pl.col("disease_name")]
                ).unique()

        out = df.select(
            [
                pl.col("gene_symbol").str.strip_chars().alias("gene_symbol"),
                pl.col("disease_id").alias("disease_id"),
            ]
        ).filter(pl.col("gene_symbol").is_not_null() & pl.col("disease_id").is_not_null())

        if label_map is not None:
            out = out.join(label_map, on="disease_id", how="left")
        else:
            out = out.with_columns(pl.lit(None).alias("disease_name"))

        out = out.with_columns(
            pl.coalesce([pl.col("disease_name"), pl.col("disease_id")]).alias("disease_label")
        ).unique(["gene_symbol", "disease_id"])

        out_path = self.silver_dir / "gene_disease.parquet"
        out.write_parquet(out_path)
        console.print(f"  [green][ok][/] gene_disease: {out.height:,} rows")
        return {"gene_disease": out_path}
