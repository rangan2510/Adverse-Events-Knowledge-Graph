"""
ChEMBL downloader.

Downloads ChEMBL bioactivity data via the ChEMBL web services API.
We fetch drug-target activities with quantitative binding data.
"""

import json
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from kg_ae.config import settings
from kg_ae.datasets.base import BaseDownloader

console = Console()

# ChEMBL API base URL
BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"

# We'll fetch activities for approved drugs with binding data
# Using the activities endpoint with filters


class ChEMBLDownloader(BaseDownloader):
    """Download ChEMBL bioactivity data."""

    source_key = "chembl"

    def __init__(self):
        super().__init__()
        self.raw_dir = settings.raw_dir / self.source_key
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(self, max_records: int = 500000) -> dict[str, Path]:
        """
        Download ChEMBL activities via API.

        Args:
            max_records: Maximum number of activity records to fetch

        Returns:
            Dict mapping file types to paths
        """
        console.print("[bold cyan]ChEMBL Downloader[/]")

        downloaded = {}

        # Download drug-target activities with binding data
        activities_path = self._download_activities(max_records)
        if activities_path:
            downloaded["activities"] = activities_path

        # Download approved drugs list for cross-reference
        drugs_path = self._download_approved_drugs()
        if drugs_path:
            downloaded["approved_drugs"] = drugs_path

        return downloaded

    def _download_activities(self, max_records: int) -> Path | None:
        """Download bioactivity data for drug-like compounds."""
        console.print("\n  Downloading bioactivities (this may take a while)...")

        output_path = self.raw_dir / "activities.jsonl"

        # API parameters for binding activities
        # Filter: standard_type in [IC50, Ki, Kd, EC50] and pchembl_value exists
        params = {
            "format": "json",
            "limit": 1000,  # Records per page
            "offset": 0,
            "standard_type__in": "IC50,Ki,Kd,EC50",
            "pchembl_value__isnull": "false",
            "target_type": "SINGLE PROTEIN",
        }

        total_fetched = 0

        with (
            open(output_path, "w", encoding="utf-8") as f,
            Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed:,} records"),
            ) as progress,
        ):
            task = progress.add_task("    Fetching activities", total=max_records)

            with httpx.Client(timeout=60.0) as client:
                while total_fetched < max_records:
                    params["offset"] = total_fetched

                    try:
                        resp = client.get(f"{BASE_URL}/activity.json", params=params)
                        resp.raise_for_status()
                        data = resp.json()
                    except Exception as e:
                        console.print(f"    [warn] API error at offset {total_fetched}: {e}")
                        break

                    activities = data.get("activities", [])
                    if not activities:
                        break

                    for activity in activities:
                        f.write(json.dumps(activity) + "\n")

                    total_fetched += len(activities)
                    progress.update(task, completed=total_fetched)

                    # Check if we've reached the end
                    if len(activities) < params["limit"]:
                        break

        console.print(f"    Downloaded {total_fetched:,} activities → activities.jsonl")
        return output_path

    def _download_approved_drugs(self) -> Path | None:
        """Download list of approved drugs with ChEMBL IDs."""
        console.print("\n  Downloading approved drugs list...")

        output_path = self.raw_dir / "approved_drugs.json"

        # Fetch molecules with max_phase = 4 (approved)
        params = {
            "format": "json",
            "limit": 1000,
            "max_phase": 4,
        }

        all_drugs = []
        offset = 0

        with httpx.Client(timeout=60.0) as client:
            while True:
                params["offset"] = offset

                try:
                    resp = client.get(f"{BASE_URL}/molecule.json", params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    console.print(f"    [warn] API error: {e}")
                    break

                molecules = data.get("molecules", [])
                if not molecules:
                    break

                all_drugs.extend(molecules)
                offset += len(molecules)

                if len(molecules) < params["limit"]:
                    break

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(all_drugs, f)

        console.print(f"    Downloaded {len(all_drugs):,} approved drugs → approved_drugs.json")
        return output_path
