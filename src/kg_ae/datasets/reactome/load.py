"""
Reactome loader.

Loads normalized Reactome data into SQL Server graph tables.
"""

import json

import polars as pl
from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseLoader

console = Console()


class ReactomeLoader(BaseLoader):
    """Load Reactome data into SQL Server graph tables."""

    source_key = "reactome"
    dataset_name = "Reactome"

    def load(self) -> dict[str, int]:
        """
        Load Reactome silver data into SQL Server.

        Returns:
            Dict with counts of loaded entities
        """
        console.print("[bold cyan]Reactome Loader[/]")
        results = {}

        # Register dataset
        dataset_id = self.ensure_dataset(
            dataset_key=self.source_key,
            dataset_name=self.dataset_name,
            dataset_version="current",
            license_name="CC BY 4.0",
            source_url="https://reactome.org/",
        )

        # Load pathways
        pathway_count = self._load_pathways(dataset_id)
        results["pathways"] = pathway_count

        # Load gene-pathway relationships (claims + edges)
        gene_pathway_count = self._load_gene_pathways(dataset_id)
        results["gene_pathways"] = gene_pathway_count

        # Summary table
        table = Table(title="Reactome Load Summary", show_header=True)
        table.add_column("Entity", style="cyan")
        table.add_column("Count", justify="right", style="green")
        for entity, count in results.items():
            table.add_row(entity.replace('_', ' ').title(), f"{count:,}")
        console.print(table)

        return results

    def _load_pathways(self, dataset_id: int) -> int:
        """
        Load pathway entities into kg.Pathway table.
        """
        pathways_path = self.silver_dir / "pathways.parquet"
        if not pathways_path.exists():
            console.print("  [dim][skip] No pathways.parquet found[/]")
            return 0

        df = pl.read_parquet(pathways_path)

        count = 0
        for row in df.iter_rows(named=True):
            reactome_id = row.get("reactome_id")
            label = row.get("label", "")

            if not reactome_id or not label:
                continue

            # Check if pathway exists
            existing = self._execute(
                "SELECT pathway_key FROM kg.Pathway WHERE reactome_id = ?",
                (reactome_id,),
            )
            if existing:
                count += 1
                continue

            # Insert new pathway
            self._execute(
                """
                INSERT INTO kg.Pathway (reactome_id, label)
                VALUES (?, ?)
                """,
                (reactome_id, label),
            )
            count += 1

        console.print(f"    [green]✓[/] Pathways: {count:,}")
        return count

    def _load_gene_pathways(self, dataset_id: int) -> int:
        """
        Load gene-pathway relationships as Claims with edges.

        Creates GENE_PATHWAY claims linking genes to pathways.
        """
        gene_pathways_path = self.silver_dir / "gene_pathways.parquet"
        if not gene_pathways_path.exists():
            console.print("  [dim][skip] No gene_pathways.parquet found[/]")
            return 0

        df = pl.read_parquet(gene_pathways_path)

        count = 0
        skipped_no_gene = 0
        skipped_no_pathway = 0

        for row in df.iter_rows(named=True):
            uniprot_id = row.get("uniprot_id")
            reactome_id = row.get("reactome_id")
            evidence_code = row.get("evidence_code")

            if not uniprot_id or not reactome_id:
                continue

            # Get gene node by UniProt ID
            gene_result = self._execute(
                "SELECT $node_id AS node_id, gene_key FROM kg.Gene WHERE uniprot_id = ?",
                (uniprot_id,),
            )
            if not gene_result:
                skipped_no_gene += 1
                continue
            gene_node_id = gene_result[0][0]

            # Get pathway node
            pathway_result = self._execute(
                "SELECT $node_id AS node_id FROM kg.Pathway WHERE reactome_id = ?",
                (reactome_id,),
            )
            if not pathway_result:
                skipped_no_pathway += 1
                continue
            pathway_node_id = pathway_result[0][0]

            # Create claim
            claim_meta = json.dumps({
                "evidence_code": evidence_code,
                "source": "reactome",
            })
            self._execute(
                """
                INSERT INTO kg.Claim (claim_type, dataset_id, meta_json)
                VALUES ('GENE_PATHWAY', ?, ?)
                """,
                (dataset_id, claim_meta),
            )

            # Get claim node
            claim_result = self._execute(
                """
                SELECT TOP 1 $node_id AS node_id 
                FROM kg.Claim 
                WHERE claim_type = 'GENE_PATHWAY' AND dataset_id = ?
                ORDER BY claim_key DESC
                """,
                (dataset_id,),
            )
            claim_node_id = claim_result[0][0]

            # Create edges: Gene -> Claim -> Pathway
            # Using HasClaim for Gene -> Claim (gene is subject)
            self._execute(
                """
                INSERT INTO kg.HasClaim ($from_id, $to_id, role)
                VALUES (?, ?, 'subject')
                """,
                (gene_node_id, claim_node_id),
            )

            # Using ClaimPathway for Claim -> Pathway
            self._execute(
                """
                INSERT INTO kg.ClaimPathway ($from_id, $to_id, relation)
                VALUES (?, ?, 'member_of')
                """,
                (claim_node_id, pathway_node_id),
            )

            count += 1

        console.print(f"    [green]✓[/] Gene pathways: {count:,}")
        if skipped_no_gene > 0:
            console.print(f"    [yellow]Skipped[/]: {skipped_no_gene:,} rows - gene not found")
        if skipped_no_pathway > 0:
            console.print(f"    [yellow]Skipped[/]: {skipped_no_pathway:,} rows - pathway not found")
        return count
