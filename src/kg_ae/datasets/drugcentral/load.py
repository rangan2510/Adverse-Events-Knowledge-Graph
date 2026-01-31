"""
DrugCentral loader.

Loads normalized DrugCentral data into SQL Server graph tables.
"""

import json

import polars as pl

from kg_ae.datasets.base import BaseLoader


class DrugCentralLoader(BaseLoader):
    """Load DrugCentral data into SQL Server graph tables."""

    source_key = "drugcentral"
    dataset_name = "DrugCentral"

    def load(self) -> dict[str, int]:
        """
        Load DrugCentral silver data into SQL Server.

        Returns:
            Dict with counts of loaded entities
        """
        results = {}

        # Register dataset
        dataset_id = self.ensure_dataset(
            dataset_key=self.source_key,
            dataset_name=self.dataset_name,
            dataset_version="2024",  # Will be updated from actual data
            license_name="Open",
            source_url="https://drugcentral.org/",
        )

        # Load drugs
        drug_count = self._load_drugs(dataset_id)
        results["drugs"] = drug_count

        # Load genes
        gene_count = self._load_genes(dataset_id)
        results["genes"] = gene_count

        # Load drug-target interactions (claims + edges)
        interaction_count = self._load_interactions(dataset_id)
        results["interactions"] = interaction_count

        return results

    def _load_drugs(self, dataset_id: int) -> int:
        """
        Load drug entities into kg.Drug table.

        Updates existing drugs with DrugCentral IDs or inserts new ones.
        """
        drugs_path = self.silver_dir / "drugs.parquet"
        if not drugs_path.exists():
            print("  [skip] No drugs.parquet found")
            return 0

        df = pl.read_parquet(drugs_path)

        count = 0
        for row in df.iter_rows(named=True):
            drugcentral_id = row.get("drugcentral_id")
            preferred_name = row.get("preferred_name", "")
            inchikey = row.get("inchikey")
            smiles = row.get("smiles")
            cas_rn = row.get("cas_rn")

            if not preferred_name:
                continue

            # Build xrefs JSON
            xrefs = {}
            if cas_rn:
                xrefs["cas_rn"] = cas_rn
            if smiles:
                xrefs["smiles"] = smiles
            xrefs_json = json.dumps(xrefs) if xrefs else None

            # Check if drug already exists by DrugCentral ID
            existing = self._execute(
                "SELECT drug_key FROM kg.Drug WHERE drugcentral_id = ?",
                (drugcentral_id,),
            )
            if existing:
                count += 1
                continue

            # Check if drug exists by InChIKey and update with drugcentral_id
            if inchikey:
                existing = self._execute(
                    "SELECT drug_key FROM kg.Drug WHERE inchikey = ?",
                    (inchikey,),
                )
                if existing:
                    self._execute(
                        """
                        UPDATE kg.Drug
                        SET drugcentral_id = ?,
                            preferred_name = COALESCE(preferred_name, ?),
                            xrefs_json = COALESCE(?, xrefs_json),
                            updated_at = SYSUTCDATETIME()
                        WHERE inchikey = ?
                        """,
                        (drugcentral_id, preferred_name, xrefs_json, inchikey),
                    )
                    count += 1
                    continue

            # Insert new drug
            self._execute(
                """
                INSERT INTO kg.Drug (
                    preferred_name, drugcentral_id, inchikey, xrefs_json
                )
                VALUES (?, ?, ?, ?)
                """,
                (preferred_name, drugcentral_id, inchikey, xrefs_json),
            )
            count += 1

        print(f"  [loaded] drugs: {count:,}")
        return count

    def _load_genes(self, dataset_id: int) -> int:
        """Load gene/target entities into kg.Gene table."""
        genes_path = self.silver_dir / "genes.parquet"
        if not genes_path.exists():
            print("  [skip] No genes.parquet found")
            return 0

        df = pl.read_parquet(genes_path)

        count = 0
        for row in df.iter_rows(named=True):
            symbol = row.get("symbol")
            uniprot_id = row.get("uniprot_id")

            if not symbol:
                continue

            # Check if gene exists
            existing = self._execute(
                """
                SELECT gene_key FROM kg.Gene 
                WHERE symbol = ? OR uniprot_id = ?
                """,
                (symbol, uniprot_id),
            )
            if existing:
                # Update with UniProt if we have it
                if uniprot_id:
                    self._execute(
                        """
                        UPDATE kg.Gene 
                        SET uniprot_id = COALESCE(uniprot_id, ?),
                            updated_at = SYSUTCDATETIME()
                        WHERE symbol = ?
                        """,
                        (uniprot_id, symbol),
                    )
                count += 1
                continue

            # Insert new gene
            self._execute(
                """
                INSERT INTO kg.Gene (symbol, uniprot_id)
                VALUES (?, ?)
                """,
                (symbol, uniprot_id),
            )
            count += 1

        print(f"  [loaded] genes: {count:,}")
        return count

    def _load_interactions(self, dataset_id: int) -> int:
        """
        Load drug-target interactions as Claims with edges.

        Creates DRUG_TARGET claims linking drugs to genes.
        """
        interactions_path = self.silver_dir / "interactions.parquet"
        if not interactions_path.exists():
            print("  [skip] No interactions.parquet found")
            return 0

        df = pl.read_parquet(interactions_path)

        count = 0
        for row in df.iter_rows(named=True):
            drugcentral_id = row.get("drugcentral_id")
            gene_symbol = row.get("gene_symbol")
            action_type = row.get("action_type")

            if not drugcentral_id or not gene_symbol:
                continue

            # Get drug node
            drug_result = self._execute(
                "SELECT $node_id AS node_id FROM kg.Drug WHERE drugcentral_id = ?",
                (drugcentral_id,),
            )
            if not drug_result:
                continue
            drug_node_id = drug_result[0][0]

            # Get or create gene node
            gene_result = self._execute(
                "SELECT $node_id AS node_id FROM kg.Gene WHERE symbol = ?",
                (gene_symbol,),
            )
            if not gene_result:
                # Insert gene
                self._execute(
                    "INSERT INTO kg.Gene (symbol) VALUES (?)",
                    (gene_symbol,),
                )
                gene_result = self._execute(
                    "SELECT $node_id AS node_id FROM kg.Gene WHERE symbol = ?",
                    (gene_symbol,),
                )
            gene_node_id = gene_result[0][0]

            # Create claim
            claim_meta = json.dumps({
                "action_type": action_type,
                "source": "drugcentral",
            })
            self._execute(
                """
                INSERT INTO kg.Claim (claim_type, dataset_id, meta_json)
                VALUES ('DRUG_TARGET', ?, ?)
                """,
                (dataset_id, claim_meta),
            )

            # Get claim node
            claim_result = self._execute(
                """
                SELECT TOP 1 $node_id AS node_id 
                FROM kg.Claim 
                WHERE claim_type = 'DRUG_TARGET' AND dataset_id = ?
                ORDER BY claim_key DESC
                """,
                (dataset_id,),
            )
            claim_node_id = claim_result[0][0]

            # Create edges: Drug -> Claim -> Gene
            self._execute(
                """
                INSERT INTO kg.HasClaim ($from_id, $to_id, role)
                VALUES (?, ?, 'subject')
                """,
                (drug_node_id, claim_node_id),
            )

            self._execute(
                """
                INSERT INTO kg.ClaimGene ($from_id, $to_id, relation, effect)
                VALUES (?, ?, 'targets', ?)
                """,
                (claim_node_id, gene_node_id, action_type),
            )

            count += 1

        print(f"  [loaded] interactions: {count:,}")
        return count
