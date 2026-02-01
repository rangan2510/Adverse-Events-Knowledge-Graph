"""
HGNC (HUGO Gene Nomenclature Committee) dataset downloader.

Downloads the complete set of approved human gene symbols and metadata.
This is the canonical reference for human gene nomenclature.
"""

from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseDownloader, DatasetMetadata

console = Console()


class HGNCDownloader(BaseDownloader):
    """Download HGNC gene nomenclature data."""

    source_key = "hgnc"
    base_url = "https://storage.googleapis.com/public-download-files/hgnc/json/json"
    license_name = "CC0 1.0"

    FILES = {
        "hgnc_complete_set.json": {
            "url": "hgnc_complete_set.json",
            "description": "Complete set of HGNC approved gene symbols",
        },
    }

    def download(self, force: bool = False) -> list[DatasetMetadata]:
        """
        Download HGNC complete gene set.

        Args:
            force: Re-download even if files exist

        Returns:
            List of metadata for downloaded files
        """
        console.print("[bold cyan]HGNC Downloader[/]")
        results = []

        for filename, info in self.FILES.items():
            dest = self.raw_dir / filename
            url = f"{self.base_url}/{info['url']}"

            if dest.exists() and not force:
                console.print(f"  [dim][skip] {filename} (cached)[/]")
                sha256 = self._compute_sha256(dest)
            else:
                console.print(f"  Downloading {filename}...")
                self._fetch_url(url, dest, timeout=120.0)
                sha256 = self._compute_sha256(dest)
                size_mb = dest.stat().st_size / (1024 * 1024)
                console.print(f"    [green]✓[/] {filename} ({size_mb:.1f} MB)")

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

        # Summary table
        if results:
            table = Table(title="Download Summary", show_header=True)
            table.add_column("File", style="cyan")
            table.add_column("Size", justify="right")
            for r in results:
                size = r.local_path.stat().st_size / (1024 * 1024)
                table.add_row(r.local_path.name, f"{size:.1f} MB")
            console.print(table)

        return results
