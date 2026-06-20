"""TWOSIDES dataset downloader."""

from kg_ae.datasets.base import BaseDownloader, DownloadSpec


class TwosidesDownloader(BaseDownloader):
    """Download the TWOSIDES drug-drug interaction CSV (gzip)."""

    source_key = "twosides"
    base_url = "https://tatonettilab-resources.s3.us-west-1.amazonaws.com/nsides"
    license_name = "None stated (research only)"
    version = "v0.1"

    FILES = {"TWOSIDES.csv.gz": "Drug-drug interaction adverse-event signals"}

    def download_specs(self) -> list[DownloadSpec]:
        return [
            DownloadSpec(url=f"{self.base_url}/{filename}", dest=self.raw_dir / filename, source=self.source_key)
            for filename in self.FILES
        ]
