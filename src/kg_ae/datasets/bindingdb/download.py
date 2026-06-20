"""
BindingDB dataset downloader.

Downloads the monthly BindingDB_All TSV ZIP and extracts the single large TSV.
"""

import zipfile
from datetime import UTC, datetime

from rich.console import Console

from kg_ae.datasets.base import BaseDownloader, DatasetMetadata

console = Console()

# Monthly release tag (YYYYMM). Bump to re-pin a newer release.
BINDINGDB_RELEASE = "202606"


class BindingdbDownloader(BaseDownloader):
    """Download the BindingDB_All TSV release and extract it."""

    source_key = "bindingdb"
    # Direct static path under /downloads. The JSP endpoint
    # (SDFdownload.jsp?download_file=...) 302-redirects here but is flaky for
    # large files; the direct path is what the md5 links use and is resumable.
    base_url = "https://www.bindingdb.org/rwd/bind/downloads"
    license_name = "CC BY 4.0"

    def download(self, force: bool = False) -> list[DatasetMetadata]:
        console.print("[bold cyan]BindingDB Downloader[/]")
        filename = f"BindingDB_All_{BINDINGDB_RELEASE}_tsv.zip"
        url = f"{self.base_url}/{filename}"
        dest = self.raw_dir / filename

        if dest.exists() and not force:
            console.print(f"  [dim][skip] {filename} (cached)[/]")
        else:
            console.print(f"  [yellow]Downloading[/] {filename} (~563 MB)...")
            self._fetch_url(url, dest, timeout=1800.0)
            console.print(f"    [green][ok][/] {filename} ({dest.stat().st_size:,} bytes)")

        # Extract the TSV next to the zip.
        extract_dir = self.raw_dir / "extracted"
        if force or not extract_dir.exists():
            extract_dir.mkdir(parents=True, exist_ok=True)
            console.print(f"  [yellow]Extracting[/] {filename}...")
            with zipfile.ZipFile(dest) as zf:
                zf.extractall(extract_dir)
            console.print("    [green][ok][/] extracted TSV")

        sha256 = self._compute_sha256(dest)
        return [
            DatasetMetadata(
                source_key=self.source_key,
                version=BINDINGDB_RELEASE,
                download_url=url,
                local_path=dest,
                sha256=sha256,
                downloaded_at=datetime.now(UTC),
                license_name=self.license_name,
            )
        ]
