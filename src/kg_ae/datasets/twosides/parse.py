"""
TWOSIDES dataset parser (raw -> bronze).

Lazily scans the gzipped CSV (large), keeps the columns needed for the
drug-drug -> AE edges, and writes a compact bronze Parquet.
"""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseParser

console = Console()


class TwosidesParser(BaseParser):
    """Parse TWOSIDES.csv.gz to bronze Parquet."""

    source_key = "twosides"

    def parse(self) -> dict[str, Path]:
        console.print("[bold cyan]TWOSIDES Parser[/]")
        src = self.raw_dir / "TWOSIDES.csv.gz"
        if not src.exists():
            console.print("  [yellow][!][/] TWOSIDES.csv.gz not found, skipping")
            return {}

        # polars reads .gz transparently. Read all as str for tolerant parsing.
        lf = pl.scan_csv(
            src,
            infer_schema_length=0,
            truncate_ragged_lines=True,
            ignore_errors=True,
        )
        df = lf.collect()
        out = self.bronze_dir / "interactions.parquet"
        df.write_parquet(out)
        console.print(f"  [green][ok][/] interactions: {df.height:,} rows")
        return {"interactions": out}
