"""
CTD (Comparative Toxicogenomics Database) downloader.

Downloads curated chemical-gene, chemical-disease, and gene-disease
interaction data from CTD.
"""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseDownloader, DatasetMetadata

console = Console()


class CTDDownloader(BaseDownloader):
    """Download CTD interaction files."""

    source_key = "ctd"
    base_url = "https://ctdbase.org/reports"
    license_name = "Open Access (non-commercial research)"

    FILES = [
        "CTD_chem_gene_ixns.tsv.gz",      # Chemical-gene interactions
        "CTD_chemicals_diseases.tsv.gz",   # Chemical-disease associations
        "CTD_genes_diseases.tsv.gz",       # Gene-disease associations
        "CTD_chemicals.tsv.gz",            # Chemical vocabulary (for ID mapping)
    ]

    def download(self, force: bool = False) -> list[DatasetMetadata]:
        """
        Download CTD TSV files.

        Args:
            force: Re-download even if files exist

        Returns:
            List of metadata for downloaded files
        """
        from datetime import datetime

        console.print("[bold cyan]CTD Download[/]")
        results = []
        skipped = 0

        for filename in self.FILES:
            dest = self.raw_dir / filename
            
            if dest.exists() and not force:
                console.print(f"  [dim][skip] {filename} (cached)[/]")
                skipped += 1
                continue

            url = f"{self.base_url}/{filename}"
            console.print(f"  [yellow]Downloading[/] {filename}...")
            
            try:
                self._fetch_url(url, dest)
                
                results.append(DatasetMetadata(
                    source_key=self.source_key,
                    version=datetime.now().strftime("%Y-%m"),
                    download_url=url,
                    local_path=dest,
                    sha256=self._compute_sha256(dest),
                    downloaded_at=datetime.now(),
                    license_name=self.license_name,
                ))
                console.print(f"    [green]✓[/] {filename}: {dest.stat().st_size / 1024 / 1024:.1f} MB")
            except Exception as e:
                console.print(f"  [red]✗[/] {filename}: {e}")

        # Summary
        table = Table(title="CTD Download Summary", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right", style="green")
        table.add_row("Files downloaded", str(len(results)))
        table.add_row("Files skipped", str(skipped))
        console.print(table)

        return results
