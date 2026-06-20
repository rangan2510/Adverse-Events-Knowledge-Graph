"""
SIDER dataset downloader.

Downloads drug-side effect data from SIDER 4.1.
"""

from kg_ae.datasets.base import BaseDownloader, DownloadSpec


class SiderDownloader(BaseDownloader):
    """Download SIDER drug-ADR data."""

    source_key = "sider"
    base_url = "http://sideeffects.embl.de/media/download"
    license_name = "CC BY-NC-SA 4.0"
    version = "4.1"

    # Files to download
    FILES = {
        "meddra_all_se.tsv.gz": "All side effects with MedDRA terms",
        "drug_names.tsv": "STITCH ID to drug name mapping",
        "meddra_freq.tsv.gz": "Side effect frequencies",
    }

    def download_specs(self) -> list[DownloadSpec]:
        return [
            DownloadSpec(url=f"{self.base_url}/{filename}", dest=self.raw_dir / filename, source=self.source_key)
            for filename in self.FILES
        ]
