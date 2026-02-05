"""
Open Targets loader.

Loads normalized Open Targets data into SQL Server graph tables.
"""

import json

import polars as pl
from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseLoader

console = Console()


class OpenTargetsLoader(BaseLoader):
    """Load Open Targets data into SQL Server graph tables."""

    source_key = "opentargets"
    dataset_name = "Open Targets Platform"

    def load(self) -> dict[str, int]:
        """
        Load Open Targets silver data into SQL Server.

        Returns:
            Dict with counts of loaded entities
        """
        console.print("[bold cyan]Open Targets Loader[/]")
        results = {}

        # Register dataset
        dataset_id = self.ensure_dataset(
            dataset_key=self.source_key,
            dataset_name=self.dataset_name,
            dataset_version="25.03",
            license_name="CC0",
            source_url="https://platform.opentargets.org/",
        )

        # Load diseases
        disease_count = self._load_diseases(dataset_id)
        results["diseases"] = disease_count

        # Update genes with Ensembl IDs
        gene_update_count = self._update_genes(dataset_id)
        results["genes_updated"] = gene_update_count

        # Load gene-disease associations (claims + edges)
        assoc_count = self._load_associations(dataset_id)
        results["associations"] = assoc_count

        # Summary table
        table = Table(title="Open Targets Load Summary", show_header=True)
        table.add_column("Entity", style="cyan")
        table.add_column("Count", justify="right", style="green")
        for entity, count in results.items():
            table.add_row(entity.replace("_", " ").title(), f"{count:,}")
        console.print(table)

        return results

    def _load_diseases(self, dataset_id: int) -> int:
        """
        Load disease entities into kg.Disease table.
        """
        diseases_path = self.silver_dir / "diseases.parquet"
        if not diseases_path.exists():
            console.print("  [dim][skip] No diseases.parquet found[/]")
            return 0

        df = pl.read_parquet(diseases_path)

        count = 0
        for row in df.iter_rows(named=True):
            efo_id = row.get("efo_id")
            label = row.get("label", "")
            mondo_id = row.get("mondo_id") or None
            doid = row.get("doid") or None

            if not efo_id or not label:
                continue

            # Check if disease exists by EFO ID
            existing = self._execute(
                "SELECT disease_key FROM kg.Disease WHERE efo_id = ?",
                (efo_id,),
            )
            if existing:
                count += 1
                continue

            # Check by MONDO ID
            if mondo_id:
                existing = self._execute(
                    "SELECT disease_key FROM kg.Disease WHERE mondo_id = ?",
                    (mondo_id,),
                )
                if existing:
                    # Update with EFO ID
                    self._execute(
                        """
                        UPDATE kg.Disease
                        SET efo_id = ?, updated_at = SYSUTCDATETIME()
                        WHERE mondo_id = ?
                        """,
                        (efo_id, mondo_id),
                    )
                    count += 1
                    continue

            # Check by DOID (multiple EFO IDs can map to same DOID)
            if doid:
                existing = self._execute(
                    "SELECT disease_key FROM kg.Disease WHERE doid = ?",
                    (doid,),
                )
                if existing:
                    # Update with EFO ID if not already set
                    self._execute(
                        """
                        UPDATE kg.Disease
                        SET efo_id = COALESCE(efo_id, ?),
                            mondo_id = COALESCE(mondo_id, ?),
                            updated_at = SYSUTCDATETIME()
                        WHERE doid = ?
                        """,
                        (efo_id, mondo_id, doid),
                    )
                    count += 1
                    continue

            # Insert new disease
            self._execute(
                """
                INSERT INTO kg.Disease (efo_id, mondo_id, doid, label)
                VALUES (?, ?, ?, ?)
                """,
                (efo_id, mondo_id, doid, label),
            )
            count += 1

        console.print(f"    [green]✓[/] Diseases: {count:,}")
        return count

    def _update_genes(self, dataset_id: int) -> int:
        """
        Update existing genes with Ensembl IDs from Open Targets.
        """
        genes_path = self.silver_dir / "genes.parquet"
        if not genes_path.exists():
            console.print("  [dim][skip] No genes.parquet found[/]")
            return 0

        df = pl.read_parquet(genes_path)

        count = 0
        for row in df.iter_rows(named=True):
            ensembl_gene_id = row.get("ensembl_gene_id")
            symbol = row.get("symbol")
            uniprot_id = row.get("uniprot_id")

            if not ensembl_gene_id or not symbol:
                continue

            # Check if this Ensembl ID already exists (avoid duplicate key)
            existing_ensembl = self._execute(
                "SELECT gene_key FROM kg.Gene WHERE ensembl_gene_id = ?",
                (ensembl_gene_id,),
            )
            if existing_ensembl:
                count += 1
                continue

            # Try to update existing gene by symbol
            self._execute(
                """
                UPDATE kg.Gene
                SET ensembl_gene_id = ?,
                    uniprot_id = COALESCE(uniprot_id, ?),
                    updated_at = SYSUTCDATETIME()
                WHERE symbol = ? AND ensembl_gene_id IS NULL
                """,
                (ensembl_gene_id, uniprot_id, symbol),
            )

            # Also try by UniProt ID
            if uniprot_id:
                self._execute(
                    """
                    UPDATE kg.Gene
                    SET ensembl_gene_id = ?,
                        symbol = COALESCE(symbol, ?),
                        updated_at = SYSUTCDATETIME()
                    WHERE uniprot_id = ? AND ensembl_gene_id IS NULL
                    """,
                    (ensembl_gene_id, symbol, uniprot_id),
                )

            count += 1

        console.print(f"    [green]✓[/] Genes updated: {count:,}")
        return count

    def _load_associations(self, dataset_id: int) -> int:
        """
        Load gene-disease associations as Claims with edges.

        Creates GENE_DISEASE claims linking genes to diseases.
        """
        associations_path = self.silver_dir / "associations.parquet"
        if not associations_path.exists():
            console.print("  [dim][skip] No associations.parquet found[/]")
            return 0

        df = pl.read_parquet(associations_path)

        count = 0
        skipped_no_gene = 0
        skipped_no_disease = 0

        for row in df.iter_rows(named=True):
            ensembl_gene_id = row.get("ensembl_gene_id")
            efo_id = row.get("efo_id")
            score = row.get("score", 0)

            if not ensembl_gene_id or not efo_id:
                continue

            # Get gene node by Ensembl ID or symbol
            gene_result = self._execute(
                """
                SELECT $node_id AS node_id, gene_key 
                FROM kg.Gene 
                WHERE ensembl_gene_id = ?
                """,
                (ensembl_gene_id,),
            )
            if not gene_result:
                skipped_no_gene += 1
                continue
            gene_node_id = gene_result[0][0]

            # Get disease node
            disease_result = self._execute(
                "SELECT $node_id AS node_id FROM kg.Disease WHERE efo_id = ?",
                (efo_id,),
            )
            if not disease_result:
                skipped_no_disease += 1
                continue
            disease_node_id = disease_result[0][0]

            # Create claim
            claim_meta = json.dumps(
                {
                    "score": score,
                    "source": "opentargets",
                }
            )
            self._execute(
                """
                INSERT INTO kg.Claim (claim_type, strength_score, dataset_id, meta_json)
                VALUES ('GENE_DISEASE', ?, ?, ?)
                """,
                (score, dataset_id, claim_meta),
            )

            # Get claim node
            claim_result = self._execute(
                """
                SELECT TOP 1 $node_id AS node_id 
                FROM kg.Claim 
                WHERE claim_type = 'GENE_DISEASE' AND dataset_id = ?
                ORDER BY claim_key DESC
                """,
                (dataset_id,),
            )
            claim_node_id = claim_result[0][0]

            # Create edges: Gene -> Claim -> Disease
            self._execute(
                """
                INSERT INTO kg.HasClaim ($from_id, $to_id, role)
                VALUES (?, ?, 'subject')
                """,
                (gene_node_id, claim_node_id),
            )

            self._execute(
                """
                INSERT INTO kg.ClaimDisease ($from_id, $to_id, relation)
                VALUES (?, ?, 'associated_with')
                """,
                (claim_node_id, disease_node_id),
            )

            count += 1

        console.print(f"    [green]✓[/] Associations: {count:,}")
        if skipped_no_gene > 0:
            console.print(f"    [yellow]Skipped[/]: {skipped_no_gene:,} rows - gene not found")
        if skipped_no_disease > 0:
            console.print(f"    [yellow]Skipped[/]: {skipped_no_disease:,} rows - disease not found")
        return count
