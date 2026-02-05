"""
HGNC dataset parser.

Parses the HGNC complete gene set JSON to bronze Parquet format.
"""

import json
from pathlib import Path

import polars as pl
from rich.console import Console
from rich.progress import track
from rich.table import Table

from kg_ae.datasets.base import BaseParser

console = Console()


class HGNCParser(BaseParser):
    """Parse HGNC JSON to Parquet."""

    source_key = "hgnc"

    def parse(self) -> dict[str, Path]:
        """
        Parse HGNC complete set JSON to bronze Parquet.

        Returns:
            Dict mapping table names to Parquet file paths
        """
        console.print("[bold cyan]HGNC Parser[/]")
        results = {}

        genes_path = self._parse_genes()
        if genes_path:
            results["genes"] = genes_path

        return results

    def _parse_genes(self) -> Path | None:
        """Parse hgnc_complete_set.json to Parquet."""
        src = self.raw_dir / "hgnc_complete_set.json"
        if not src.exists():
            console.print(f"  [yellow][skip][/] {src.name} not found")
            return None

        dest = self.bronze_dir / "genes.parquet"

        # Load JSON
        console.print(f"  Parsing {src.name}...")
        with open(src, encoding="utf-8") as f:
            data = json.load(f)

        docs = data["response"]["docs"]
        console.print(f"    Input records: {len(docs):,}")

        # Extract relevant fields
        records = []
        for doc in track(docs, description="    Processing genes"):
            # Handle list fields - convert to JSON strings for storage
            alias_symbols = doc.get("alias_symbol", [])
            prev_symbols = doc.get("prev_symbol", [])
            prev_names = doc.get("prev_name", [])
            uniprot_ids = doc.get("uniprot_ids", [])
            pubmed_ids = doc.get("pubmed_id", [])
            gene_groups = doc.get("gene_group", [])

            records.append(
                {
                    "hgnc_id": doc.get("hgnc_id"),  # e.g., "HGNC:5"
                    "symbol": doc.get("symbol"),
                    "name": doc.get("name"),
                    "locus_type": doc.get("locus_type"),
                    "locus_group": doc.get("locus_group"),
                    "status": doc.get("status"),
                    "location": doc.get("location"),
                    "ensembl_gene_id": doc.get("ensembl_gene_id"),
                    "entrez_id": str(doc["entrez_id"]) if doc.get("entrez_id") else None,
                    "uniprot_id": uniprot_ids[0] if uniprot_ids else None,
                    "uniprot_ids_json": json.dumps(uniprot_ids) if uniprot_ids else None,
                    "alias_symbols_json": json.dumps(alias_symbols) if alias_symbols else None,
                    "prev_symbols_json": json.dumps(prev_symbols) if prev_symbols else None,
                    "prev_names_json": json.dumps(prev_names) if prev_names else None,
                    "pubmed_ids_json": json.dumps(pubmed_ids) if pubmed_ids else None,
                    "gene_groups_json": json.dumps(gene_groups) if gene_groups else None,
                    "omim_id": doc.get("omim_id", [None])[0] if doc.get("omim_id") else None,
                    "mgd_id": doc.get("mgd_id", [None])[0] if doc.get("mgd_id") else None,
                    "rgd_id": doc.get("rgd_id", [None])[0] if doc.get("rgd_id") else None,
                }
            )

        df = pl.DataFrame(records)

        # Filter to approved genes with symbols
        df = df.filter((pl.col("status") == "Approved") & pl.col("symbol").is_not_null())

        df.write_parquet(dest)

        # Summary table
        table = Table(title="Parse Summary", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right")
        table.add_row("Input records", f"{len(docs):,}")
        table.add_row("Approved genes", f"{len(df):,}")
        table.add_row("Output", dest.name)
        console.print(table)

        return dest
