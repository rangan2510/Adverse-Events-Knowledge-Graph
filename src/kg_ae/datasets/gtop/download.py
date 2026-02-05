"""
Guide to PHARMACOLOGY (GtoPdb) dataset downloader.

Downloads curated ligand-target interaction data with quantitative pharmacology.
"""

from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseDownloader, DatasetMetadata

console = Console()


class GtoPdbDownloader(BaseDownloader):
    """Download GtoPdb pharmacology data."""

    source_key = "gtop"
    base_url = "https://www.guidetopharmacology.org/DATA"
    license_name = "CC BY-SA 4.0"

    FILES = {
        "interactions.tsv": {
            "url": "interactions.tsv",
            "description": "Ligand-target interactions with affinity data",
        },
        "ligands.tsv": {
            "url": "ligands.tsv",
            "description": "Ligand/drug information with cross-references",
        },
        "targets_and_families.tsv": {
            "url": "targets_and_families.tsv",
            "description": "Target information and classifications",
        },
        "GtP_to_HGNC_mapping.csv": {
            "url": "GtP_to_HGNC_mapping.csv",
            "description": "Mapping from GtoPdb target IDs to HGNC symbols",
        },
    }

    def download(self, force: bool = False) -> list[DatasetMetadata]:
        """
        Download GtoPdb data files.

        Args:
            force: Re-download even if files exist

        Returns:
            List of metadata for downloaded files
        """
        console.print("[bold cyan]GtoPdb Downloader[/]")
        results = []
        version = None

        for filename, info in self.FILES.items():
            dest = self.raw_dir / filename
            url = f"{self.base_url}/{info['url']}"

            if dest.exists() and not force:
                console.print(f"  [dim][skip] {filename} (cached)[/]")
                sha256 = self._compute_sha256(dest)
            else:
                console.print(f"  [yellow]Downloading[/] {filename}...")
                self._fetch_url(url, dest, timeout=120.0)
                sha256 = self._compute_sha256(dest)
                size_kb = dest.stat().st_size / 1024
                console.print(f"    [green]✓[/] {filename} ({size_kb:.0f} KB)")

            # Extract version from first line (comment)
            if version is None and filename == "interactions.tsv":
                with open(dest, encoding="utf-8") as f:
                    first_line = f.readline()
                    # Parse: "# GtoPdb Version: 2025.4 - published: 2025-12-10"
                    if "Version:" in first_line:
                        version = first_line.split("Version:")[1].split("-")[0].strip()

            results.append(
                DatasetMetadata(
                    source_key=self.source_key,
                    version=version or datetime.now(UTC).strftime("%Y-%m-%d"),
                    download_url=url,
                    local_path=dest,
                    sha256=sha256,
                    downloaded_at=datetime.now(UTC),
                    license_name=self.license_name,
                )
            )

        # Summary table
        table = Table(title="GtoPdb Download Summary", show_header=True)
        table.add_column("File", style="cyan")
        table.add_column("Status", justify="center")
        for r in results:
            table.add_row(r.local_path.name, "[green]✓[/]")
        console.print(table)

        return results
