"""
FAERS parser.

Parses openFDA FAERS bulk data and computes disproportionality signals
(PRR - Proportional Reporting Ratio, ROR - Reporting Odds Ratio).
"""

import json
import zipfile
from collections import defaultdict
from pathlib import Path

import polars as pl
from rich.console import Console
from rich.progress import track

from kg_ae.config import settings
from kg_ae.datasets.base import BaseParser

console = Console()


class FAERSParser(BaseParser):
    """Parse FAERS data and compute disproportionality signals."""

    source_key = "faers"

    def __init__(self):
        super().__init__()
        self.raw_dir = settings.raw_dir / self.source_key
        self.bronze_dir = settings.bronze_dir / self.source_key
        self.bronze_dir.mkdir(parents=True, exist_ok=True)

    def parse(self) -> dict[str, Path]:
        """
        Parse FAERS data and compute drug-AE signals.

        Returns:
            Dict mapping data types to output paths
        """
        console.print("[bold cyan]FAERS Parser[/]")

        # Step 1: Extract drug-AE pairs from all partitions
        pairs_path = self._extract_drug_ae_pairs()
        if not pairs_path:
            return {}

        # Step 2: Compute disproportionality signals
        signals_path = self._compute_signals(pairs_path)
        if not signals_path:
            return {}

        return {"signals": signals_path}

    def _extract_drug_ae_pairs(self) -> Path | None:
        """Extract drug-adverse event pairs from FAERS JSON files."""
        console.print("\n  Step 1: Extracting drug-AE pairs from reports...")

        # Find all zip files
        zip_files = list(self.raw_dir.glob("*.zip"))
        if not zip_files:
            console.print("    [warn] No FAERS zip files found")
            return None

        console.print(f"    Processing {len(zip_files)} partition files...")

        # Count drug-AE co-occurrences
        drug_ae_counts = defaultdict(int)  # (drug, ae) -> count
        drug_counts = defaultdict(int)  # drug -> total reports
        ae_counts = defaultdict(int)  # ae -> total reports
        total_reports = 0

        for zip_path in track(zip_files, description="    Parsing"):
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    for name in zf.namelist():
                        if not name.endswith(".json"):
                            continue

                        with zf.open(name) as f:
                            data = json.load(f)

                        results = data.get("results", [])

                        for report in results:
                            total_reports += 1

                            # Get drugs from this report
                            drugs = set()
                            for drug_info in report.get("patient", {}).get("drug", []):
                                drug_name = drug_info.get("medicinalproduct", "").upper().strip()
                                if drug_name and len(drug_name) > 1:
                                    drugs.add(drug_name)

                            # Get reactions (AEs) from this report
                            aes = set()
                            for reaction in report.get("patient", {}).get("reaction", []):
                                ae_term = reaction.get("reactionmeddrapt", "").lower().strip()
                                if ae_term and len(ae_term) > 1:
                                    aes.add(ae_term)

                            # Count co-occurrences
                            for drug in drugs:
                                drug_counts[drug] += 1
                                for ae in aes:
                                    drug_ae_counts[(drug, ae)] += 1

                            for ae in aes:
                                ae_counts[ae] += 1

            except Exception as e:
                console.print(f"    [warn] Error parsing {zip_path.name}: {e}")
                continue

        console.print(f"    Total reports processed: {total_reports:,}")
        console.print(f"    Unique drugs: {len(drug_counts):,}")
        console.print(f"    Unique AEs: {len(ae_counts):,}")
        console.print(f"    Drug-AE pairs: {len(drug_ae_counts):,}")

        # Save intermediate counts
        counts_data = {
            "drug_ae_counts": {f"{d}|||{a}": c for (d, a), c in drug_ae_counts.items()},
            "drug_counts": dict(drug_counts),
            "ae_counts": dict(ae_counts),
            "total_reports": total_reports,
        }

        counts_path = self.bronze_dir / "raw_counts.json"
        with open(counts_path, "w", encoding="utf-8") as f:
            json.dump(counts_data, f)

        return counts_path

    def _compute_signals(self, counts_path: Path) -> Path | None:
        """Compute PRR and ROR from drug-AE counts."""
        console.print("\n  Step 2: Computing disproportionality signals...")

        with open(counts_path, encoding="utf-8") as f:
            counts_data = json.load(f)

        drug_ae_counts = {tuple(k.split("|||")): v for k, v in counts_data["drug_ae_counts"].items()}
        drug_counts = counts_data["drug_counts"]
        ae_counts = counts_data["ae_counts"]
        N = counts_data["total_reports"]

        if N == 0:
            console.print("    [warn] No reports to analyze")
            return None

        # Compute signals for each drug-AE pair
        signals = []

        for (drug, ae), a in track(drug_ae_counts.items(), description="    Computing"):
            # a = reports with drug AND ae
            # b = reports with drug but NOT ae
            # c = reports with ae but NOT drug
            # d = reports without drug and without ae

            b = drug_counts[drug] - a  # drug without this AE
            c = ae_counts[ae] - a  # AE without this drug
            d = N - a - b - c  # neither

            # Avoid division by zero
            if b <= 0 or c <= 0 or d <= 0:
                continue

            # Minimum count threshold (at least 3 co-occurrences)
            if a < 3:
                continue

            # PRR = (a/(a+b)) / (c/(c+d))
            prr = (a / (a + b)) / (c / (c + d))

            # ROR = (a/c) / (b/d) = (a*d) / (b*c)
            ror = (a * d) / (b * c)

            # Chi-square for significance
            expected = (a + b) * (a + c) / N
            chi2 = (a - expected) ** 2 / expected if expected > 0 else 0

            # Only keep signals where PRR > 1 and chi2 significant
            if prr > 1.0 and chi2 > 3.84:  # p < 0.05
                signals.append(
                    {
                        "drug_name": drug,
                        "ae_term": ae,
                        "count": a,
                        "prr": round(prr, 3),
                        "ror": round(ror, 3),
                        "chi2": round(chi2, 2),
                        "drug_total": drug_counts[drug],
                        "ae_total": ae_counts[ae],
                    }
                )

        console.print(f"    Significant signals (PRR>1, p<0.05): {len(signals):,}")

        if not signals:
            console.print("    [warn] No significant signals found")
            return None

        # Convert to DataFrame and sort by chi2
        df = pl.DataFrame(signals)
        df = df.sort("chi2", descending=True)

        # Filter to top signals per drug (limit noise)
        # Keep top 100 AEs per drug by chi2
        df = df.group_by("drug_name").head(100)

        console.print(f"    After top-100-per-drug filter: {len(df):,}")

        output_path = self.bronze_dir / "signals.parquet"
        df.write_parquet(output_path)
        console.print(f"    signals: {len(df):,} rows → signals.parquet")

        return output_path
