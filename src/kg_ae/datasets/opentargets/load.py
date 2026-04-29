"""
Open Targets loader.

Loads normalized Open Targets data into SQL Server graph tables.

Performance notes (issue #3):
- Reuses a single connection across all rows. The previous implementation
  called ``self._execute(...)`` per row, which opens a new mssql_python
  connection on every call -- on 450k+ associations this looked like a hang.
- Preloads node-id lookups for kg.Gene and kg.Disease into in-memory dicts.
- Inserts claims and edges in batches and uses ``OUTPUT INSERTED.$node_id``
  to retrieve new claim node ids deterministically (the prior
  ``ORDER BY claim_key DESC TOP 1`` trick was both slow and race-prone).
"""

from __future__ import annotations

import json
from typing import Any

import polars as pl
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from kg_ae.datasets.base import BaseLoader
from kg_ae.db import get_connection

console = Console()

# Batch size for claim + edge inserts. 500 keeps each VALUES clause well under
# SQL Server's 2100 parameter limit (we use ~5 params per claim row).
ASSOCIATION_BATCH_SIZE = 500


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
        results: dict[str, int] = {}

        # Register dataset
        dataset_id = self.ensure_dataset(
            dataset_key=self.source_key,
            dataset_name=self.dataset_name,
            dataset_version="25.03",
            license_name="CC0",
            source_url="https://platform.opentargets.org/",
        )

        # All entity loads share one connection to avoid per-row connect overhead.
        with get_connection() as conn:
            cursor = conn.cursor()

            disease_count = self._load_diseases(cursor)
            conn.commit()
            results["diseases"] = disease_count

            gene_update_count = self._update_genes(cursor)
            conn.commit()
            results["genes_updated"] = gene_update_count

            assoc_count = self._load_associations(cursor, conn, dataset_id)
            results["associations"] = assoc_count

        # Summary table
        table = Table(title="Open Targets Load Summary", show_header=True)
        table.add_column("Entity", style="cyan")
        table.add_column("Count", justify="right", style="green")
        for entity, count in results.items():
            table.add_row(entity.replace("_", " ").title(), f"{count:,}")
        console.print(table)

        return results

    # ------------------------------------------------------------------
    # Diseases
    # ------------------------------------------------------------------
    def _load_diseases(self, cursor: Any) -> int:
        """Load disease entities into kg.Disease table."""
        diseases_path = self.silver_dir / "diseases.parquet"
        if not diseases_path.exists():
            console.print("  [dim][skip] No diseases.parquet found[/]")
            return 0

        df = pl.read_parquet(diseases_path)
        total = len(df)
        console.print(f"  Diseases input: {total:,} rows")

        # Preload existing key sets so we avoid a round-trip per row.
        cursor.execute("SELECT efo_id FROM kg.Disease WHERE efo_id IS NOT NULL")
        existing_efo: set[str] = {r[0] for r in cursor.fetchall()}

        cursor.execute("SELECT mondo_id FROM kg.Disease WHERE mondo_id IS NOT NULL")
        existing_mondo: set[str] = {r[0] for r in cursor.fetchall()}

        cursor.execute("SELECT doid FROM kg.Disease WHERE doid IS NOT NULL")
        existing_doid: set[str] = {r[0] for r in cursor.fetchall()}

        count = 0
        with Progress() as progress:
            task = progress.add_task("[cyan]    Loading diseases", total=total)

            for row in df.iter_rows(named=True):
                progress.advance(task)

                efo_id = row.get("efo_id")
                label = row.get("label", "")
                mondo_id = row.get("mondo_id") or None
                doid = row.get("doid") or None

                if not efo_id or not label:
                    continue

                if efo_id in existing_efo:
                    count += 1
                    continue

                # Backfill EFO id onto an existing MONDO match.
                if mondo_id and mondo_id in existing_mondo:
                    cursor.execute(
                        """
                        UPDATE kg.Disease
                        SET efo_id = ?, updated_at = SYSUTCDATETIME()
                        WHERE mondo_id = ?
                        """,
                        efo_id,
                        mondo_id,
                    )
                    existing_efo.add(efo_id)
                    count += 1
                    continue

                # Backfill EFO/MONDO onto an existing DOID match.
                if doid and doid in existing_doid:
                    cursor.execute(
                        """
                        UPDATE kg.Disease
                        SET efo_id = COALESCE(efo_id, ?),
                            mondo_id = COALESCE(mondo_id, ?),
                            updated_at = SYSUTCDATETIME()
                        WHERE doid = ?
                        """,
                        efo_id,
                        mondo_id,
                        doid,
                    )
                    existing_efo.add(efo_id)
                    if mondo_id:
                        existing_mondo.add(mondo_id)
                    count += 1
                    continue

                # New disease.
                cursor.execute(
                    """
                    INSERT INTO kg.Disease (efo_id, mondo_id, doid, label)
                    VALUES (?, ?, ?, ?)
                    """,
                    efo_id,
                    mondo_id,
                    doid,
                    label,
                )
                existing_efo.add(efo_id)
                if mondo_id:
                    existing_mondo.add(mondo_id)
                if doid:
                    existing_doid.add(doid)
                count += 1

        console.print(f"    [green]done[/] Diseases: {count:,}")
        return count

    # ------------------------------------------------------------------
    # Genes
    # ------------------------------------------------------------------
    def _update_genes(self, cursor: Any) -> int:
        """
        Update existing genes with Ensembl IDs from Open Targets.

        Open Targets does not introduce new genes; it enriches HGNC-loaded
        genes with Ensembl ids and a UniProt id when one is not yet assigned.
        """
        genes_path = self.silver_dir / "genes.parquet"
        if not genes_path.exists():
            console.print("  [dim][skip] No genes.parquet found[/]")
            return 0

        df = pl.read_parquet(genes_path)
        total = len(df)
        console.print(f"  Genes input: {total:,} rows")

        # Preload taken keys to skip duplicates without round-trips.
        cursor.execute("SELECT ensembl_gene_id FROM kg.Gene WHERE ensembl_gene_id IS NOT NULL")
        existing_ensembl: set[str] = {r[0] for r in cursor.fetchall()}

        cursor.execute("SELECT uniprot_id FROM kg.Gene WHERE uniprot_id IS NOT NULL")
        taken_uniprot: set[str] = {r[0] for r in cursor.fetchall()}

        count = 0
        with Progress() as progress:
            task = progress.add_task("[cyan]    Updating genes", total=total)

            for row in df.iter_rows(named=True):
                progress.advance(task)

                ensembl_gene_id = row.get("ensembl_gene_id")
                symbol = row.get("symbol")
                uniprot_id = row.get("uniprot_id")

                if not ensembl_gene_id or not symbol:
                    continue

                if ensembl_gene_id in existing_ensembl:
                    count += 1
                    continue

                # Only assign uniprot_id if it isn't already taken by another
                # gene. Mirrors the guard in hgnc/load.py and prevents
                # violating UX_Gene_UniP when multiple Open Targets targets
                # share a UniProt accession.
                safe_uniprot = uniprot_id if uniprot_id and uniprot_id not in taken_uniprot else None

                cursor.execute(
                    """
                    UPDATE kg.Gene
                    SET ensembl_gene_id = ?,
                        uniprot_id = COALESCE(uniprot_id, ?),
                        updated_at = SYSUTCDATETIME()
                    WHERE symbol = ? AND ensembl_gene_id IS NULL
                    """,
                    ensembl_gene_id,
                    safe_uniprot,
                    symbol,
                )

                if uniprot_id and uniprot_id in taken_uniprot:
                    cursor.execute(
                        """
                        UPDATE kg.Gene
                        SET ensembl_gene_id = ?,
                            symbol = COALESCE(symbol, ?),
                            updated_at = SYSUTCDATETIME()
                        WHERE uniprot_id = ? AND ensembl_gene_id IS NULL
                        """,
                        ensembl_gene_id,
                        symbol,
                        uniprot_id,
                    )

                existing_ensembl.add(ensembl_gene_id)
                if safe_uniprot:
                    taken_uniprot.add(safe_uniprot)
                count += 1

        console.print(f"    [green]done[/] Genes updated: {count:,}")
        return count

    # ------------------------------------------------------------------
    # Associations
    # ------------------------------------------------------------------
    def _load_associations(self, cursor: Any, conn: Any, dataset_id: int) -> int:
        """
        Load gene-disease associations as Claims with edges.

        Strategy:
          1. Preload Ensembl-id -> gene $node_id and EFO-id -> disease $node_id.
          2. Filter the input dataframe to rows whose gene and disease are known.
          3. Insert claims in batches with ``OUTPUT INSERTED.$node_id`` to get
             the new claim node ids back in order.
          4. Build matching HasClaim and ClaimDisease edge rows in a single
             batched insert per edge type.
        """
        associations_path = self.silver_dir / "associations.parquet"
        if not associations_path.exists():
            console.print("  [dim][skip] No associations.parquet found[/]")
            return 0

        df = pl.read_parquet(associations_path)
        total = len(df)
        console.print(f"  Associations input: {total:,} rows")

        # Preload node-id lookups -- one query each, instead of two per row.
        cursor.execute("SELECT ensembl_gene_id, $node_id FROM kg.Gene WHERE ensembl_gene_id IS NOT NULL")
        gene_nodes: dict[str, str] = {r[0]: r[1] for r in cursor.fetchall()}
        console.print(f"    Gene nodes available: {len(gene_nodes):,}")

        cursor.execute("SELECT efo_id, $node_id FROM kg.Disease WHERE efo_id IS NOT NULL")
        disease_nodes: dict[str, str] = {r[0]: r[1] for r in cursor.fetchall()}
        console.print(f"    Disease nodes available: {len(disease_nodes):,}")

        # Materialize input rows that have both endpoints, so we know the
        # progress total up front.
        valid_rows: list[tuple[str, str, float]] = []
        skipped_no_gene = 0
        skipped_no_disease = 0

        for row in df.iter_rows(named=True):
            ensembl_gene_id = row.get("ensembl_gene_id")
            efo_id = row.get("efo_id")
            score = row.get("score") or 0.0

            if not ensembl_gene_id or not efo_id:
                continue
            if ensembl_gene_id not in gene_nodes:
                skipped_no_gene += 1
                continue
            if efo_id not in disease_nodes:
                skipped_no_disease += 1
                continue

            valid_rows.append((ensembl_gene_id, efo_id, float(score)))

        console.print(f"    Valid associations to insert: {len(valid_rows):,}")

        count = 0
        with Progress() as progress:
            task = progress.add_task(
                "[cyan]    Loading associations",
                total=len(valid_rows),
            )

            for batch_start in range(0, len(valid_rows), ASSOCIATION_BATCH_SIZE):
                batch = valid_rows[batch_start : batch_start + ASSOCIATION_BATCH_SIZE]

                # 1) Insert claims for the batch and capture their $node_ids
                #    in insertion order. SQL Server preserves OUTPUT order
                #    relative to the VALUES list when there is no ORDER BY.
                claim_values_sql = ", ".join(["('GENE_DISEASE', ?, ?, ?)"] * len(batch))
                claim_params: list[Any] = []
                for _ensembl, _efo, score in batch:
                    meta = json.dumps({"score": score, "source": "opentargets"})
                    claim_params.extend([score, dataset_id, meta])

                cursor.execute(
                    f"""
                    INSERT INTO kg.Claim (claim_type, strength_score, dataset_id, meta_json)
                    OUTPUT INSERTED.$node_id
                    VALUES {claim_values_sql}
                    """,
                    *claim_params,
                )
                claim_node_ids = [r[0] for r in cursor.fetchall()]

                if len(claim_node_ids) != len(batch):
                    raise RuntimeError(
                        f"Open Targets loader: expected {len(batch)} claim node ids, "
                        f"got {len(claim_node_ids)}"
                    )

                # 2) Build edge VALUES for the same batch.
                has_claim_params: list[Any] = []
                claim_disease_params: list[Any] = []
                for (ensembl, efo, _score), claim_node_id in zip(batch, claim_node_ids, strict=True):
                    gene_node_id = gene_nodes[ensembl]
                    disease_node_id = disease_nodes[efo]
                    has_claim_params.extend([gene_node_id, claim_node_id, "subject"])
                    claim_disease_params.extend([claim_node_id, disease_node_id, "associated_with"])

                has_claim_sql = ", ".join(["(?, ?, ?)"] * len(batch))
                cursor.execute(
                    f"""
                    INSERT INTO kg.HasClaim ($from_id, $to_id, role)
                    VALUES {has_claim_sql}
                    """,
                    *has_claim_params,
                )

                claim_disease_sql = ", ".join(["(?, ?, ?)"] * len(batch))
                cursor.execute(
                    f"""
                    INSERT INTO kg.ClaimDisease ($from_id, $to_id, relation)
                    VALUES {claim_disease_sql}
                    """,
                    *claim_disease_params,
                )

                # Commit per batch so a failure midway doesn't lose hours of work.
                conn.commit()

                count += len(batch)
                progress.advance(task, advance=len(batch))

        console.print(f"    [green]done[/] Associations: {count:,}")
        if skipped_no_gene > 0:
            console.print(f"    [yellow]Skipped[/]: {skipped_no_gene:,} rows - gene not found")
        if skipped_no_disease > 0:
            console.print(f"    [yellow]Skipped[/]: {skipped_no_disease:,} rows - disease not found")
        return count
