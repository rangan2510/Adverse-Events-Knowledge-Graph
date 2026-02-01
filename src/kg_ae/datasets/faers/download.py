"""
FAERS downloader.

Downloads FDA Adverse Event Reporting System data from openFDA bulk downloads.
"""

import zipfile
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import Progress, DownloadColumn, TransferSpeedColumn, BarColumn

from kg_ae.config import settings
from kg_ae.datasets.base import BaseDownloader

console = Console()

# openFDA bulk download endpoint
# Files are partitioned by quarter
DOWNLOAD_INDEX_URL = "https://api.fda.gov/download.json"


class FAERSDownloader(BaseDownloader):
    """Download FAERS data from openFDA bulk downloads."""

    source_key = "faers"

    def __init__(self):
        super().__init__()
        self.raw_dir = settings.raw_dir / self.source_key
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(self, max_partitions: int = 10) -> dict[str, Path]:
        """
        Download FAERS quarterly data files.
        
        Args:
            max_partitions: Maximum number of quarterly files to download
            
        Returns:
            Dict mapping partition names to paths
        """
        console.print("[bold cyan]FAERS Downloader[/]")
        
        # Get download index
        console.print("  Fetching download index...")
        
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(DOWNLOAD_INDEX_URL)
                resp.raise_for_status()
                index = resp.json()
        except Exception as e:
            console.print(f"  [error] Failed to fetch index: {e}")
            return {}
        
        # Get drug event partitions
        partitions = index.get("results", {}).get("drug", {}).get("event", {}).get("partitions", [])
        
        if not partitions:
            console.print("  [warn] No FAERS partitions found in index")
            return {}
        
        console.print(f"  Found {len(partitions)} total partitions")
        
        # Sort by date (newest first) and take max_partitions
        # Partition format: drug-event-0001-of-0012.json.zip
        partitions = sorted(partitions, key=lambda p: p.get("file", ""), reverse=True)[:max_partitions]
        
        downloaded = {}
        
        for i, partition in enumerate(partitions):
            file_url = partition.get("file")
            if not file_url:
                continue
            
            file_name = Path(file_url).name
            output_path = self.raw_dir / file_name
            
            # Skip if already downloaded
            if output_path.exists():
                console.print(f"  [{i+1}/{len(partitions)}] {file_name} (cached)")
                downloaded[file_name] = output_path
                continue
            
            console.print(f"  [{i+1}/{len(partitions)}] Downloading {file_name}...")
            
            try:
                self._download_file(file_url, output_path)
                downloaded[file_name] = output_path
            except Exception as e:
                console.print(f"    [error] Failed: {e}")
        
        return downloaded

    def _download_file(self, url: str, output_path: Path) -> None:
        """Download a file with progress."""
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                
                with Progress(
                    BarColumn(),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                ) as progress:
                    task = progress.add_task("    ", total=total)
                    
                    with open(output_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))
