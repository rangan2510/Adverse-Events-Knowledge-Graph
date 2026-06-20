"""FAERS normalizer (bronze -> silver): drug-AE disproportionality signals."""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseNormalizer

console = Console()


class FaersNormalizer(BaseNormalizer):
    """Normalize FAERS signals to silver drug-AE rows."""

    source_key = "faers"

    def normalize(self) -> dict[str, Path]:
        console.print("[bold cyan]FAERS Normalizer[/]")
        src = self.bronze_dir / "signals.parquet"
        if not src.exists():
            console.print("  [yellow][!][/] missing bronze signals; skipping")
            return {}
        df = pl.read_parquet(src)
        out = df.select(
            [
                pl.col("drug_name").str.to_lowercase().str.strip_chars().alias("drug_name"),
                pl.col("ae_term").str.strip_chars().alias("ae_label"),
                pl.col("count").cast(pl.Int64, strict=False).alias("report_count"),
                pl.col("prr").cast(pl.Float64, strict=False).alias("prr"),
                pl.col("ror").cast(pl.Float64, strict=False).alias("ror"),
                pl.col("chi2").cast(pl.Float64, strict=False).alias("chi2"),
            ]
        ).filter(pl.col("drug_name").is_not_null() & pl.col("ae_label").is_not_null())
        out_path = self.silver_dir / "signals.parquet"
        out.write_parquet(out_path)
        console.print(f"  [green][ok][/] signals: {out.height:,} drug-AE rows")
        return {"signals": out_path}
