"""
Reactome dataset downloader.

Downloads pathway data from Reactome.
https://reactome.org/download-data
"""

from kg_ae.datasets.base import BaseDownloader, DownloadSpec

_BASE = "https://reactome.org/download/current"


class ReactomeDownloader(BaseDownloader):
    """Download Reactome pathway data files."""

    source_key = "reactome"
    base_url = _BASE
    license_name = "CC BY 4.0"

    # filename -> full URL
    FILES = {
        "UniProt2Reactome.txt": f"{_BASE}/UniProt2Reactome.txt",
        "ReactomePathwaysRelation.txt": f"{_BASE}/ReactomePathwaysRelation.txt",
        "ReactomePathways.txt": f"{_BASE}/ReactomePathways.txt",
        "Ensembl2Reactome.txt": f"{_BASE}/Ensembl2Reactome.txt",
    }

    def download_specs(self) -> list[DownloadSpec]:
        return [
            DownloadSpec(url=url, dest=self.raw_dir / filename, source=self.source_key)
            for filename, url in self.FILES.items()
        ]
