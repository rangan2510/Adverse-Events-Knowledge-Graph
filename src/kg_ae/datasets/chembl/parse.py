"""
ChEMBL parser.

Parses ChEMBL bioactivity data into normalized format for loading.
"""

import json
from pathlib import Path

import polars as pl
from rich.console import Console
from rich.progress import track

from kg_ae.config import settings
from kg_ae.datasets.base import BaseParser

console = Console()


class ChEMBLParser(BaseParser):
    """Parse ChEMBL activity data."""

    source_key = "chembl"

    def __init__(self):
        super().__init__()
        self.raw_dir = settings.raw_dir / self.source_key
        self.bronze_dir = settings.bronze_dir / self.source_key
        self.bronze_dir.mkdir(parents=True, exist_ok=True)

    def parse(self) -> dict[str, Path]:
        """
        Parse ChEMBL activity data.
        
        Returns:
            Dict mapping data types to output paths
        """
        console.print("[bold cyan]ChEMBL Parser[/]")
        
        parsed = {}
        
        # Parse activities
        activities_path = self.raw_dir / "activities.jsonl"
        if activities_path.exists():
            result = self._parse_activities(activities_path)
            if result:
                parsed["activities"] = result
        else:
            console.print("  [skip] No activities.jsonl found")
        
        # Parse approved drugs for cross-reference
        drugs_path = self.raw_dir / "approved_drugs.json"
        if drugs_path.exists():
            result = self._parse_approved_drugs(drugs_path)
            if result:
                parsed["approved_drugs"] = result
        
        return parsed

    def _parse_activities(self, path: Path) -> Path | None:
        """Parse JSONL activities file."""
        console.print(f"  Parsing {path.name}...")
        
        records = []
        
        with open(path, encoding="utf-8") as f:
            for line in track(f, description="    Reading"):
                try:
                    activity = json.loads(line.strip())
                    
                    # Extract key fields
                    record = {
                        "activity_id": activity.get("activity_id"),
                        "molecule_chembl_id": activity.get("molecule_chembl_id"),
                        "molecule_pref_name": activity.get("molecule_pref_name"),
                        "target_chembl_id": activity.get("target_chembl_id"),
                        "target_pref_name": activity.get("target_pref_name"),
                        "target_organism": activity.get("target_organism"),
                        "target_type": activity.get("target_type"),
                        "standard_type": activity.get("standard_type"),  # IC50, Ki, etc.
                        "standard_value": activity.get("standard_value"),  # Numeric value
                        "standard_units": activity.get("standard_units"),  # nM, etc.
                        "pchembl_value": activity.get("pchembl_value"),  # -log10 normalized
                        "activity_comment": activity.get("activity_comment"),
                        "assay_chembl_id": activity.get("assay_chembl_id"),
                        "assay_type": activity.get("assay_type"),  # B=Binding, F=Functional
                        "src_id": activity.get("src_id"),
                        "document_chembl_id": activity.get("document_chembl_id"),
                    }
                    
                    # Only keep records with essential fields
                    if record["molecule_chembl_id"] and record["target_chembl_id"] and record["pchembl_value"]:
                        records.append(record)
                        
                except (json.JSONDecodeError, KeyError):
                    continue
        
        if not records:
            console.print("    [warn] No valid activity records found")
            return None
        
        df = pl.DataFrame(records)
        
        # Filter to human targets
        if "target_organism" in df.columns:
            df = df.filter(pl.col("target_organism") == "Homo sapiens")
        
        console.print(f"    Human target activities: {len(df):,}")
        
        # Aggregate by molecule-target pair (take best pchembl_value)
        df_agg = df.group_by(["molecule_chembl_id", "target_chembl_id"]).agg([
            pl.col("molecule_pref_name").first(),
            pl.col("target_pref_name").first(),
            pl.col("standard_type").first(),
            pl.col("pchembl_value").max().alias("best_pchembl"),
            pl.col("pchembl_value").mean().alias("mean_pchembl"),
            pl.len().alias("activity_count"),
        ])
        
        console.print(f"    Unique molecule-target pairs: {len(df_agg):,}")
        
        output_path = self.bronze_dir / "activities.parquet"
        df_agg.write_parquet(output_path)
        console.print(f"    activities: {len(df_agg):,} rows → activities.parquet")
        
        return output_path

    def _parse_approved_drugs(self, path: Path) -> Path | None:
        """Parse approved drugs JSON."""
        console.print(f"  Parsing {path.name}...")
        
        with open(path, encoding="utf-8") as f:
            drugs = json.load(f)
        
        records = []
        for drug in drugs:
            record = {
                "molecule_chembl_id": drug.get("molecule_chembl_id"),
                "pref_name": drug.get("pref_name"),
                "max_phase": drug.get("max_phase"),
                "molecule_type": drug.get("molecule_type"),
                "first_approval": drug.get("first_approval"),
            }
            
            # Extract cross-references
            xrefs = drug.get("cross_references", [])
            for xref in xrefs:
                if xref.get("xref_src") == "DrugCentral":
                    record["drugcentral_id"] = xref.get("xref_id")
                elif xref.get("xref_src") == "PubChem":
                    record["pubchem_cid"] = xref.get("xref_id")
            
            if record["molecule_chembl_id"]:
                records.append(record)
        
        df = pl.DataFrame(records)
        
        output_path = self.bronze_dir / "approved_drugs.parquet"
        df.write_parquet(output_path)
        console.print(f"    approved_drugs: {len(df):,} rows → approved_drugs.parquet")
        
        return output_path
