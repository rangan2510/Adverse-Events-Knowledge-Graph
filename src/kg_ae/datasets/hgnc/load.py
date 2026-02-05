"""
HGNC loader.

Loads HGNC gene data to enrich existing Gene nodes in SQL Server.
This is primarily an enrichment/update operation, not bulk insert.
"""

import json

import polars as pl
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from kg_ae.config import settings
from kg_ae.datasets.base import BaseLoader

console = Console()


class HGNCLoader(BaseLoader):
    """Load HGNC data to enrich Gene nodes in SQL Server."""

    source_key = "hgnc"
    dataset_name = "HGNC"

    def __init__(self):
        super().__init__()
        # HGNC loads directly from bronze (no normalization needed)
        self.bronze_dir = settings.bronze_dir / self.source_key

    def load(self) -> dict[str, int]:
        """
        Load HGNC gene data into SQL Server.

        This enriches existing Gene nodes with canonical HGNC data
        and inserts new genes not yet in the database.

        Returns:
            Dict with counts of loaded/updated entities
        """
        console.print("[bold cyan]HGNC Loader[/]")
        results = {}

        # Register dataset
        dataset_id = self.ensure_dataset(
            dataset_key=self.source_key,
            dataset_name=self.dataset_name,
            dataset_version="2025",
            license_name="CC0 1.0",
            source_url="https://www.genenames.org/",
        )

        # Load/update genes
        stats = self._load_genes(dataset_id)
        results.update(stats)

        return results

    def _load_genes(self, dataset_id: int) -> dict[str, int]:
        """
        Load gene data - update existing and insert new genes.

        Strategy:
        1. Match by HGNC ID first
        2. Then by Ensembl gene ID
        3. Then by UniProt ID
        4. Then by symbol (case-insensitive)
        5. Insert if no match
        """
        genes_path = self.bronze_dir / "genes.parquet"
        if not genes_path.exists():
            console.print("  [yellow][skip][/] genes.parquet not found")
            return {"genes_updated": 0, "genes_inserted": 0}

        df = pl.read_parquet(genes_path)
        console.print(f"  Loading {len(df):,} HGNC genes...")

        updated = 0
        inserted = 0
        skipped = 0
        total = len(df)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed:,}/{task.total:,}"),
        ) as progress:
            task = progress.add_task("    Processing", total=total)
            for row in df.iter_rows(named=True):
                hgnc_id = row.get("hgnc_id")
                symbol = row.get("symbol")
                ensembl_gene_id = row.get("ensembl_gene_id")
                uniprot_id = row.get("uniprot_id")

                if not symbol:
                    skipped += 1
                    progress.update(task, advance=1)
                    continue

                # Build synonyms JSON
                synonyms = []
                if row.get("alias_symbols_json"):
                    synonyms.extend(json.loads(row["alias_symbols_json"]))
                if row.get("prev_symbols_json"):
                    synonyms.extend(json.loads(row["prev_symbols_json"]))
                synonyms_json = json.dumps(list(set(synonyms))) if synonyms else None

                # Build xrefs JSON
                xrefs = {}
                if row.get("entrez_id"):
                    xrefs["entrez_id"] = row["entrez_id"]
                if row.get("omim_id"):
                    xrefs["omim_id"] = row["omim_id"]
                if row.get("mgd_id"):
                    xrefs["mgd_id"] = row["mgd_id"]
                if row.get("location"):
                    xrefs["location"] = row["location"]
                xrefs_json = json.dumps(xrefs) if xrefs else None

                # Build meta JSON
                meta = {}
                if row.get("name"):
                    meta["name"] = row["name"]
                if row.get("locus_type"):
                    meta["locus_type"] = row["locus_type"]
                if row.get("locus_group"):
                    meta["locus_group"] = row["locus_group"]
                meta_json = json.dumps(meta) if meta else None

                # Try to find existing gene
                gene_key = None

                # 1. Match by HGNC ID
                if hgnc_id:
                    existing = self._execute(
                        "SELECT gene_key FROM kg.Gene WHERE hgnc_id = ?",
                        (hgnc_id,),
                    )
                    if existing:
                        gene_key = existing[0][0]

                # 2. Match by Ensembl gene ID
                if not gene_key and ensembl_gene_id:
                    existing = self._execute(
                        "SELECT gene_key FROM kg.Gene WHERE ensembl_gene_id = ?",
                        (ensembl_gene_id,),
                    )
                    if existing:
                        gene_key = existing[0][0]

                # 3. Match by UniProt ID
                if not gene_key and uniprot_id:
                    existing = self._execute(
                        "SELECT gene_key FROM kg.Gene WHERE uniprot_id = ?",
                        (uniprot_id,),
                    )
                    if existing:
                        gene_key = existing[0][0]

                # 4. Match by symbol (case-insensitive)
                if not gene_key:
                    existing = self._execute(
                        "SELECT gene_key FROM kg.Gene WHERE LOWER(symbol) = LOWER(?)",
                        (symbol,),
                    )
                    if existing:
                        gene_key = existing[0][0]

                if gene_key:
                    # Update existing gene with HGNC canonical data
                    # Only update uniprot_id if it won't cause a duplicate
                    safe_uniprot = None
                    if uniprot_id:
                        existing_up = self._execute(
                            "SELECT gene_key FROM kg.Gene WHERE uniprot_id = ? AND gene_key != ?",
                            (uniprot_id, gene_key),
                        )
                        if not existing_up:
                            safe_uniprot = uniprot_id

                    self._execute(
                        """
                        UPDATE kg.Gene
                        SET hgnc_id = COALESCE(?, hgnc_id),
                            symbol = ?,
                            ensembl_gene_id = COALESCE(?, ensembl_gene_id),
                            uniprot_id = COALESCE(?, uniprot_id),
                            synonyms_json = COALESCE(?, synonyms_json),
                            xrefs_json = COALESCE(?, xrefs_json),
                            meta_json = COALESCE(?, meta_json),
                            updated_at = SYSUTCDATETIME()
                        WHERE gene_key = ?
                        """,
                        (hgnc_id, symbol, ensembl_gene_id, safe_uniprot,
                         synonyms_json, xrefs_json, meta_json, gene_key),
                    )
                    updated += 1
                else:
                    # Check if UniProt ID or Ensembl ID already exist (unique constraint)
                    if uniprot_id:
                        existing = self._execute(
                            "SELECT gene_key FROM kg.Gene WHERE uniprot_id = ?",
                            (uniprot_id,),
                        )
                        if existing:
                            # Gene with this UniProt exists, just skip
                            skipped += 1
                            progress.update(task, advance=1)
                            continue

                    if ensembl_gene_id:
                        existing = self._execute(
                            "SELECT gene_key FROM kg.Gene WHERE ensembl_gene_id = ?",
                            (ensembl_gene_id,),
                        )
                        if existing:
                            # Gene with this Ensembl exists, just skip
                            skipped += 1
                            progress.update(task, advance=1)
                            continue

                    # Insert new gene
                    self._execute(
                        """
                        INSERT INTO kg.Gene (
                            hgnc_id, symbol, ensembl_gene_id, uniprot_id,
                            synonyms_json, xrefs_json, meta_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (hgnc_id, symbol, ensembl_gene_id, uniprot_id,
                         synonyms_json, xrefs_json, meta_json),
                    )
                    inserted += 1

                progress.update(task, advance=1)

        # Summary table
        table = Table(title="Load Summary", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right")
        table.add_row("Updated", f"{updated:,}")
        table.add_row("Inserted", f"{inserted:,}")
        table.add_row("Skipped", f"{skipped:,}")
        console.print(table)

        return {"genes_updated": updated, "genes_inserted": inserted}
