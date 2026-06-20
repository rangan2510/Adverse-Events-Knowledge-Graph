"""ClinGen normalizer (bronze -> silver): curated gene-disease validity."""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseNormalizer

console = Console()

# Map ClinGen classification -> a coarse strength score.
_CLASSIFICATION_SCORE = {
    "definitive": 1.0,
    "strong": 0.9,
    "moderate": 0.6,
    "limited": 0.4,
    "disputed": 0.2,
    "refuted": 0.0,
    "no known disease relationship": 0.0,
}


class ClingenNormalizer(BaseNormalizer):
    """Normalize ClinGen validity to silver gene-disease rows."""

    source_key = "clingen"

    def normalize(self) -> dict[str, Path]:
        console.print("[bold cyan]ClinGen Normalizer[/]")
        src = self.bronze_dir / "validity.parquet"
        if not src.exists():
            console.print("  [yellow][!][/] missing bronze validity; skipping")
            return {}
        df = pl.read_parquet(src)
        out = (
            df.select(
                [
                    pl.col("gene_symbol").str.strip_chars().alias("gene_symbol"),
                    pl.col("disease_label").str.strip_chars().alias("disease_label"),
                    pl.col("mondo_id").alias("mondo_id"),
                    pl.col("classification").str.to_lowercase().str.strip_chars().alias("classification"),
                ]
            )
            .filter(pl.col("gene_symbol").is_not_null() & pl.col("disease_label").is_not_null())
            .with_columns(
                pl.col("classification").replace_strict(_CLASSIFICATION_SCORE, default=0.5).alias("score")
            )
        )
        out_path = self.silver_dir / "gene_disease.parquet"
        out.write_parquet(out_path)
        console.print(f"  [green][ok][/] gene_disease: {out.height:,} rows")
        return {"gene_disease": out_path}
