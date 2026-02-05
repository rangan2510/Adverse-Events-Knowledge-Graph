"""
HPO (Human Phenotype Ontology) downloader.

Downloads phenotype-disease annotations from HPO.
https://hpo.jax.org/data/annotations
"""

from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import DownloadColumn, Progress, TransferSpeedColumn

from kg_ae.config import settings
from kg_ae.datasets.base import BaseDownloader

console = Console()


class HPODownloader(BaseDownloader):
    """Download HPO phenotype-disease annotations."""

    source_key = "hpo"

    # HPO annotation files
    BASE_URL = "http://purl.obolibrary.org/obo/hp/hpoa"

    FILES = {
        # Phenotype-disease annotations with frequency and citations
        "phenotype_to_genes": "phenotype_to_genes.txt",
        # Gene-disease annotations
        "genes_to_phenotype": "genes_to_phenotype.txt",
        # Disease annotations (phenotypes per disease)
        "phenotype": "phenotype.hpoa",
    }

    def __init__(self):
        super().__init__()
        self.raw_dir = settings.raw_dir / self.source_key
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download(self) -> dict[str, Path]:
        """
        Download HPO annotation files.

        Returns:
            Dict mapping file types to paths
        """
        console.print("[bold cyan]HPO Downloader[/]")

        downloaded = {}

        for key, filename in self.FILES.items():
            url = f"{self.BASE_URL}/{filename}"
            output_path = self.raw_dir / filename

            console.print(f"  Downloading {filename}...")

            try:
                with (
                    httpx.Client(timeout=120.0, follow_redirects=True) as client,
                    client.stream("GET", url) as response,
                ):
                    if response.status_code != 200:
                        console.print(f"    [warn] HTTP {response.status_code}")
                        continue

                    total = int(response.headers.get("content-length", 0))

                    with Progress(
                        *Progress.get_default_columns(),
                        DownloadColumn(),
                        TransferSpeedColumn(),
                    ) as progress:
                        task = progress.add_task(f"[cyan]{filename}", total=total)

                        with open(output_path, "wb") as f:
                            for chunk in response.iter_bytes(chunk_size=8192):
                                f.write(chunk)
                                progress.update(task, advance=len(chunk))

                    size_mb = output_path.stat().st_size / 1024 / 1024
                    console.print(f"    Downloaded {filename} ({size_mb:.1f} MB)")
                    downloaded[key] = output_path

            except Exception as e:
                console.print(f"    [warn] Download error: {e}")

        return downloaded
