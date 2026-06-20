"""
Guide to PHARMACOLOGY (GtoPdb) dataset downloader.

Downloads curated ligand-target interaction data with quantitative pharmacology.
"""

from kg_ae.datasets.base import BaseDownloader, DownloadSpec


class GtoPdbDownloader(BaseDownloader):
    """Download GtoPdb pharmacology data."""

    source_key = "gtop"
    base_url = "https://www.guidetopharmacology.org/DATA"
    license_name = "CC BY-SA 4.0"

    FILES = {
        "interactions.tsv": "Ligand-target interactions with affinity data",
        "ligands.tsv": "Ligand/drug information with cross-references",
        "targets_and_families.tsv": "Target information and classifications",
        "GtP_to_HGNC_mapping.csv": "Mapping from GtoPdb target IDs to HGNC symbols",
    }

    def download_specs(self) -> list[DownloadSpec]:
        return [
            DownloadSpec(url=f"{self.base_url}/{filename}", dest=self.raw_dir / filename, source=self.source_key)
            for filename in self.FILES
        ]
