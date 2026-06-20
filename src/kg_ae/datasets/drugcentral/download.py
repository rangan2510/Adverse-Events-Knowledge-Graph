"""
DrugCentral dataset downloader.

Downloads drug identity and target data from DrugCentral.
"""

from kg_ae.datasets.base import BaseDownloader, DownloadSpec

_BASE = "https://unmtid-dbs.net/download/DrugCentral"


class DrugCentralDownloader(BaseDownloader):
    """Download DrugCentral drug and target data."""

    source_key = "drugcentral"
    base_url = _BASE
    license_name = "CC BY-SA 4.0"
    version = "2021_09_01"

    # filename -> full URL
    FILES = {
        "drug.target.interaction.tsv.gz": f"{_BASE}/2021_09_01/drug.target.interaction.tsv.gz",
        "structures.smiles.tsv": f"{_BASE}/2021_09_01/structures.smiles.tsv",
        "FDA+EMA+PMDA_Approved.csv": "https://drugcentral.org/static/FDA+EMA+PMDA_Approved.csv",
    }

    def download_specs(self) -> list[DownloadSpec]:
        return [
            DownloadSpec(url=url, dest=self.raw_dir / filename, source=self.source_key)
            for filename, url in self.FILES.items()
        ]
