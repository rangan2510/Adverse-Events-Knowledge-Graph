"""
openFDA dataset downloader.

Downloads FDA drug labeling and NDC data from openFDA bulk downloads.
FAERS bulk is too large (~100GB) so we use the API for queries instead.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from kg_ae.datasets.base import BaseDownloader, DatasetMetadata

console = Console()


class OpenFDADownloader(BaseDownloader):
    """Download openFDA drug labeling and NDC data."""

    source_key = "openfda"
    base_url = "https://api.fda.gov"
    license_name = "Public Domain (CC0)"

    def download(self, force: bool = False) -> list[DatasetMetadata]:
        """
        Download openFDA bulk data files.

        Downloads:
        - Drug labels (13 partitions, ~1.7 GB total)
        - NDC (1 partition, ~26 MB)

        FAERS is not downloaded (104 GB) - use API queries instead.

        Args:
            force: Re-download even if files exist

        Returns:
            List of metadata for downloaded files
        """
        console.print("[bold cyan]openFDA Downloader[/]")
        results = []

        # Load manifest
        manifest_path = self.raw_dir / "download.json"
        if not manifest_path.exists():
            console.print("  [yellow]Fetching manifest...[/]")
            self._fetch_url(f"{self.base_url}/download.json", manifest_path)

        with open(manifest_path) as f:
            manifest = json.load(f)

        drug = manifest["results"]["drug"]

        # Download labels
        label_results = self._download_partitions(
            drug["label"]["partitions"],
            "label",
            force=force,
        )
        results.extend(label_results)

        # Download NDC
        ndc_results = self._download_partitions(
            drug["ndc"]["partitions"],
            "ndc",
            force=force,
        )
        results.extend(ndc_results)

        # Summary table
        table = Table(title="openFDA Download Summary", show_header=True)
        table.add_column("Type", style="cyan")
        table.add_column("Files", justify="right")
        table.add_row("Labels", f"{len(label_results):,}")
        table.add_row("NDC", f"{len(ndc_results):,}")
        console.print(table)

        return results

    def _download_partitions(
        self,
        partitions: list[dict],
        subdir: str,
        force: bool = False,
    ) -> list[DatasetMetadata]:
        """Download partition files with progress tracking."""
        results = []
        dest_dir = self.raw_dir / subdir
        dest_dir.mkdir(parents=True, exist_ok=True)

        total_parts = len(partitions)
        total_size_mb = sum(float(p.get("size_mb", 0) or 0) for p in partitions)

        console.print(f"  [dim]{subdir}[/]: {total_parts} partitions, {total_size_mb:.0f} MB total")

        with Progress() as progress:
            task = progress.add_task(f"[cyan]{subdir}", total=total_parts)

            for i, part in enumerate(partitions):
                url = part["file"]
                filename = url.split("/")[-1]
                dest = dest_dir / filename

                if dest.exists() and not force:
                    progress.update(task, advance=1, description=f"[dim]{subdir} (skip)")
                    sha256 = self._compute_sha256(dest)
                else:
                    progress.update(task, description=f"[cyan]{subdir} ({i+1}/{total_parts})")
                    try:
                        self._fetch_url(url, dest, timeout=600.0)  # 10 min timeout for large files
                        sha256 = self._compute_sha256(dest)
                    except Exception as e:
                        console.print(f"\n  [red][error][/] Failed to download {filename}: {e}")
                        continue

                    progress.update(task, advance=1)

                results.append(
                    DatasetMetadata(
                        source_key=self.source_key,
                        version=datetime.now(UTC).strftime("%Y-%m-%d"),
                        download_url=url,
                        local_path=dest,
                        sha256=sha256,
                        downloaded_at=datetime.now(UTC),
                        license_name=self.license_name,
                    )
                )

        console.print(f"    [green]✓[/] {subdir}: {len(results)} files")
        return results


def download_faers_sample(drug_name: str, output_dir: Path, limit: int = 100) -> Path:
    """
    Download a sample of FAERS reports for a specific drug via API.

    This is for targeted queries, not bulk download.

    Args:
        drug_name: Drug name to search for
        output_dir: Directory to save results
        limit: Max number of results

    Returns:
        Path to saved JSON file
    """
    import httpx

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"faers_sample_{drug_name.lower().replace(' ', '_')}.json"

    # Search for reports mentioning this drug
    url = "https://api.fda.gov/drug/event.json"
    params = {
        "search": f'patient.drug.medicinalproduct:"{drug_name}"',
        "limit": limit,
    }

    response = httpx.get(url, params=params, timeout=30.0)
    response.raise_for_status()

    with open(output_file, "w") as f:
        json.dump(response.json(), f, indent=2)

    return output_file
