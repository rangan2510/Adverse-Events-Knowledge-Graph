"""
Reactome dataset downloader.

Downloads pathway data from Reactome.
https://reactome.org/download-data
"""

from datetime import datetime

from kg_ae.datasets.base import BaseDownloader, DatasetMetadata


class ReactomeDownloader(BaseDownloader):
    """Download Reactome pathway data files."""

    source_key = "reactome"
    base_url = "https://reactome.org/download/current"
    license_name = "CC BY 4.0"

    # Key files for gene-pathway relationships
    FILES = {
        # UniProt to pathway mapping (human)
        "UniProt2Reactome.txt": {
            "url": "https://reactome.org/download/current/UniProt2Reactome.txt",
            "description": "UniProt protein to pathway mapping",
        },
        # Pathway hierarchy
        "ReactomePathwaysRelation.txt": {
            "url": "https://reactome.org/download/current/ReactomePathwaysRelation.txt",
            "description": "Pathway parent-child relationships",
        },
        # Pathway names
        "ReactomePathways.txt": {
            "url": "https://reactome.org/download/current/ReactomePathways.txt",
            "description": "Pathway IDs and names",
        },
        # Gene symbol mapping (alternative to UniProt)
        "Ensembl2Reactome.txt": {
            "url": "https://reactome.org/download/current/Ensembl2Reactome.txt",
            "description": "Ensembl gene to pathway mapping",
        },
    }

    def download(self, force: bool = False) -> list[DatasetMetadata]:
        """
        Download Reactome data files.

        Args:
            force: Re-download even if files exist

        Returns:
            List of metadata for downloaded files
        """
        results = []

        for filename, info in self.FILES.items():
            dest = self.raw_dir / filename

            if dest.exists() and not force:
                print(f"  [skip] {filename} exists")
                sha256 = self._compute_sha256(dest)
            else:
                print(f"  [download] {filename}...")
                self._fetch_url(info["url"], dest)
                sha256 = self._compute_sha256(dest)
                print(f"  [done] {filename} ({dest.stat().st_size:,} bytes)")

            results.append(
                DatasetMetadata(
                    source_key=self.source_key,
                    version=None,  # Reactome uses "current" endpoint
                    download_url=info["url"],
                    local_path=dest,
                    sha256=sha256,
                    downloaded_at=datetime.now(),
                    license_name=self.license_name,
                )
            )

        return results
