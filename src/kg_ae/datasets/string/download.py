"""
STRING database downloader.

Downloads human protein-protein interaction data from STRING.
Uses the human-only (taxon 9606) files for efficiency.
"""

from kg_ae.datasets.base import BaseDownloader, DownloadSpec

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


class STRINGDownloader(BaseDownloader):
    """Download STRING human protein interaction data."""

    source_key = "string"
    base_url = STRING_BASE
    license_name = "CC BY 4.0"
    version = STRING_VERSION

    def download_specs(self) -> list[DownloadSpec]:
        specs = []
        for url_path in FILES.values():
            filename = url_path.split("/")[-1]
            specs.append(
                DownloadSpec(url=f"{STRING_BASE}/{url_path}", dest=self.raw_dir / filename, source=self.source_key)
            )
        return specs
