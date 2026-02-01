"""
ClinGen gene-disease validity curation downloader.

Downloads gene-disease validity data from ClinGen API.
https://search.clinicalgenome.org/kb/gene-validity
"""

import gzip
import json
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import Progress

from kg_ae.config import settings
from kg_ae.datasets.base import BaseDownloader

console = Console()


class ClinGenDownloader(BaseDownloader):
    """Download ClinGen gene-disease validity curations."""

    source_key = "clingen"

    # ClinGen API endpoint for gene-disease validity
    API_BASE = "https://search.clinicalgenome.org/kb"
    VALIDITY_ENDPOINT = "/gene-validity"

    def __init__(self):
        super().__init__()
        self.raw_dir = settings.raw_dir / self.source_key
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(self) -> dict[str, Path]:
        """
        Download ClinGen gene-disease validity curations.
        
        Uses the ClinGen public API to fetch all curations.
        
        Returns:
            Dict mapping file types to paths
        """
        console.print("[bold cyan]ClinGen Downloader[/]")
        
        downloaded = {}
        
        # Fetch gene-disease validity curations via API
        validity_path = self._download_validity_curations()
        if validity_path:
            downloaded["validity"] = validity_path
        
        return downloaded

    def _download_validity_curations(self) -> Path | None:
        """Download gene-disease validity curations from API."""
        output_path = self.raw_dir / "gene_validity.json.gz"
        
        console.print("  Downloading gene-disease validity curations...")
        
        try:
            # ClinGen provides a bulk download TSV, easier than paginating API
            # Direct link to gene-disease validity export
            tsv_url = "https://search.clinicalgenome.org/kb/gene-validity/download"
            
            with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                # First try the TSV export
                response = client.get(tsv_url)
                
                if response.status_code == 200:
                    tsv_path = self.raw_dir / "gene_validity.tsv"
                    tsv_path.write_bytes(response.content)
                    size_mb = len(response.content) / 1024 / 1024
                    console.print(f"    Downloaded gene_validity.tsv ({size_mb:.1f} MB)")
                    return tsv_path
                
                # Fallback: Try JSON API with pagination
                console.print(f"    [dim]TSV download returned {response.status_code}, trying API...[/]")
                
                # Use the API search endpoint
                all_curations = []
                offset = 0
                limit = 500
                
                with Progress() as progress:
                    task = progress.add_task("[cyan]Fetching curations", total=None)
                    
                    while True:
                        api_url = f"{self.API_BASE}/gene-validity?rows={limit}&offset={offset}"
                        resp = client.get(api_url, headers={"Accept": "application/json"})
                        
                        if resp.status_code != 200:
                            console.print(f"    [warn] API returned {resp.status_code}")
                            break
                        
                        data = resp.json()
                        items = data.get("results", [])
                        
                        if not items:
                            break
                        
                        all_curations.extend(items)
                        offset += limit
                        
                        progress.update(task, completed=len(all_curations), 
                                        description=f"[cyan]Fetching curations ({len(all_curations):,})")
                        
                        # Safety limit
                        if offset > 50000:
                            break
                
                if all_curations:
                    # Save as gzipped JSON
                    with gzip.open(output_path, "wt", encoding="utf-8") as f:
                        json.dump(all_curations, f)
                    console.print(f"    Downloaded {len(all_curations):,} curations → gene_validity.json.gz")
                    return output_path
                    
        except httpx.TimeoutException:
            console.print("  [warn] Download timed out")
        except Exception as e:
            console.print(f"  [warn] Download error: {e}")
        
        # Alternative: use the gene-validity flat file from ClinGen FTP
        console.print("  [dim]Trying ClinGen FTP fallback...[/]")
        try:
            ftp_url = "https://www.clinicalgenome.org/docs/downloads/gene-disease-validity-curations.csv"
            with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                response = client.get(ftp_url)
                if response.status_code == 200:
                    csv_path = self.raw_dir / "gene_validity.csv"
                    csv_path.write_bytes(response.content)
                    size_mb = len(response.content) / 1024 / 1024
                    console.print(f"    Downloaded gene_validity.csv ({size_mb:.1f} MB)")
                    return csv_path
        except Exception as e:
            console.print(f"  [warn] FTP fallback failed: {e}")
        
        console.print("  [skip] Could not download ClinGen data")
        return None
