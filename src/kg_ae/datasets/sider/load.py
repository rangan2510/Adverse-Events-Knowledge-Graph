"""
SIDER dataset loader.

Loads normalized SIDER data into SQL Server kg.* tables.
"""

import json

import polars as pl
from rich.console import Console
from rich.table import Table

from kg_ae.config import settings
from kg_ae.db import execute, get_connection

console = Console()


class SiderLoader:
    """Load SIDER data into SQL Server knowledge graph."""

    source_key = "sider"
    dataset_name = "SIDER"
    dataset_version = "4.1"
    license_name = "CC BY-NC-SA 4.0"

    def __init__(self):
        self.silver_dir = settings.silver_dir / self.source_key

    def load(self) -> dict[str, int]:
        """
        Load SIDER silver data into kg.* tables.

        Creates:
        - kg.Dataset record for SIDER
        - kg.Drug nodes
        - kg.AdverseEvent nodes
        - kg.Claim nodes (DRUG_AE_LABEL type)
        - kg.Evidence nodes
        - kg.HasClaim edges (Drug → Claim)
        - kg.ClaimAdverseEvent edges (Claim → AdverseEvent)
        - kg.SupportedBy edges (Claim → Evidence)

        Returns:
            Dict with row counts per table
        """
        console.print("[bold cyan]SIDER Loader[/]")
        counts = {}

        # 1. Register dataset
        dataset_id = self._register_dataset()
        console.print(f"  [dim]Registered dataset_id={dataset_id}[/]")

        # 2. Load drugs
        drug_count = self._load_drugs()
        counts["drugs"] = drug_count

        # 3. Load adverse events
        ae_count = self._load_adverse_events()
        counts["adverse_events"] = ae_count

        # 4. Load drug-AE associations (claims + evidence + edges)
        claim_count = self._load_drug_ae_claims(dataset_id)
        counts["claims"] = claim_count

        # Summary table
        table = Table(title="SIDER Load Summary", show_header=True)
        table.add_column("Entity", style="cyan")
        table.add_column("Count", justify="right", style="green")
        for entity, count in counts.items():
            table.add_row(entity.title(), f"{count:,}")
        console.print(table)

        return counts

    def _register_dataset(self) -> int:
        """Register SIDER dataset in kg.Dataset table."""
        # Check if already registered
        rows = execute(
            "SELECT dataset_id FROM kg.Dataset WHERE dataset_key = ? AND version_key = ?",
            (self.source_key, self.dataset_version),
        )
        if rows:
            return rows[0][0]

        # Insert new dataset record
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO kg.Dataset 
                    (dataset_key, dataset_name, dataset_version, license_name, source_url)
                OUTPUT INSERTED.dataset_id
                VALUES (?, ?, ?, ?, ?)
                """,
                self.source_key,
                self.dataset_name,
                self.dataset_version,
                self.license_name,
                "http://sideeffects.embl.de/",
            )
            result = cursor.fetchone()
            conn.commit()
            return result[0]

    def _load_drugs(self) -> int:
        """Load drug entities into kg.Drug table."""
        drugs = pl.read_parquet(self.silver_dir / "drugs.parquet")

        # Build insert data
        insert_data = []
        for row in drugs.iter_rows(named=True):
            xrefs = {
                "stitch_id": row["stitch_id"],
                "stitch_numeric": row["stitch_numeric"],
            }
            insert_data.append((
                row["preferred_name"],
                row["pubchem_cid"] if row["pubchem_cid"] and row["pubchem_cid"] > 0 else None,
                json.dumps(xrefs),
            ))

        # Use MERGE to handle duplicates (by pubchem_cid)
        with get_connection() as conn:
            cursor = conn.cursor()
            inserted = 0
            for name, pubchem_cid, xrefs_json in insert_data:
                # Skip if drug already exists with same pubchem_cid
                if pubchem_cid:
                    cursor.execute(
                        "SELECT drug_key FROM kg.Drug WHERE pubchem_cid = ?",
                        pubchem_cid,
                    )
                    if cursor.fetchone():
                        continue

                cursor.execute(
                    """
                    INSERT INTO kg.Drug (preferred_name, pubchem_cid, xrefs_json)
                    VALUES (?, ?, ?)
                    """,
                    name,
                    pubchem_cid,
                    xrefs_json,
                )
                inserted += 1

            conn.commit()

        console.print(f"    [green]✓[/] Drugs: {inserted:,} new")
        return inserted

    def _load_adverse_events(self) -> int:
        """Load adverse event entities into kg.AdverseEvent table."""
        ae_terms = pl.read_parquet(self.silver_dir / "adverse_events.parquet")

        with get_connection() as conn:
            cursor = conn.cursor()
            inserted = 0

            for row in ae_terms.iter_rows(named=True):
                # Skip if AE already exists with same code
                cursor.execute(
                    "SELECT ae_key FROM kg.AdverseEvent WHERE ae_code = ? AND ae_ontology = ?",
                    row["ae_code"],
                    row["ae_ontology"],
                )
                if cursor.fetchone():
                    continue

                cursor.execute(
                    """
                    INSERT INTO kg.AdverseEvent (ae_label, ae_code, ae_ontology)
                    VALUES (?, ?, ?)
                    """,
                    row["ae_label"],
                    row["ae_code"],
                    row["ae_ontology"],
                )
                inserted += 1

            conn.commit()

        console.print(f"    [green]✓[/] Adverse Events: {inserted:,} new")
        return inserted

    def _load_drug_ae_claims(self, dataset_id: int) -> int:
        """Load drug-AE associations as claims with evidence."""
        pairs = pl.read_parquet(self.silver_dir / "drug_ae_pairs.parquet")

        with get_connection() as conn:
            cursor = conn.cursor()
            claims_created = 0

            for row in pairs.iter_rows(named=True):
                stitch_id = row["stitch_id"]
                ae_code = row["ae_code"]
                freq_score = row["frequency_score"]

                # Find drug by STITCH ID in xrefs_json
                cursor.execute(
                    """
                    SELECT drug_key, $node_id AS node_id FROM kg.Drug 
                    WHERE JSON_VALUE(xrefs_json, '$.stitch_id') = ?
                    """,
                    stitch_id,
                )
                drug_row = cursor.fetchone()
                if not drug_row:
                    continue
                drug_key, drug_node_id = drug_row

                # Find adverse event by code
                cursor.execute(
                    "SELECT ae_key, $node_id AS node_id FROM kg.AdverseEvent WHERE ae_code = ?",
                    ae_code,
                )
                ae_row = cursor.fetchone()
                if not ae_row:
                    continue
                ae_key, ae_node_id = ae_row

                # Create claim
                statement = {
                    "drug_stitch_id": stitch_id,
                    "ae_code": ae_code,
                    "ae_name": row["side_effect_name"],
                    "frequency_text": row["frequency_text"],
                }
                cursor.execute(
                    """
                    INSERT INTO kg.Claim (claim_type, strength_score, dataset_id, statement_json)
                    OUTPUT INSERTED.claim_key, INSERTED.$node_id
                    VALUES (?, ?, ?, ?)
                    """,
                    "DRUG_AE_LABEL",
                    freq_score,
                    dataset_id,
                    json.dumps(statement),
                )
                claim_row = cursor.fetchone()
                claim_key, claim_node_id = claim_row

                # Create evidence
                evidence_payload = {
                    "source": "SIDER",
                    "version": self.dataset_version,
                    "stitch_id": stitch_id,
                    "umls_cui": ae_code,
                }
                cursor.execute(
                    """
                    INSERT INTO kg.Evidence (dataset_id, evidence_type, payload_json)
                    OUTPUT INSERTED.evidence_key, INSERTED.$node_id
                    VALUES (?, ?, ?)
                    """,
                    dataset_id,
                    "CURATED_DB",
                    json.dumps(evidence_payload),
                )
                evidence_row = cursor.fetchone()
                evidence_key, evidence_node_id = evidence_row

                # Create edges using $node_id references
                # HasClaim: Drug → Claim
                cursor.execute(
                    """
                    INSERT INTO kg.HasClaim ($from_id, $to_id, role)
                    VALUES (?, ?, ?)
                    """,
                    drug_node_id,
                    claim_node_id,
                    "subject",
                )

                # ClaimAdverseEvent: Claim → AdverseEvent
                cursor.execute(
                    """
                    INSERT INTO kg.ClaimAdverseEvent ($from_id, $to_id, relation, frequency)
                    VALUES (?, ?, ?, ?)
                    """,
                    claim_node_id,
                    ae_node_id,
                    "associated_with",
                    freq_score,
                )

                # SupportedBy: Claim → Evidence
                cursor.execute(
                    """
                    INSERT INTO kg.SupportedBy ($from_id, $to_id)
                    VALUES (?, ?)
                    """,
                    claim_node_id,
                    evidence_node_id,
                )

                claims_created += 1

                # Commit in batches
                if claims_created % 1000 == 0:
                    conn.commit()

            conn.commit()

        console.print(f"    [green]✓[/] Claims: {claims_created:,} drug-AE associations")
        return claims_created
