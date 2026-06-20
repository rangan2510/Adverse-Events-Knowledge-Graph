"""
OnSIDES dataset normalizer (bronze -> silver).

Joins the OnSIDES tables into a flat drug -> adverse-event association table
keyed by RxNorm ingredient name (the drug) and MedDRA term (the AE), so the
graph builder can merge drugs by name (like SIDER) and reuse/create AE nodes.

Silver outputs:
    drug_ae_pairs.parquet   drug_name, ae_label, meddra_id, source, confidence
    adverse_events.parquet  meddra_id, ae_label
"""

import contextlib
from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseNormalizer

console = Console()


def _col(df: pl.DataFrame, *candidates: str) -> str | None:
    """Return the first candidate column present in df (case-insensitive)."""
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


class OnsidesNormalizer(BaseNormalizer):
    """Normalize OnSIDES bronze tables to silver drug-AE pairs."""

    source_key = "onsides"

    def _read(self, name: str) -> pl.DataFrame | None:
        path = self.bronze_dir / f"{name}.parquet"
        if not path.exists():
            console.print(f"  [yellow][!][/] missing bronze {name}, cannot normalize")
            return None
        return pl.read_parquet(path)

    def normalize(self) -> dict[str, Path]:
        console.print("[bold cyan]OnSIDES Normalizer[/]")

        pae = self._read("product_adverse_effect")
        label = self._read("product_label")
        p2rx = self._read("product_to_rxnorm")
        ing2prod = self._read("ingredient_to_product")
        ingredient = self._read("ingredient")
        meddra = self._read("meddra")
        if any(x is None for x in (pae, label, p2rx, ing2prod, ingredient, meddra)):
            console.print("  [red][!][/] missing required tables; skipping OnSIDES normalize")
            return {}

        # Resolve column names defensively (schema may vary slightly by release).
        pae_label = _col(pae, "product_label_id", "label_id")
        pae_meddra = _col(pae, "effect_meddra_id", "meddra_id")
        pae_conf = _col(pae, "pred1", "confidence", "score")
        label_id = _col(label, "label_id", "id")
        label_src = _col(label, "source")
        p2rx_label = _col(p2rx, "label_id")
        p2rx_prod = _col(p2rx, "rxnorm_product_id", "product_id")
        i2p_prod = _col(ing2prod, "product_id", "rxnorm_product_id")
        i2p_ing = _col(ing2prod, "ingredient_id", "rxnorm_ingredient_id")
        ing_id = _col(ingredient, "rxnorm_id", "ingredient_id", "id")
        ing_name = _col(ingredient, "rxnorm_name", "name", "ingredient_name")
        meddra_id = _col(meddra, "meddra_id", "id")
        meddra_name = _col(meddra, "meddra_name", "name", "term", "concept_name")

        required = [
            pae_label,
            pae_meddra,
            label_id,
            p2rx_label,
            p2rx_prod,
            i2p_prod,
            i2p_ing,
            ing_id,
            ing_name,
            meddra_id,
            meddra_name,
        ]
        if any(c is None for c in required):
            console.print("  [red][!][/] could not resolve required columns; skipping")
            return {}

        # Cast all join keys to string so i64/str mismatches across tables don't fail.
        pae = pae.with_columns([pl.col(pae_label).cast(pl.Utf8), pl.col(pae_meddra).cast(pl.Utf8)])
        label = label.with_columns(pl.col(label_id).cast(pl.Utf8))
        p2rx = p2rx.with_columns([pl.col(p2rx_label).cast(pl.Utf8), pl.col(p2rx_prod).cast(pl.Utf8)])
        ing2prod = ing2prod.with_columns([pl.col(i2p_prod).cast(pl.Utf8), pl.col(i2p_ing).cast(pl.Utf8)])
        ingredient = ingredient.with_columns(pl.col(ing_id).cast(pl.Utf8))
        meddra = meddra.with_columns(pl.col(meddra_id).cast(pl.Utf8))

        # label -> ingredient name
        label_to_ing = (
            p2rx.join(ing2prod, left_on=p2rx_prod, right_on=i2p_prod)
            .join(ingredient, left_on=i2p_ing, right_on=ing_id)
            .select([pl.col(p2rx_label).alias("label_id"), pl.col(ing_name).alias("drug_name")])
            .unique()
        )

        # label -> source
        label_src_df = label.select(
            [pl.col(label_id).alias("label_id"), (pl.col(label_src) if label_src else pl.lit(None)).alias("source")]
        )

        # adverse effect rows -> drug + AE label + source + confidence
        pairs = (
            pae.select(
                [
                    pl.col(pae_label).alias("label_id"),
                    pl.col(pae_meddra).alias("meddra_id"),
                    (pl.col(pae_conf) if pae_conf else pl.lit(None)).alias("confidence"),
                ]
            )
            .join(label_to_ing, on="label_id")
            .join(label_src_df, on="label_id", how="left")
            .join(
                meddra.select([pl.col(meddra_id).alias("meddra_id"), pl.col(meddra_name).alias("ae_label")]),
                on="meddra_id",
                how="left",
            )
            .filter(pl.col("drug_name").is_not_null() & pl.col("ae_label").is_not_null())
        )

        # Collapse to unique drug-AE pairs, keeping max confidence and a source set.
        pairs = (
            pairs.group_by(["drug_name", "ae_label", "meddra_id"])
            .agg(
                [
                    pl.col("confidence").max().alias("confidence"),
                    pl.col("source").drop_nulls().unique().str.join(",").alias("sources"),
                ]
            )
            .sort("drug_name")
        )

        pairs_path = self.silver_dir / "drug_ae_pairs.parquet"
        pairs.write_parquet(pairs_path)

        ae = pairs.select(["meddra_id", "ae_label"]).unique().sort("ae_label")
        ae_path = self.silver_dir / "adverse_events.parquet"
        ae.write_parquet(ae_path)

        console.print(f"  [green][ok][/] drug_ae_pairs: {pairs.height:,}  adverse_events: {ae.height:,}")
        with contextlib.suppress(Exception):
            console.print(f"  [dim]sources present: {pairs['sources'].unique().to_list()[:6]}[/]")

        return {"drug_ae_pairs": pairs_path, "adverse_events": ae_path}
