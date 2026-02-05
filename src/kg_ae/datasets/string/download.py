"""
STRING database downloader.

Downloads human protein-protein interaction data from STRING.
Uses the human-only (taxon 9606) files for efficiency.
"""

from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import DownloadColumn, Progress, TransferSpeedColumn

from kg_ae.config import settings

console = Console()

# STRING v12.0 URLs for human (taxon 9606)
STRING_BASE = "https://stringdb-downloads.org/download"
STRING_VERSION = "12.0"

FILES = {
    # Protein-protein interactions with combined scores
    "protein_links": f"protein.links.v{STRING_VERSION}/9606.protein.links.v{STRING_VERSION}.txt.gz",
    # Protein aliases for mapping to gene symbols
    "protein_aliases": f"protein.aliases.v{STRING_VERSION}/9606.protein.aliases.v{STRING_VERSION}.txt.gz",
    # Protein info (preferred names)
    "protein_info": f"protein.info.v{STRING_VERSION}/9606.protein.info.v{STRING_VERSION}.txt.gz",
}


class STRINGDownloader:
    """Download STRING human protein interaction data."""

    def __init__(self):
        self.raw_dir = settings.raw_dir / "string"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(self, force: bool = False) -> dict[str, Path]:
        """
        Download STRING files for human proteins.

        Args:
            force: Re-download even if files exist

        Returns:
            Dict mapping file keys to local paths
        """
        results = {}

        for key, url_path in FILES.items():
            url = f"{STRING_BASE}/{url_path}"
            filename = url_path.split("/")[-1]
            dest = self.raw_dir / filename

            if dest.exists() and not force:
                console.print(f"  [dim]Skipping {filename} (exists)[/]")
                results[key] = dest
                continue

            console.print(f"  Downloading {filename}...")
            self._download_file(url, dest)
            results[key] = dest

        return results

    def _download_file(self, url: str, dest: Path) -> None:
        """Download a file with progress bar."""
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))

            with Progress(
                *Progress.get_default_columns(),
                DownloadColumn(),
                TransferSpeedColumn(),
            ) as progress:
                task = progress.add_task(f"[cyan]{dest.name}", total=total)

                with open(dest, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        progress.update(task, advance=len(chunk))

        size_mb = dest.stat().st_size / (1024 * 1024)
        console.print(f"    Downloaded {dest.name} ({size_mb:.1f} MB)")
