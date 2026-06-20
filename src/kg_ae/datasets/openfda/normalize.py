"""openFDA normalizer (bronze -> silver): drug label sections (drug -> AE narrative)."""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseNormalizer

console = Console()

_SECTIONS = ["adverse_reactions", "warnings", "contraindications", "boxed_warning", "drug_interactions"]


class OpenfdaNormalizer(BaseNormalizer):
    """Normalize openFDA labels to silver drug-label sections."""

    source_key = "openfda"

    def normalize(self) -> dict[str, Path]:
        console.print("[bold cyan]openFDA Normalizer[/]")
        src = self.bronze_dir / "labels.parquet"
        if not src.exists():
            console.print("  [yellow][!][/] missing bronze labels; skipping")
            return {}
        df = pl.read_parquet(src)
        cols = ["generic_name", "brand_name", "effective_time", *[c for c in _SECTIONS if c in df.columns]]
        out = (
            df.select([c for c in cols if c in df.columns])
            .with_columns(pl.col("generic_name").str.to_lowercase().str.strip_chars().alias("drug_name"))
            .filter(pl.col("drug_name").is_not_null())
            .unique("drug_name")
        )
        out_path = self.silver_dir / "labels.parquet"
        out.write_parquet(out_path)
        console.print(f"  [green][ok][/] labels: {out.height:,} drugs")
        return {"labels": out_path}
