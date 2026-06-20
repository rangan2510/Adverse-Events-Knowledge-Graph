"""
OnSIDES dataset downloader.

Downloads the OnSIDES release ZIP (CSV flat files) from GitHub Releases.
"""

import zipfile
from datetime import UTC, datetime

from rich.console import Console

from kg_ae.datasets.base import BaseDownloader, DatasetMetadata

console = Console()

ONSIDES_VERSION = "v3.1.1"


class OnsidesDownloader(BaseDownloader):
    """Download the OnSIDES release ZIP and extract the CSV tables."""

    source_key = "onsides"
    base_url = "https://github.com/tatonetti-lab/onsides/releases/download"
    license_name = "MIT"

    def download(self, force: bool = False) -> list[DatasetMetadata]:
        console.print("[bold cyan]OnSIDES Downloader[/]")
        filename = f"onsides-{ONSIDES_VERSION}.zip"
        url = f"{self.base_url}/{ONSIDES_VERSION}/{filename}"
        dest = self.raw_dir / filename

        if dest.exists() and not force:
            console.print(f"  [dim][skip] {filename} (cached)[/]")
        else:
            console.print(f"  [yellow]Downloading[/] {filename} (large, ~100s MB)...")
            self._fetch_url(url, dest)
            console.print(f"    [green][ok][/] {filename} ({dest.stat().st_size:,} bytes)")

        # Extract the csv/ folder so the parser can read flat files.
        extract_dir = self.raw_dir / "extracted"
        if force or not extract_dir.exists():
            extract_dir.mkdir(parents=True, exist_ok=True)
            console.print(f"  [yellow]Extracting[/] {filename}...")
            with zipfile.ZipFile(dest) as zf:
                for member in zf.namelist():
                    # Only the CSV data tables are needed.
                    if "/csv/" in member or member.endswith(".csv"):
                        zf.extract(member, extract_dir)
            console.print("    [green][ok][/] extracted csv/ tables")

        sha256 = self._compute_sha256(dest)
        return [
            DatasetMetadata(
                source_key=self.source_key,
                version=ONSIDES_VERSION,
                download_url=url,
                local_path=dest,
                sha256=sha256,
                downloaded_at=datetime.now(UTC),
                license_name=self.license_name,
            )
        ]
