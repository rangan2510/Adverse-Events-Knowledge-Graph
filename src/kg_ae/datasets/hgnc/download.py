"""
HGNC (HUGO Gene Nomenclature Committee) dataset downloader.

Downloads the complete set of approved human gene symbols and metadata.
This is the canonical reference for human gene nomenclature.
"""

from datetime import datetime

from kg_ae.datasets.base import BaseDownloader, DownloadSpec


class HGNCDownloader(BaseDownloader):
    """Download HGNC gene nomenclature data."""

    source_key = "hgnc"
    base_url = "https://storage.googleapis.com/public-download-files/hgnc/json/json"
    license_name = "CC0 1.0"
    version = datetime.now().strftime("%Y-%m-%d")

    FILES = {"hgnc_complete_set.json": "Complete set of HGNC approved gene symbols"}

    def download_specs(self) -> list[DownloadSpec]:
        return [
            DownloadSpec(
                url=f"{self.base_url}/{filename}",
                dest=self.raw_dir / filename,
                source=self.source_key,
            )
            for filename in self.FILES
        ]
