"""
TWOSIDES dataset normalizer (bronze -> silver).

Produces a clean drug-drug -> adverse-event table. Drug names are lowercased
for joining to existing drug nodes; the AE keeps its MedDRA label. PRR is the
disproportionality signal strength.

Silver output:
    ddi_ae.parquet  drug_1, drug_2, ae_label, condition_meddra_id, prr, report_count
"""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseNormalizer

console = Console()


def _col(df: pl.DataFrame, *candidates: str) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


class TwosidesNormalizer(BaseNormalizer):
    """Normalize TWOSIDES bronze to silver drug-drug-AE rows."""

    source_key = "twosides"

    def normalize(self) -> dict[str, Path]:
        console.print("[bold cyan]TWOSIDES Normalizer[/]")
        bronze = self.bronze_dir / "interactions.parquet"
        if not bronze.exists():
            console.print("  [yellow][!][/] missing bronze interactions; skipping")
            return {}

        df = pl.read_parquet(bronze)

        d1 = _col(df, "drug_1_concept_name", "drug_1_name", "drug1")
        d2 = _col(df, "drug_2_concept_name", "drug_2_name", "drug2")
        ae = _col(df, "condition_concept_name", "condition_name", "event")
        meddra = _col(df, "condition_meddra_id", "meddra_id")
        prr = _col(df, "PRR", "prr")
        count = _col(df, "A", "report_count", "count")
        if d1 is None or d2 is None or ae is None:
            console.print("  [red][!][/] required TWOSIDES columns missing; skipping")
            return {}

        out = df.select(
            [
                pl.col(d1).str.to_lowercase().str.strip_chars().alias("drug_1"),
                pl.col(d2).str.to_lowercase().str.strip_chars().alias("drug_2"),
                pl.col(ae).str.strip_chars().alias("ae_label"),
                (pl.col(meddra) if meddra else pl.lit(None)).alias("condition_meddra_id"),
                (pl.col(prr).cast(pl.Float64, strict=False) if prr else pl.lit(None)).alias("prr"),
                (pl.col(count).cast(pl.Int64, strict=False) if count else pl.lit(None)).alias("report_count"),
            ]
        ).filter(
            pl.col("drug_1").is_not_null()
            & pl.col("drug_2").is_not_null()
            & pl.col("ae_label").is_not_null()
            & (pl.col("drug_1") != pl.col("drug_2"))
        )

        # TWOSIDES is ~43M raw rows; keep only stronger signals to stay tractable.
        if prr:
            out = out.filter(pl.col("prr") >= 2.0)
        if count:
            out = out.filter((pl.col("report_count") >= 10) | pl.col("report_count").is_null())

        out_path = self.silver_dir / "ddi_ae.parquet"
        out.write_parquet(out_path)
        console.print(f"  [green][ok][/] ddi_ae: {out.height:,} drug-drug-AE rows (PRR>=2, count>=10)")
        return {"ddi_ae": out_path}
