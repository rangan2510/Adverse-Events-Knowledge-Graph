"""
openFDA dataset loader.

Loads parsed FDA labeling data into SQL Server graph tables:
- Creates Drug nodes for labeled drugs (if not already present)
- Creates DRUG_LABEL claims linking drugs to their safety sections
"""

import contextlib
import json
from pathlib import Path
from typing import Any

import polars as pl
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from kg_ae.config import settings
from kg_ae.datasets.base import BaseLoader

console = Console()


class OpenFDALoader(BaseLoader):
    """Load openFDA data into SQL Server graph."""

    source_key = "openfda"

    def __init__(self):
        super().__init__()
        self.bronze_dir = settings.bronze_dir / self.source_key

    # ==================== Helper Methods ====================

    def _execute_scalar(self, sql: str, params: tuple = ()) -> Any:
        """Execute SQL and return single scalar value."""
        result = self._execute(sql, params)
        return result[0][0] if result else None

    def _get_node_id(self, table: str, key: int) -> str | None:
        """Get the $node_id for a graph node."""
        key_col = table.split(".")[-1].lower() + "_key"
        result = self._execute(
            f"SELECT $node_id FROM {table} WHERE {key_col} = ?",
            (key,),
        )
        return result[0][0] if result else None

    # ==================== Main Load ====================

    def load(self) -> dict[str, int]:
        """
        Load openFDA data into graph tables.

        Returns:
            Dict with counts of loaded entities
        """
        console.print("[bold cyan]openFDA Loader[/]")

        # Ensure dataset registration
        dataset_id = self.ensure_dataset(
            dataset_key="openfda",
            dataset_name="openFDA",
            license_name="Public Domain (CC0)",
            source_url="https://open.fda.gov/",
        )

        stats = {}

        # Load labels
        labels_path = self.bronze_dir / "labels.parquet"
        if labels_path.exists():
            label_stats = self._load_labels(labels_path, dataset_id)
            stats.update(label_stats)

        # Load NDC
        ndc_path = self.bronze_dir / "ndc.parquet"
        if ndc_path.exists():
            ndc_stats = self._load_ndc(ndc_path, dataset_id)
            stats.update(ndc_stats)

        # Summary table
        if stats:
            table = Table(title="openFDA Load Summary", show_header=True)
            table.add_column("Metric", style="cyan")
            table.add_column("Count", justify="right", style="green")
            for metric, count in stats.items():
                table.add_row(metric.replace('_', ' ').title(), f"{count:,}")
            console.print(table)

        return stats

    # ==================== Label Loading ====================

    def _load_labels(self, path: Path, dataset_id: int) -> dict[str, int]:
        """Load drug labels and create claims."""
        df = pl.read_parquet(path)
        console.print(f"  Processing {len(df):,} labels...")

        drugs_created = 0
        drugs_matched = 0
        claims_created = 0
        evidence_created = 0
        skipped = 0

        with Progress() as progress:
            task = progress.add_task("[cyan]Loading labels", total=len(df))

            for row in df.iter_rows(named=True):
                try:
                    # Get or create drug
                    drug_key = self._ensure_drug(row)
                    if drug_key is None:
                        skipped += 1
                        progress.update(task, advance=1)
                        continue

                    if drug_key == -1:
                        drugs_created += 1
                        drug_key = self._create_drug(row)
                    else:
                        drugs_matched += 1

                    # Create evidence from label sections
                    evidence_key = self._create_label_evidence(row, dataset_id)
                    if evidence_key:
                        evidence_created += 1

                        # Create claim linking drug to label
                        claim_key = self._create_label_claim(
                            drug_key, row, evidence_key, dataset_id
                        )
                        if claim_key:
                            claims_created += 1

                except Exception as e:
                    # Print only first few errors to avoid flooding
                    if skipped < 5:
                        console.print(f"\n  [yellow][warn][/] Error processing label {row.get('set_id')}: {e}")
                    skipped += 1

                progress.update(task, advance=1)

        console.print(f"    [green]✓[/] Labels: {drugs_created} new drugs, {drugs_matched} matched, "
              f"{claims_created} claims, {evidence_created} evidence, {skipped} skipped")

        return {
            "label_drugs_created": drugs_created,
            "label_drugs_matched": drugs_matched,
            "label_claims": claims_created,
            "label_evidence": evidence_created,
        }

    def _ensure_drug(self, row: dict) -> int | None:
        """
        Find or signal need to create drug.
        
        Returns:
            drug_key if found, -1 if should create, None if skip
        """
        generic_name = row.get("generic_name")
        brand_name = row.get("brand_name")

        if not generic_name and not brand_name:
            return None

        # Try to find by name
        name_to_search = generic_name or brand_name

        result = self._execute(
            """
            SELECT drug_key
            FROM kg.Drug
            WHERE preferred_name = ? COLLATE SQL_Latin1_General_CP1_CI_AS
               OR JSON_VALUE(synonyms_json, '$[0]') = ? COLLATE SQL_Latin1_General_CP1_CI_AS
            """,
            (name_to_search, brand_name or ""),
        )

        if result:
            return result[0][0]

        return -1  # Signal to create

    def _create_drug(self, row: dict) -> int:
        """Create a new drug node from label data."""
        generic_name = row.get("generic_name")
        brand_name = row.get("brand_name")
        
        preferred_name = generic_name or brand_name

        # Build synonyms from brand names
        synonyms = []
        if row.get("brand_names_json"):
            with contextlib.suppress(json.JSONDecodeError):
                synonyms.extend(json.loads(row["brand_names_json"]))
        if row.get("generic_names_json"):
            try:
                for gn in json.loads(row["generic_names_json"]):
                    if gn not in synonyms and gn != preferred_name:
                        synonyms.append(gn)
            except json.JSONDecodeError:
                pass

        # Build xrefs
        xrefs = {}
        if row.get("rxcui_json"):
            with contextlib.suppress(json.JSONDecodeError):
                xrefs["rxcui"] = json.loads(row["rxcui_json"])
        if row.get("unii_json"):
            with contextlib.suppress(json.JSONDecodeError):
                xrefs["unii"] = json.loads(row["unii_json"])
        if row.get("spl_id"):
            xrefs["spl_id"] = row["spl_id"]

        drug_key = self._execute_scalar(
            """
            INSERT INTO kg.Drug (preferred_name, synonyms_json, xrefs_json)
            OUTPUT INSERTED.drug_key
            VALUES (?, ?, ?)
            """,
            (
                preferred_name,
                json.dumps(synonyms) if synonyms else None,
                json.dumps(xrefs) if xrefs else None,
            ),
        )
        return drug_key

    def _create_label_evidence(self, row: dict, dataset_id: int) -> int | None:
        """Create evidence record from label sections."""
        # Build payload with all safety sections
        payload = {}
        if row.get("adverse_reactions"):
            payload["adverse_reactions"] = row["adverse_reactions"]
        if row.get("warnings"):
            payload["warnings"] = row["warnings"]
        if row.get("contraindications"):
            payload["contraindications"] = row["contraindications"]
        if row.get("boxed_warning"):
            payload["boxed_warning"] = row["boxed_warning"]
        if row.get("drug_interactions"):
            payload["drug_interactions"] = row["drug_interactions"]

        if not payload:
            return None

        evidence_key = self._execute_scalar(
            """
            INSERT INTO kg.Evidence (
                dataset_id, evidence_type, source_record_id, 
                source_url, payload_json
            )
            OUTPUT INSERTED.evidence_key
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                dataset_id,
                "LABEL_SECTION",
                row.get("set_id"),
                f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={row.get('set_id')}",
                json.dumps(payload),
            ),
        )
        return evidence_key

    def _create_label_claim(
        self, drug_key: int, row: dict, evidence_key: int, dataset_id: int
    ) -> int | None:
        """Create claim linking drug to its label info."""
        # Determine claim strength based on content
        has_boxed = bool(row.get("boxed_warning"))
        has_adverse = bool(row.get("adverse_reactions"))

        # Boxed warnings are highest priority safety info
        score = 0.9 if has_boxed else (0.7 if has_adverse else 0.5)

        # Build statement summary
        sections = []
        if has_boxed:
            sections.append("boxed_warning")
        if has_adverse:
            sections.append("adverse_reactions")
        if row.get("warnings"):
            sections.append("warnings")
        if row.get("contraindications"):
            sections.append("contraindications")

        statement = {
            "sections_present": sections,
            "effective_date": row.get("effective_time"),
            "brand_name": row.get("brand_name"),
            "generic_name": row.get("generic_name"),
        }

        # Insert claim
        claim_key = self._execute_scalar(
            """
            INSERT INTO kg.Claim (
                claim_type, strength_score, dataset_id,
                source_record_id, statement_json
            )
            OUTPUT INSERTED.claim_key
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "DRUG_LABEL",
                score,
                dataset_id,
                row.get("set_id"),
                json.dumps(statement),
            ),
        )

        if not claim_key:
            return None

        # Get node IDs for graph edges
        drug_node_id = self._get_node_id("kg.Drug", drug_key)
        claim_node_id = self._get_node_id("kg.Claim", claim_key)
        evidence_node_id = self._get_node_id("kg.Evidence", evidence_key)

        # Create HasClaim edge (Drug -> Claim)
        if drug_node_id and claim_node_id:
            self._execute(
                """
                INSERT INTO kg.HasClaim ($from_id, $to_id, role)
                VALUES (?, ?, 'subject')
                """,
                (drug_node_id, claim_node_id),
            )

        # Create SupportedBy edge (Claim -> Evidence)
        if claim_node_id and evidence_node_id:
            self._execute(
                """
                INSERT INTO kg.SupportedBy ($from_id, $to_id)
                VALUES (?, ?)
                """,
                (claim_node_id, evidence_node_id),
            )

        return claim_key

    # ==================== NDC Loading ====================

    def _load_ndc(self, path: Path, dataset_id: int) -> dict[str, int]:
        """Load NDC data for drug cross-references."""
        df = pl.read_parquet(path)
        console.print(f"  Processing {len(df):,} NDC products...")

        # NDC is primarily useful for drug cross-references
        # We can use it to enrich existing drug nodes
        updated = 0

        for row in df.iter_rows(named=True):
            generic_name = row.get("generic_name")
            if not generic_name:
                continue

            # Try to find matching drug
            result = self._execute(
                """
                SELECT drug_key, xrefs_json
                FROM kg.Drug
                WHERE preferred_name = ? COLLATE SQL_Latin1_General_CP1_CI_AS
                """,
                (generic_name,),
            )

            if result:
                drug_key, existing_xrefs = result[0]

                # Parse existing xrefs
                xrefs = {}
                if existing_xrefs:
                    with contextlib.suppress(json.JSONDecodeError):
                        xrefs = json.loads(existing_xrefs)

                # Add NDC
                if "ndc" not in xrefs:
                    xrefs["ndc"] = []
                if row.get("product_ndc") not in xrefs["ndc"]:
                    xrefs["ndc"].append(row.get("product_ndc"))

                    # Limit NDC list to prevent huge JSON
                    if len(xrefs["ndc"]) <= 10:
                        # Update drug
                        self._execute(
                            """
                            UPDATE kg.Drug
                            SET xrefs_json = ?, updated_at = SYSUTCDATETIME()
                            WHERE drug_key = ?
                            """,
                            (json.dumps(xrefs), drug_key),
                        )
                        updated += 1

        console.print(f"    [green]✓[/] NDC: {updated} drugs enriched with NDC codes")
        return {"ndc_drugs_enriched": updated}
