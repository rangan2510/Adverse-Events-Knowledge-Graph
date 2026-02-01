"""
GtoPdb loader.

Loads GtoPdb ligand-target interaction data into SQL Server graph tables.
Creates DRUG_TARGET_GTOPDB claims with pharmacological evidence.
"""

import json

import polars as pl
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.table import Table

from kg_ae.config import settings
from kg_ae.datasets.base import BaseLoader

console = Console()


class GtoPdbLoader(BaseLoader):
    """Load GtoPdb data into SQL Server graph tables."""

    source_key = "gtop"
    dataset_name = "Guide to PHARMACOLOGY"

    def __init__(self):
        super().__init__()
        # GtoPdb loads directly from bronze (no normalization needed)
        self.bronze_dir = settings.bronze_dir / self.source_key

    def load(self) -> dict[str, int]:
        """
        Load GtoPdb data into SQL Server.

        Returns:
            Dict with counts of loaded entities
        """
        console.print("[bold cyan]GtoPdb Loader[/]")
        results = {}

        # Register dataset
        dataset_id = self.ensure_dataset(
            dataset_key=self.source_key,
            dataset_name=self.dataset_name,
            dataset_version="2025.4",
            license_name="CC BY-SA 4.0",
            source_url="https://www.guidetopharmacology.org/",
        )

        # Load ligands as drugs (or update existing)
        drug_count = self._load_ligands(dataset_id)
        results["drugs"] = drug_count

        # Load targets as genes (or update existing)
        gene_count = self._load_targets(dataset_id)
        results["genes"] = gene_count

        # Load interactions as claims
        interaction_count = self._load_interactions(dataset_id)
        results["interactions"] = interaction_count

        # Summary table
        table = Table(title="GtoPdb Load Summary", show_header=True)
        table.add_column("Entity", style="cyan")
        table.add_column("Count", justify="right", style="green")
        for entity, count in results.items():
            table.add_row(entity.title(), f"{count:,}")
        console.print(table)

        return results

    def _load_ligands(self, dataset_id: int) -> int:
        """Load GtoPdb ligands as Drug entities."""
        ligands_path = self.bronze_dir / "ligands.parquet"
        if not ligands_path.exists():
            console.print("  [dim][skip] No ligands.parquet found[/]")
            return 0

        df = pl.read_parquet(ligands_path)

        # Focus on approved drugs and synthetic organics
        df = df.filter(
            (pl.col("is_approved") == True) |
            (pl.col("ligand_type") == "Synthetic organic")
        )

        console.print(f"  Processing {len(df):,} GtoPdb ligands...")

        count = 0
        updated = 0
        inserted = 0

        for row in df.iter_rows(named=True):
            ligand_id = row.get("ligand_id")
            name = row.get("name")
            inchikey = row.get("inchikey")
            pubchem_cid = row.get("pubchem_cid")
            chembl_id = row.get("chembl_id")

            if not name:
                continue

            # Clean up values
            if pubchem_cid and str(pubchem_cid).strip():
                try:
                    pubchem_cid = int(float(str(pubchem_cid)))
                except (ValueError, TypeError):
                    pubchem_cid = None
            else:
                pubchem_cid = None

            if chembl_id and str(chembl_id).strip():
                chembl_id = str(chembl_id).strip()
            else:
                chembl_id = None

            if inchikey and str(inchikey).strip():
                inchikey = str(inchikey).strip()
                if len(inchikey) != 27:  # Standard InChIKey length
                    inchikey = None
            else:
                inchikey = None

            # Build xrefs
            xrefs = {"gtopdb_ligand_id": ligand_id}
            if row.get("pubchem_sid"):
                xrefs["pubchem_sid"] = str(row["pubchem_sid"])
            if row.get("inn"):
                xrefs["inn"] = row["inn"]
            if row.get("synonyms"):
                xrefs["synonyms"] = row["synonyms"]
            xrefs_json = json.dumps(xrefs)

            # Try to find existing drug by various IDs
            drug_key = None

            # 1. Match by InChIKey
            if inchikey:
                existing = self._execute(
                    "SELECT drug_key FROM kg.Drug WHERE inchikey = ?",
                    (inchikey,),
                )
                if existing:
                    drug_key = existing[0][0]

            # 2. Match by ChEMBL ID
            if not drug_key and chembl_id:
                existing = self._execute(
                    "SELECT drug_key FROM kg.Drug WHERE chembl_id = ?",
                    (chembl_id,),
                )
                if existing:
                    drug_key = existing[0][0]

            # 3. Match by PubChem CID
            if not drug_key and pubchem_cid:
                existing = self._execute(
                    "SELECT drug_key FROM kg.Drug WHERE pubchem_cid = ?",
                    (pubchem_cid,),
                )
                if existing:
                    drug_key = existing[0][0]

            # 4. Match by name (case-insensitive)
            if not drug_key:
                existing = self._execute(
                    "SELECT drug_key FROM kg.Drug WHERE LOWER(preferred_name) = LOWER(?)",
                    (name,),
                )
                if existing:
                    drug_key = existing[0][0]

            if drug_key:
                # Update existing drug with GtoPdb data
                # Check for unique constraint conflicts before update
                safe_chembl_id = chembl_id
                safe_pubchem_cid = pubchem_cid
                safe_inchikey = inchikey

                if chembl_id:
                    existing = self._execute(
                        "SELECT drug_key FROM kg.Drug WHERE chembl_id = ? AND drug_key != ?",
                        (chembl_id, drug_key),
                    )
                    if existing:
                        safe_chembl_id = None

                if pubchem_cid:
                    existing = self._execute(
                        "SELECT drug_key FROM kg.Drug WHERE pubchem_cid = ? AND drug_key != ?",
                        (pubchem_cid, drug_key),
                    )
                    if existing:
                        safe_pubchem_cid = None

                if inchikey:
                    existing = self._execute(
                        "SELECT drug_key FROM kg.Drug WHERE inchikey = ? AND drug_key != ?",
                        (inchikey, drug_key),
                    )
                    if existing:
                        safe_inchikey = None

                self._execute(
                    """
                    UPDATE kg.Drug
                    SET chembl_id = COALESCE(chembl_id, ?),
                        pubchem_cid = COALESCE(pubchem_cid, ?),
                        inchikey = COALESCE(inchikey, ?),
                        xrefs_json = CASE 
                            WHEN xrefs_json IS NULL THEN ?
                            ELSE JSON_MODIFY(COALESCE(xrefs_json, '{}'), '$.gtopdb_ligand_id', ?)
                        END,
                        updated_at = SYSUTCDATETIME()
                    WHERE drug_key = ?
                    """,
                    (safe_chembl_id, safe_pubchem_cid, safe_inchikey, xrefs_json, str(ligand_id), drug_key),
                )
                updated += 1
            else:
                # Check for unique constraint conflicts before insert
                safe_chembl_id = chembl_id
                safe_pubchem_cid = pubchem_cid
                safe_inchikey = inchikey

                if chembl_id:
                    existing = self._execute(
                        "SELECT drug_key FROM kg.Drug WHERE chembl_id = ?",
                        (chembl_id,),
                    )
                    if existing:
                        safe_chembl_id = None

                if pubchem_cid:
                    existing = self._execute(
                        "SELECT drug_key FROM kg.Drug WHERE pubchem_cid = ?",
                        (pubchem_cid,),
                    )
                    if existing:
                        safe_pubchem_cid = None

                if inchikey:
                    existing = self._execute(
                        "SELECT drug_key FROM kg.Drug WHERE inchikey = ?",
                        (inchikey,),
                    )
                    if existing:
                        safe_inchikey = None

                # Insert new drug
                self._execute(
                    """
                    INSERT INTO kg.Drug (
                        preferred_name, chembl_id, pubchem_cid, inchikey, xrefs_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (name, safe_chembl_id, safe_pubchem_cid, safe_inchikey, xrefs_json),
                )
                inserted += 1

            count += 1

        console.print(f"    [green]✓[/] Ligands: {updated:,} updated, {inserted:,} inserted")
        return count

    def _load_targets(self, dataset_id: int) -> int:
        """Load GtoPdb targets as Gene entities."""
        # Use HGNC mapping for accurate gene assignment
        hgnc_map_path = self.bronze_dir / "hgnc_mapping.parquet"
        if not hgnc_map_path.exists():
            console.print("  [dim][skip] No hgnc_mapping.parquet found[/]")
            return 0

        df = pl.read_parquet(hgnc_map_path)
        console.print(f"  Processing {len(df):,} GtoPdb target-gene mappings...")

        count = 0
        for row in df.iter_rows(named=True):
            hgnc_symbol = row.get("hgnc_symbol")
            hgnc_numeric_id = row.get("hgnc_numeric_id")
            iuphar_id = row.get("iuphar_id")

            if not hgnc_symbol:
                continue

            # Format HGNC ID properly
            hgnc_id = f"HGNC:{hgnc_numeric_id}" if hgnc_numeric_id else None

            # Build xrefs with GtoPdb target ID
            xrefs = {"gtopdb_target_id": iuphar_id}
            xrefs_json = json.dumps(xrefs)

            # Try to find existing gene by HGNC ID or symbol
            gene_key = None

            if hgnc_id:
                existing = self._execute(
                    "SELECT gene_key FROM kg.Gene WHERE hgnc_id = ?",
                    (hgnc_id,),
                )
                if existing:
                    gene_key = existing[0][0]

            if not gene_key:
                existing = self._execute(
                    "SELECT gene_key FROM kg.Gene WHERE LOWER(symbol) = LOWER(?)",
                    (hgnc_symbol,),
                )
                if existing:
                    gene_key = existing[0][0]

            if gene_key:
                # Update existing gene with GtoPdb target ID
                self._execute(
                    """
                    UPDATE kg.Gene
                    SET hgnc_id = COALESCE(hgnc_id, ?),
                        xrefs_json = CASE 
                            WHEN xrefs_json IS NULL THEN ?
                            ELSE JSON_MODIFY(COALESCE(xrefs_json, '{}'), '$.gtopdb_target_id', ?)
                        END,
                        updated_at = SYSUTCDATETIME()
                    WHERE gene_key = ?
                    """,
                    (hgnc_id, xrefs_json, str(iuphar_id), gene_key),
                )
            else:
                # Insert new gene
                self._execute(
                    """
                    INSERT INTO kg.Gene (symbol, hgnc_id, xrefs_json)
                    VALUES (?, ?, ?)
                    """,
                    (hgnc_symbol, hgnc_id, xrefs_json),
                )

            count += 1

        console.print(f"    [green]✓[/] Target-gene mappings: {count:,}")
        return count

    def _load_interactions(self, dataset_id: int) -> int:
        """Load GtoPdb interactions as claims."""
        interactions_path = self.bronze_dir / "interactions.parquet"
        if not interactions_path.exists():
            console.print("  [dim][skip] No interactions.parquet found[/]")
            return 0

        df = pl.read_parquet(interactions_path)

        # Focus on interactions with affinity data
        df = df.filter(
            pl.col("ligand_id").is_not_null() &
            pl.col("target_id").is_not_null()
        )

        console.print(f"  Processing {len(df):,} GtoPdb interactions...")

        count = 0
        claims_created = 0

        for row in df.iter_rows(named=True):
            ligand_id = row.get("ligand_id")
            ligand_name = row.get("ligand_name")
            target_gene_symbol = row.get("target_gene_symbol")
            target_uniprot_id = row.get("target_uniprot_id")
            action = row.get("action")
            affinity_units = row.get("affinity_units")
            affinity_median = row.get("affinity_median")
            pubmed_id = row.get("pubmed_id")

            if not ligand_name or not target_gene_symbol:
                continue

            # Find drug by name or gtopdb_ligand_id in xrefs
            drug_key = None
            existing = self._execute(
                "SELECT drug_key FROM kg.Drug WHERE LOWER(preferred_name) = LOWER(?)",
                (ligand_name,),
            )
            if existing:
                drug_key = existing[0][0]

            if not drug_key:
                # Try via xrefs_json
                existing = self._execute(
                    """
                    SELECT drug_key FROM kg.Drug 
                    WHERE JSON_VALUE(xrefs_json, '$.gtopdb_ligand_id') = ?
                    """,
                    (str(ligand_id),),
                )
                if existing:
                    drug_key = existing[0][0]

            if not drug_key:
                continue  # Skip if drug not found

            # Find gene by symbol or uniprot_id
            gene_key = None
            existing = self._execute(
                "SELECT gene_key FROM kg.Gene WHERE LOWER(symbol) = LOWER(?)",
                (target_gene_symbol,),
            )
            if existing:
                gene_key = existing[0][0]

            if not gene_key and target_uniprot_id:
                existing = self._execute(
                    "SELECT gene_key FROM kg.Gene WHERE uniprot_id = ?",
                    (target_uniprot_id,),
                )
                if existing:
                    gene_key = existing[0][0]

            if not gene_key:
                continue  # Skip if gene not found

            # Calculate normalized strength score from affinity
            # pIC50/pKi of 8 = IC50/Ki of 10nM (very potent)
            # pIC50/pKi of 5 = IC50/Ki of 10µM (moderate)
            strength_score = None
            if affinity_median is not None:
                try:
                    aff = float(affinity_median)
                    if affinity_units in ("pIC50", "pKi", "pKd", "pEC50"):
                        # Higher pXX = more potent = higher score
                        # Normalize: 5 → 0.5, 8 → 0.8, 10 → 1.0
                        strength_score = min(1.0, max(0.0, aff / 10.0))
                except (ValueError, TypeError):
                    pass

            # Map action to effect
            effect = None
            if action:
                action_lower = action.lower()
                if "agonist" in action_lower or "activat" in action_lower:
                    effect = "activates"
                elif "antagonist" in action_lower or "inhibit" in action_lower or "block" in action_lower:
                    effect = "inhibits"
                elif "modulator" in action_lower:
                    effect = "modulates"

            # Build statement JSON
            statement = {
                "ligand_id": ligand_id,
                "target_id": row.get("target_id"),
                "action": action,
                "affinity_units": affinity_units,
                "affinity_median": affinity_median,
            }
            if pubmed_id:
                statement["pubmed_id"] = pubmed_id
            statement_json = json.dumps(statement)

            # Check if this claim already exists
            existing_claim = self._execute(
                """
                SELECT c.claim_key FROM kg.Claim c
                WHERE c.claim_type = 'DRUG_TARGET_GTOPDB'
                  AND c.source_record_id = ?
                """,
                (f"{ligand_id}_{row.get('target_id')}",),
            )

            if existing_claim:
                count += 1
                continue  # Skip duplicate

            # Create claim
            claim_key = self._execute_scalar(
                """
                INSERT INTO kg.Claim (
                    claim_type, strength_score, dataset_id, 
                    source_record_id, statement_json
                )
                OUTPUT INSERTED.claim_key
                VALUES ('DRUG_TARGET_GTOPDB', ?, ?, ?, ?)
                """,
                (strength_score, dataset_id, 
                 f"{ligand_id}_{row.get('target_id')}", statement_json),
            )

            if claim_key:
                # Get node IDs for edges
                drug_node_id = self._get_node_id("kg.Drug", drug_key)
                gene_node_id = self._get_node_id("kg.Gene", gene_key)
                claim_node_id = self._get_node_id("kg.Claim", claim_key)

                if drug_node_id and claim_node_id:
                    # Create HasClaim edge: Drug -> Claim
                    self._execute(
                        """
                        INSERT INTO kg.HasClaim ($from_id, $to_id, role)
                        VALUES (?, ?, 'subject')
                        """,
                        (drug_node_id, claim_node_id),
                    )

                if gene_node_id and claim_node_id:
                    # Create ClaimGene edge: Claim -> Gene
                    self._execute(
                        """
                        INSERT INTO kg.ClaimGene ($from_id, $to_id, relation, effect)
                        VALUES (?, ?, 'targets', ?)
                        """,
                        (claim_node_id, gene_node_id, effect),
                    )

                claims_created += 1

            count += 1

        console.print(f"    [green]✓[/] Interactions: {count:,} processed, {claims_created:,} claims created")
        return claims_created

    def _get_node_id(self, table: str, key: int) -> str | None:
        """Get the $node_id for a graph node."""
        key_col = table.split(".")[-1].lower() + "_key"
        result = self._execute(
            f"SELECT $node_id FROM {table} WHERE {key_col} = ?",
            (key,),
        )
        return result[0][0] if result else None

    def _execute_scalar(self, sql: str, params: tuple = ()) -> any:
        """Execute SQL and return single scalar value."""
        result = self._execute(sql, params)
        return result[0][0] if result else None
