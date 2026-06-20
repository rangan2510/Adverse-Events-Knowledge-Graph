"""
OnSIDES dataset parser (raw -> bronze).

Reads the OnSIDES CSV flat files and writes the tables needed to build
drug -> adverse-event edges as source-shaped Parquet. The five relevant tables:

    product_adverse_effect          product_label_id, effect_meddra_id, pred1
    product_label                   label_id, source (US/EU/UK/JP)
    product_to_rxnorm               label_id, rxnorm_product_id
    vocab_rxnorm_ingredient_to_product  ingredient_id, product_id
    vocab_rxnorm_ingredient         rxnorm_id, name
    vocab_meddra_adverse_effect     meddra_id, name
"""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseParser

console = Console()

# Logical name -> CSV filename stem (OnSIDES ships one CSV per table)
_TABLES = {
    "product_adverse_effect": "product_adverse_effect",
    "product_label": "product_label",
    "product_to_rxnorm": "product_to_rxnorm",
    "ingredient_to_product": "vocab_rxnorm_ingredient_to_product",
    "ingredient": "vocab_rxnorm_ingredient",
    "meddra": "vocab_meddra_adverse_effect",
}


class OnsidesParser(BaseParser):
    """Parse OnSIDES CSV tables to bronze Parquet."""

    source_key = "onsides"

    def _find_csv(self, stem: str) -> Path | None:
        """Locate a CSV by filename stem anywhere under the raw dir."""
        for candidate in self.raw_dir.rglob(f"{stem}.csv"):
            return candidate
        return None

    def parse(self) -> dict[str, Path]:
        console.print("[bold cyan]OnSIDES Parser[/]")
        results: dict[str, Path] = {}

        for logical, stem in _TABLES.items():
            csv_path = self._find_csv(stem)
            if csv_path is None:
                console.print(f"  [yellow][!][/] {stem}.csv not found, skipping")
                continue
            df = pl.read_csv(csv_path, infer_schema_length=10000, ignore_errors=True)
            out = self.bronze_dir / f"{logical}.parquet"
            df.write_parquet(out)
            results[logical] = out
            console.print(f"  [green][ok][/] {logical}: {df.height:,} rows")

        return results
