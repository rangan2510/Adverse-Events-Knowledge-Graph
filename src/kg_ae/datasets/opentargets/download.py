"""
Open Targets dataset downloader.

Downloads gene-disease association data from Open Targets Platform.
https://platform.opentargets.org/downloads/data
"""

from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseDownloader, DatasetMetadata

console = Console()


class OpenTargetsDownloader(BaseDownloader):
    """Download Open Targets Platform data files."""

    source_key = "opentargets"
    base_url = "https://ftp.ebi.ac.uk/pub/databases/opentargets/platform"
    license_name = "CC0"
    version = "25.03"  # Pin to specific release

    # Datasets to download (Parquet directories)
    DATASETS = {
        "association_overall_direct": {
            "description": "Gene-disease overall association scores (direct)",
        },
        "disease": {
            "description": "Disease/phenotype entities with EFO/MONDO mappings",
        },
        "target": {
            "description": "Target/gene annotations with Ensembl/UniProt IDs",
        },
    }

    def download(self, force: bool = False) -> list[DatasetMetadata]:
        """
        Download Open Targets data files.

        Uses wget to download Parquet directories recursively.
        
        Args:
            force: Re-download even if files exist

        Returns:
            List of metadata for downloaded files
        """
        console.print("[bold cyan]Open Targets Downloader[/]")
        results = []

        for dataset_name, _info in self.DATASETS.items():
            dataset_dir = self.raw_dir / dataset_name

            if dataset_dir.exists() and not force:
                # Check if parquet files exist
                parquet_files = list(dataset_dir.glob("*.parquet"))
                if parquet_files:
                    console.print(f"  [dim][skip] {dataset_name} (cached, {len(parquet_files)} files)[/]")
                    results.append(
                        DatasetMetadata(
                            source_key=self.source_key,
                            version=self.version,
                            download_url=self._get_url(dataset_name),
                            local_path=dataset_dir,
                            sha256=None,
                            downloaded_at=datetime.now(),
                            license_name=self.license_name,
                        )
                    )
                    continue

            console.print(f"  [yellow]Downloading[/] {dataset_name}...")
            self._download_dataset(dataset_name, dataset_dir)
            
            parquet_files = list(dataset_dir.glob("*.parquet"))
            total_size = sum(f.stat().st_size for f in parquet_files)
            console.print(f"    [green]✓[/] {dataset_name} ({len(parquet_files)} files, {total_size:,} bytes)")

            results.append(
                DatasetMetadata(
                    source_key=self.source_key,
                    version=self.version,
                    download_url=self._get_url(dataset_name),
                    local_path=dataset_dir,
                    sha256=None,
                    downloaded_at=datetime.now(),
                    license_name=self.license_name,
                )
            )

        # Summary table
        table = Table(title="Open Targets Download Summary", show_header=True)
        table.add_column("Dataset", style="cyan")
        table.add_column("Status", justify="center")
        for r in results:
            table.add_row(r.local_path.name, "[green]✓[/]")
        console.print(table)

        return results

    def _get_url(self, dataset_name: str) -> str:
        """Get full URL for a dataset."""
        return f"{self.base_url}/{self.version}/output/{dataset_name}/"

    def _download_dataset(self, dataset_name: str, dest_dir: Path) -> None:
        """
        Download a dataset directory using wget.
        
        Open Targets datasets are partitioned Parquet directories.
        """
        import subprocess

        dest_dir.mkdir(parents=True, exist_ok=True)
        url = self._get_url(dataset_name)

        # Use wget to download recursively
        # --recursive: download recursively
        # --no-parent: don't ascend to parent directory
        # --no-host-directories: don't create host directory
        # --cut-dirs=5: skip the /pub/databases/opentargets/platform/25.03/output/ path
        # -P: set output directory
        cmd = [
            "wget",
            "--recursive",
            "--no-parent",
            "--no-host-directories",
            "--cut-dirs=5",
            "--accept=*.parquet",
            "-P", str(dest_dir.parent),
            url,
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            console.print(f"  [red][error][/] wget failed: {e.stderr}")
            # Fallback: try with httpx for individual files
            self._download_with_httpx(url, dest_dir)
        except FileNotFoundError:
            # wget not available, use httpx
            console.print("  [yellow][info][/] wget not found, using httpx...")
            self._download_with_httpx(url, dest_dir)

    def _download_with_httpx(self, base_url: str, dest_dir: Path) -> None:
        """
        Download parquet files using httpx (fallback when wget unavailable).
        
        Note: This is slower and may not handle all partitions.
        """
        import httpx
        from bs4 import BeautifulSoup

        dest_dir.mkdir(parents=True, exist_ok=True)

        # Get directory listing
        try:
            response = httpx.get(base_url, timeout=60.0, follow_redirects=True)
            response.raise_for_status()
        except Exception as e:
            console.print(f"  [red][error][/] Failed to list directory: {e}")
            return

        # Parse HTML to find parquet files
        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a")

        for link in links:
            href = link.get("href", "")
            if href.endswith(".parquet"):
                file_url = base_url + href
                file_path = dest_dir / href
                
                if not file_path.exists():
                    console.print(f"    [dim]Fetching[/] {href}...")
                    self._fetch_url(file_url, file_path)
