"""
HPO (Human Phenotype Ontology) loader.

Loads HPO gene-phenotype associations into the knowledge graph.
Creates GENE_PHENOTYPE_HPO claims linking genes to phenotype terms.
"""

from pathlib import Path

import polars as pl
from rich.console import Console
from rich.progress import track

from kg_ae.config import settings
from kg_ae.datasets.base import BaseLoader
from kg_ae.db import get_connection

console = Console()


class HPOLoader(BaseLoader):
    """Load HPO gene-phenotype associations."""

    source_key = "hpo"
    claim_type = "GENE_PHENOTYPE_HPO"

    def __init__(self):
        super().__init__()
        self.bronze_dir = settings.bronze_dir / self.source_key

    def load(self) -> dict:
        """
        Load HPO gene-phenotype associations.

        Returns:
            Dict with counts per claim type
        """
        console.print("[bold cyan]HPO Loader[/]")

        with get_connection() as conn:
            cursor = conn.cursor()

            # Register dataset
            dataset_id = self._ensure_dataset(
                cursor,
                dataset_key=self.source_key,
                dataset_name="Human Phenotype Ontology (HPO)",
                license_name="HPO License",
                source_url="https://hpo.jax.org/",
            )

            results = {}

            # Load genes_to_phenotype
            gp_path = self.bronze_dir / "genes_to_phenotype.parquet"
            if gp_path.exists():
                count = self._load_gene_phenotype(cursor, gp_path, dataset_id)
                results["gene_phenotype"] = count

            conn.commit()

        return results

    def _ensure_dataset(self, cursor, dataset_key: str, dataset_name: str, license_name: str, source_url: str) -> int:
        """Register or get existing dataset."""
        cursor.execute(
            """
            SELECT dataset_id FROM kg.Dataset
            WHERE dataset_key = ? AND (dataset_version IS NULL OR dataset_version = '')
        """,
            dataset_key,
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        cursor.execute(
            """
            INSERT INTO kg.Dataset (dataset_key, dataset_name, license_name, source_url)
            OUTPUT INSERTED.dataset_id
            VALUES (?, ?, ?, ?)
        """,
            dataset_key,
            dataset_name,
            license_name,
            source_url,
        )
        return cursor.fetchone()[0]

    def _load_gene_phenotype(self, cursor, path: Path, dataset_id: int) -> int:
        """Load gene-phenotype associations using batched inserts."""
        console.print(f"\n  Loading {path.name}...")

        df = pl.read_parquet(path)
        console.print(f"    Input rows: {len(df):,}")

        # Identify columns
        gene_col = next((c for c in df.columns if "gene_symbol" in c.lower()), None)
        hpo_col = next((c for c in df.columns if "hpo_id" in c.lower()), None)
        hpo_name_col = next((c for c in df.columns if "hpo_name" in c.lower() or "hpo_term" in c.lower()), None)

        if not gene_col or not hpo_col:
            console.print(f"    [warn] Could not find required columns: gene_col={gene_col}, hpo_col={hpo_col}")
            console.print(f"    Available columns: {df.columns}")
            return 0

        console.print(f"    Using columns: gene_col={gene_col}, hpo_col={hpo_col}, hpo_name_col={hpo_name_col}")

        # Preload gene $node_id mapping
        cursor.execute("SELECT symbol, $node_id FROM kg.Gene")
        gene_nodes = {row[0]: row[1] for row in cursor.fetchall()}
        console.print(f"    Gene nodes in DB: {len(gene_nodes):,}")

        # Filter to genes we have
        df_filtered = df.filter(pl.col(gene_col).is_in(list(gene_nodes.keys())))
        console.print(f"    After gene filter: {len(df_filtered):,}")

        if len(df_filtered) == 0:
            console.print("    [warn] No matching genes found")
            return 0

        # Extract data for insertion
        rows = []
        for row in df_filtered.iter_rows(named=True):
            gene_symbol = row[gene_col]
            hpo_id = row[hpo_col]
            hpo_name = row.get(hpo_name_col, "") if hpo_name_col else ""

            if gene_symbol and hpo_id:
                rows.append(
                    {
                        "gene_symbol": gene_symbol,
                        "hpo_id": hpo_id,
                        "hpo_name": hpo_name or "",
                    }
                )

        console.print(f"    Valid rows to insert: {len(rows):,}")

        # Batch insert claims
        batch_size = 500
        total_inserted = 0

        for i in track(range(0, len(rows), batch_size), description="    Loading"):
            batch = rows[i : i + batch_size]

            # Build VALUES clause for batch claim insert
            values_parts = []
            params = []
            for row in batch:
                values_parts.append("(?, ?, NULL, ?, NULL, NULL)")
                params.extend([self.claim_type, dataset_id, row["hpo_id"]])

            if not values_parts:
                continue

            # Insert claims and get back claim_keys + $node_ids
            sql = f"""
                INSERT INTO kg.Claim (claim_type, dataset_id, polarity, source_record_id, strength_score, meta_json)
                OUTPUT INSERTED.claim_key, INSERTED.$node_id
                VALUES {", ".join(values_parts)}
            """
            cursor.execute(sql, params)
            inserted = cursor.fetchall()

            # Build HasClaim edges (Drug -> Claim) - but HPO is Gene -> Phenotype
            # We link Gene -> Claim via HasClaim
            edge_params = []
            for idx, (_claim_key, claim_node_id) in enumerate(inserted):
                gene_symbol = batch[idx]["gene_symbol"]
                gene_node_id = gene_nodes.get(gene_symbol)
                if gene_node_id:
                    # Metadata with HPO info
                    meta = f'{{"hpo_id": "{batch[idx]["hpo_id"]}", "hpo_name": "{batch[idx]["hpo_name"]}"}}'
                    edge_params.extend([gene_node_id, claim_node_id, "subject", meta])

            if edge_params:
                edge_values = ", ".join(["(?, ?, ?, ?)"] * (len(edge_params) // 4))
                edge_sql = f"""
                    INSERT INTO kg.HasClaim ($from_id, $to_id, role, meta_json)
                    VALUES {edge_values}
                """
                cursor.execute(edge_sql, edge_params)

            total_inserted += len(inserted)

        console.print(f"    Inserted {total_inserted:,} {self.claim_type} claims")
        return total_inserted
