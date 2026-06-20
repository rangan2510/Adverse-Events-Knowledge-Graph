"""
BindingDB dataset parser (raw -> bronze).

The BindingDB_All TSV is large (~hundreds of MB, >1M rows). We scan it lazily
with polars, select only the columns needed for drug -> target edges, restrict
to human targets, and write a compact bronze Parquet. Affinity columns are kept
as raw strings here (they contain values like ">10000"); the normalizer cleans
them to numerics.
"""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseParser

console = Console()

# Source TSV column -> bronze column. BindingDB headers are verbose; we keep a
# tolerant set and rename to short names.
_WANTED = {
    "BindingDB Ligand Name": "ligand_name",
    "Ligand SMILES": "smiles",
    "Ki (nM)": "ki_nm",
    "Kd (nM)": "kd_nm",
    "IC50 (nM)": "ic50_nm",
    "EC50 (nM)": "ec50_nm",
    "UniProt (SwissProt) Primary ID of Target Chain 1": "uniprot_id",
    "Target Source Organism According to Curator or DataSource": "organism",
}


class BindingdbParser(BaseParser):
    """Parse the BindingDB_All TSV to a compact bronze Parquet."""

    source_key = "bindingdb"

    def _find_tsv(self) -> Path | None:
        for candidate in self.raw_dir.rglob("BindingDB_All*.tsv"):
            return candidate
        # fall back to any .tsv under the raw dir
        for candidate in self.raw_dir.rglob("*.tsv"):
            return candidate
        return None

    def parse(self) -> dict[str, Path]:
        console.print("[bold cyan]BindingDB Parser[/]")
        tsv = self._find_tsv()
        if tsv is None:
            console.print("  [yellow][!][/] BindingDB TSV not found, skipping")
            return {}

        # Lazy scan; BindingDB TSV has ragged quoting, so be tolerant.
        lf = pl.scan_csv(
            tsv,
            separator="\t",
            has_header=True,
            infer_schema_length=0,  # read all as str; normalizer casts
            truncate_ragged_lines=True,
            quote_char=None,
            ignore_errors=True,
        )
        available = set(lf.collect_schema().names())
        present = {src: dst for src, dst in _WANTED.items() if src in available}
        if "uniprot_id" not in present.values() or "ligand_name" not in present.values():
            console.print("  [red][!][/] required BindingDB columns missing; skipping")
            return {}

        lf = lf.select([pl.col(src).alias(dst) for src, dst in present.items()])
        # Keep human targets only (where organism is present).
        if "organism" in present.values():
            lf = lf.filter(pl.col("organism").str.contains("(?i)homo sapiens").fill_null(False))
        # Must have a target and a ligand name.
        lf = lf.filter(pl.col("uniprot_id").is_not_null() & pl.col("ligand_name").is_not_null())

        df = lf.collect()
        out = self.bronze_dir / "interactions.parquet"
        df.write_parquet(out)
        console.print(f"  [green][ok][/] interactions: {df.height:,} rows (human targets)")
        return {"interactions": out}
