"""
BindingDB dataset normalizer (bronze -> silver).

Cleans affinity strings (e.g. ">10000", "<1", "1.2") to numeric nM, picks the
strongest (smallest) affinity per ligand-target pair across Ki/Kd/IC50/EC50,
and derives a normalized binding strength score.

Silver output:
    interactions.parquet  ligand_name, uniprot_id, affinity_nm, affinity_type,
                          strength_score
"""

import math
from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseNormalizer

console = Console()

_AFFINITY_COLS = [("ki_nm", "Ki"), ("kd_nm", "Kd"), ("ic50_nm", "IC50"), ("ec50_nm", "EC50")]


def _to_nm(value: str | None) -> float | None:
    """Parse a BindingDB affinity string to nM (drop comparator prefixes)."""
    if value is None:
        return None
    s = str(value).strip().lstrip("><=~ ").replace(",", "")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def _strength(nm: float) -> float:
    """Map affinity (nM) to a 0-1 strength score. ~ pAffinity scaled.

    pX = 9 - log10(nM); typical range pX 4 (weak) .. 10 (very strong).
    Scale to [0,1] over pX in [4, 10].
    """
    px = 9.0 - math.log10(nm)
    return max(0.0, min(1.0, (px - 4.0) / 6.0))


class BindingdbNormalizer(BaseNormalizer):
    """Normalize BindingDB bronze interactions to silver drug-target edges."""

    source_key = "bindingdb"

    def normalize(self) -> dict[str, Path]:
        console.print("[bold cyan]BindingDB Normalizer[/]")
        bronze = self.bronze_dir / "interactions.parquet"
        if not bronze.exists():
            console.print("  [yellow][!][/] missing bronze interactions; skipping")
            return {}

        df = pl.read_parquet(bronze)

        # Clean each affinity column to numeric nM via a Python map (values are messy).
        rows: list[dict] = []
        for r in df.iter_rows(named=True):
            best_nm: float | None = None
            best_type: str | None = None
            for col, label in _AFFINITY_COLS:
                nm = _to_nm(r.get(col))
                if nm is not None and (best_nm is None or nm < best_nm):
                    best_nm = nm
                    best_type = label
            if best_nm is None:
                continue
            uni = (r.get("uniprot_id") or "").strip()
            name = (r.get("ligand_name") or "").strip()
            if not uni or not name:
                continue
            rows.append(
                {
                    "ligand_name": name,
                    "uniprot_id": uni,
                    "affinity_nm": best_nm,
                    "affinity_type": best_type,
                    "strength_score": _strength(best_nm),
                }
            )

        if not rows:
            console.print("  [yellow][!][/] no usable affinities; skipping")
            return {}

        out_df = pl.DataFrame(rows)
        # Keep the strongest measurement per (ligand, target).
        out_df = (
            out_df.sort("affinity_nm")
            .group_by(["ligand_name", "uniprot_id"])
            .first()
            .sort("strength_score", descending=True)
        )

        out = self.silver_dir / "interactions.parquet"
        out_df.write_parquet(out)
        console.print(f"  [green][ok][/] interactions: {out_df.height:,} drug-target pairs")
        return {"interactions": out}
