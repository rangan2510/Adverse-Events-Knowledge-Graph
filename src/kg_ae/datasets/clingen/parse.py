"""
ClinGen gene-disease validity curation parser.

Parses ClinGen gene-disease validity TSV/CSV to parquet.
"""

import gzip
import json
from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.config import settings
from kg_ae.datasets.base import BaseParser

console = Console()


class ClinGenParser(BaseParser):
    """Parse ClinGen gene-disease validity curations."""

    source_key = "clingen"

    def __init__(self):
        super().__init__()
        self.raw_dir = settings.raw_dir / self.source_key
        self.bronze_dir = settings.bronze_dir / self.source_key
        self.bronze_dir.mkdir(parents=True, exist_ok=True)

    def parse(self) -> dict[str, Path]:
        """
        Parse ClinGen gene-disease validity data.
        
        Returns:
            Dict mapping file types to output paths
        """
        console.print("[bold cyan]ClinGen Parser[/]")
        
        parsed = {}
        
        # Try different input formats
        tsv_path = self.raw_dir / "gene_validity.tsv"
        csv_path = self.raw_dir / "gene_validity.csv"
        json_path = self.raw_dir / "gene_validity.json.gz"
        
        if tsv_path.exists():
            result = self._parse_tsv(tsv_path)
            if result:
                parsed["validity"] = result
        elif csv_path.exists():
            result = self._parse_csv(csv_path)
            if result:
                parsed["validity"] = result
        elif json_path.exists():
            result = self._parse_json(json_path)
            if result:
                parsed["validity"] = result
        else:
            console.print("  [skip] No ClinGen data found in raw/")
        
        return parsed

    def _parse_tsv(self, path: Path) -> Path | None:
        """Parse TSV format from ClinGen (actually CSV with header comment lines)."""
        console.print(f"  Parsing {path.name}...")
        
        try:
            # ClinGen format has header rows we need to skip
            # Find the actual data start (after the ++++ separator lines)
            lines = path.read_text(encoding="utf-8").splitlines()
            data_start = 0
            for i, line in enumerate(lines):
                if line.startswith('"GENE SYMBOL"'):
                    data_start = i
                    break
            
            # Read CSV starting from header row
            df = pl.read_csv(
                path,
                skip_rows=data_start,
                infer_schema_length=10000,
                ignore_errors=True,
            )
            
            # Skip the separator row (+++++)
            df = df.filter(~pl.col("GENE SYMBOL").str.starts_with("+"))
            
            # Rename columns to standard names
            rename_map = {
                "GENE SYMBOL": "gene_symbol",
                "GENE ID (HGNC)": "hgnc_id",
                "DISEASE LABEL": "disease_label",
                "DISEASE ID (MONDO)": "mondo_id",
                "MOI": "inheritance",
                "SOP": "sop",
                "CLASSIFICATION": "classification",
                "ONLINE REPORT": "report_url",
                "CLASSIFICATION DATE": "classification_date",
                "GCEP": "expert_panel",
            }
            df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
            
            return self._process_dataframe(df, "tsv")
        except Exception as e:
            console.print(f"    [warn] TSV parse error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _parse_csv(self, path: Path) -> Path | None:
        """Parse CSV format from ClinGen."""
        console.print(f"  Parsing {path.name}...")
        
        try:
            df = pl.read_csv(
                path,
                infer_schema_length=10000,
                ignore_errors=True,
            )
            return self._process_dataframe(df, "csv")
        except Exception as e:
            console.print(f"    [warn] CSV parse error: {e}")
            return None

    def _parse_json(self, path: Path) -> Path | None:
        """Parse JSON format from ClinGen API."""
        console.print(f"  Parsing {path.name}...")
        
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                data = json.load(f)
            
            if not data:
                console.print("    [warn] Empty JSON data")
                return None
            
            df = pl.DataFrame(data)
            return self._process_dataframe(df, "json")
        except Exception as e:
            console.print(f"    [warn] JSON parse error: {e}")
            return None

    def _process_dataframe(self, df: pl.DataFrame, source: str) -> Path | None:
        """Process and normalize ClinGen dataframe."""
        console.print(f"    Columns: {df.columns}")
        console.print(f"    Raw rows: {len(df):,}")
        
        # Filter out rows without gene symbol
        if "gene_symbol" in df.columns:
            df = df.filter(pl.col("gene_symbol").is_not_null())
            df = df.filter(pl.col("gene_symbol") != "")
        
        output_path = self.bronze_dir / "validity.parquet"
        df.write_parquet(output_path)
        
        console.print(f"    validity: {len(df):,} curations → validity.parquet")
        
        # Show classification distribution if available
        if "classification" in df.columns:
            dist = df.group_by("classification").len().sort("len", descending=True)
            console.print("    Classification distribution:")
            for row in dist.iter_rows(named=True):
                console.print(f"      {row['classification']}: {row['len']:,}")
        
        return output_path
