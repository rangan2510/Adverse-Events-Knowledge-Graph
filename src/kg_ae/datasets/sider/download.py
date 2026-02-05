"""
SIDER dataset downloader.

Downloads drug-side effect data from SIDER 4.1.
"""

from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseDownloader, DatasetMetadata

console = Console()


class SiderDownloader(BaseDownloader):
    """Download SIDER drug-ADR data."""

    source_key = "sider"
    base_url = "http://sideeffects.embl.de/media/download"
    license_name = "CC BY-NC-SA 4.0"

    # Files to download
    FILES = {
        "meddra_all_se.tsv.gz": "All side effects with MedDRA terms",
        "drug_names.tsv": "STITCH ID to drug name mapping",
        "meddra_freq.tsv.gz": "Side effect frequencies",
    }

    def download(self, force: bool = False) -> list[DatasetMetadata]:
        """
        Download SIDER data files.

        Args:
            force: Re-download even if files exist

        Returns:
            List of metadata for downloaded files
        """
        console.print("[bold cyan]SIDER Downloader[/]")
        results = []

        for filename, _description in self.FILES.items():
            dest = self.raw_dir / filename
            url = f"{self.base_url}/{filename}"

            if dest.exists() and not force:
                console.print(f"  [dim][skip] {filename} (cached)[/]")
                sha256 = self._compute_sha256(dest)
            else:
                console.print(f"  [yellow]Downloading[/] {filename}...")
                self._fetch_url(url, dest)
                sha256 = self._compute_sha256(dest)
                console.print(f"    [green]✓[/] {filename} ({dest.stat().st_size:,} bytes)")

            results.append(
                DatasetMetadata(
                    source_key=self.source_key,
                    version="4.1",
                    download_url=url,
                    local_path=dest,
                    sha256=sha256,
                    downloaded_at=datetime.now(UTC),
                    license_name=self.license_name,
                )
            )

        # Summary table
        table = Table(title="SIDER Download Summary", show_header=True)
        table.add_column("File", style="cyan")
        table.add_column("Status", justify="center")
        for r in results:
            table.add_row(r.local_path.name, "[green]✓[/]")
        console.print(table)

        return results
