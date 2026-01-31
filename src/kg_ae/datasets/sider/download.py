"""
SIDER dataset downloader.

Downloads drug-side effect data from SIDER 4.1.
"""

from datetime import UTC, datetime

from kg_ae.datasets.base import BaseDownloader, DatasetMetadata


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
        results = []

        for filename, _description in self.FILES.items():
            dest = self.raw_dir / filename
            url = f"{self.base_url}/{filename}"

            if dest.exists() and not force:
                print(f"  [skip] {filename} already exists")
                sha256 = self._compute_sha256(dest)
            else:
                print(f"  [download] {filename}...")
                self._fetch_url(url, dest)
                sha256 = self._compute_sha256(dest)
                print(f"  [done] {filename} ({dest.stat().st_size:,} bytes)")

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

        return results
