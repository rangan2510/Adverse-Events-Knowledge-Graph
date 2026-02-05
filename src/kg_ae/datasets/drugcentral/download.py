"""
DrugCentral dataset downloader.

Downloads drug identity and target data from DrugCentral.
"""

from datetime import UTC, datetime

from rich.console import Console

from kg_ae.datasets.base import BaseDownloader, DatasetMetadata

console = Console()


class DrugCentralDownloader(BaseDownloader):
    """Download DrugCentral drug and target data."""

    source_key = "drugcentral"
    base_url = "https://unmtid-dbs.net/download/DrugCentral"
    license_name = "CC BY-SA 4.0"

    # Files to download with their URLs
    FILES = {
        "drug.target.interaction.tsv.gz": {
            "url": "2021_09_01/drug.target.interaction.tsv.gz",
            "description": "Drug-target interactions",
        },
        "structures.smiles.tsv": {
            "url": "2021_09_01/structures.smiles.tsv",
            "description": "Drug structures with IDs",
        },
    }

    # Additional file from different base URL
    STATIC_FILES = {
        "FDA+EMA+PMDA_Approved.csv": {
            "url": "https://drugcentral.org/static/FDA+EMA+PMDA_Approved.csv",
            "description": "Approved drugs with cross-references",
        },
    }

    def download(self, force: bool = False) -> list[DatasetMetadata]:
        """
        Download DrugCentral data files.

        Args:
            force: Re-download even if files exist

        Returns:
            List of metadata for downloaded files
        """
        console.print("[bold cyan]DrugCentral Downloader[/]")
        results = []

        # Download main files
        for filename, info in self.FILES.items():
            dest = self.raw_dir / filename
            url = f"{self.base_url}/{info['url']}"

            if dest.exists() and not force:
                console.print(f"  [dim][skip] {filename} (cached)[/]")
                sha256 = self._compute_sha256(dest)
            else:
                console.print(f"  Downloading {filename}...")
                self._fetch_url(url, dest)
                sha256 = self._compute_sha256(dest)
                size_kb = dest.stat().st_size / 1024
                console.print(f"    [green]✓[/] {filename} ({size_kb:.1f} KB)")

            results.append(
                DatasetMetadata(
                    source_key=self.source_key,
                    version="2021_09_01",
                    download_url=url,
                    local_path=dest,
                    sha256=sha256,
                    downloaded_at=datetime.now(UTC),
                    license_name=self.license_name,
                )
            )

        # Download static files (different base URL)
        for filename, info in self.STATIC_FILES.items():
            dest = self.raw_dir / filename
            url = info["url"]

            if dest.exists() and not force:
                console.print(f"  [dim][skip] {filename} (cached)[/]")
                sha256 = self._compute_sha256(dest)
            else:
                console.print(f"  Downloading {filename}...")
                self._fetch_url(url, dest)
                sha256 = self._compute_sha256(dest)
                size_kb = dest.stat().st_size / 1024
                console.print(f"    [green]✓[/] {filename} ({size_kb:.1f} KB)")

            results.append(
                DatasetMetadata(
                    source_key=self.source_key,
                    version="2023",
                    download_url=url,
                    local_path=dest,
                    sha256=sha256,
                    downloaded_at=datetime.now(UTC),
                    license_name=self.license_name,
                )
            )

        return results
