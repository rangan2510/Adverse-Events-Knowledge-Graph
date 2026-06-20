"""STRING normalizer (bronze -> silver): gene-gene protein interactions."""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseNormalizer

console = Console()


class StringNormalizer(BaseNormalizer):
    """Normalize STRING links to silver gene-gene interactions."""

    source_key = "string"

    def normalize(self) -> dict[str, Path]:
        console.print("[bold cyan]STRING Normalizer[/]")
        src = self.bronze_dir / "links.parquet"
        if not src.exists():
            console.print("  [yellow][!][/] missing bronze links; skipping")
            return {}
        df = pl.read_parquet(src)
        out = df.select(
            [
                pl.col("gene1").str.strip_chars().alias("gene_1"),
                pl.col("gene2").str.strip_chars().alias("gene_2"),
                (pl.col("combined_score").cast(pl.Float64, strict=False) / 1000.0).alias("score"),
            ]
        ).filter(
            pl.col("gene_1").is_not_null()
            & pl.col("gene_2").is_not_null()
            & (pl.col("gene_1") != pl.col("gene_2"))
        )
        out_path = self.silver_dir / "interactions.parquet"
        out.write_parquet(out_path)
        console.print(f"  [green][ok][/] interactions: {out.height:,} gene-gene rows")
        return {"interactions": out_path}
