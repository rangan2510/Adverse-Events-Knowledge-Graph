"""
ChEMBL loader.

Loads ChEMBL bioactivity data into the knowledge graph.
Creates DRUG_TARGET_CHEMBL claims with binding affinity data.
"""

from pathlib import Path

import polars as pl
from rich.console import Console
from rich.progress import track

from kg_ae.config import settings
from kg_ae.datasets.base import BaseLoader
from kg_ae.db import get_connection

console = Console()


class ChEMBLLoader(BaseLoader):
    """Load ChEMBL bioactivity data."""

    source_key = "chembl"
    claim_type = "DRUG_TARGET_CHEMBL"

    def __init__(self):
        super().__init__()
        self.bronze_dir = settings.bronze_dir / self.source_key

    def load(self) -> dict:
        """
        Load ChEMBL activities.
        
        Returns:
            Dict with counts per claim type
        """
        console.print("[bold cyan]ChEMBL Loader[/]")
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Register dataset
            dataset_id = self._ensure_dataset(
                cursor,
                dataset_key=self.source_key,
                dataset_name="ChEMBL",
                license_name="CC BY-SA 3.0",
                source_url="https://www.ebi.ac.uk/chembl/",
            )
            
            results = {}
            
            # Load activities
            activities_path = self.bronze_dir / "activities.parquet"
            if activities_path.exists():
                count = self._load_activities(cursor, activities_path, dataset_id)
                results["drug_target"] = count
            else:
                console.print("  [skip] No activities.parquet found")
            
            conn.commit()
        
        return results

    def _ensure_dataset(self, cursor, dataset_key: str, dataset_name: str,
                        license_name: str, source_url: str) -> int:
        """Register or get existing dataset."""
        cursor.execute("""
            SELECT dataset_id FROM kg.Dataset
            WHERE dataset_key = ? AND (dataset_version IS NULL OR dataset_version = '')
        """, dataset_key)
        row = cursor.fetchone()
        if row:
            return row[0]
        
        cursor.execute("""
            INSERT INTO kg.Dataset (dataset_key, dataset_name, license_name, source_url)
            OUTPUT INSERTED.dataset_id
            VALUES (?, ?, ?, ?)
        """, dataset_key, dataset_name, license_name, source_url)
        return cursor.fetchone()[0]

    def _load_activities(self, cursor, path: Path, dataset_id: int) -> int:
        """Load drug-target activities using batched inserts."""
        console.print(f"\n  Loading {path.name}...")
        
        df = pl.read_parquet(path)
        console.print(f"    Input rows: {len(df):,}")
        
        # Preload drug $node_id mapping (by ChEMBL ID)
        cursor.execute("SELECT chembl_id, $node_id FROM kg.Drug WHERE chembl_id IS NOT NULL")
        drug_nodes = {row[0]: row[1] for row in cursor.fetchall()}
        console.print(f"    Drugs with ChEMBL ID in DB: {len(drug_nodes):,}")
        
        # Preload gene $node_id mapping (by symbol from target_pref_name)
        cursor.execute("SELECT symbol, $node_id FROM kg.Gene")
        gene_nodes = {row[0]: row[1] for row in cursor.fetchall()}
        console.print(f"    Gene nodes in DB: {len(gene_nodes):,}")
        
        # Filter to drugs we have
        if "molecule_chembl_id" in df.columns:
            df_filtered = df.filter(pl.col("molecule_chembl_id").is_in(list(drug_nodes.keys())))
            console.print(f"    After drug filter: {len(df_filtered):,}")
        else:
            df_filtered = df
        
        if len(df_filtered) == 0:
            console.print("    [warn] No matching drugs found")
            return 0
        
        # Build rows for insertion
        rows = []
        for row in df_filtered.iter_rows(named=True):
            chembl_id = row.get("molecule_chembl_id")
            target_name = row.get("target_pref_name", "")
            best_pchembl = row.get("best_pchembl")
            row.get("mean_pchembl")
            activity_count = row.get("activity_count", 1)
            
            if not chembl_id:
                continue
            
            drug_node_id = drug_nodes.get(chembl_id)
            if not drug_node_id:
                continue
            
            # Normalize pchembl to 0-1 score (pchembl typically 4-10, higher = stronger)
            # pchembl 5 = 10µM, pchembl 7 = 100nM, pchembl 9 = 1nM
            strength_score = None
            if best_pchembl is not None:
                try:
                    pchembl_val = float(best_pchembl)
                    strength_score = min(1.0, max(0.0, (pchembl_val - 4) / 6))
                except (ValueError, TypeError):
                    pass
            
            # Convert best_pchembl to float for storage
            try:
                best_pchembl_float = float(best_pchembl) if best_pchembl is not None else None
            except (ValueError, TypeError):
                best_pchembl_float = None
            
            rows.append({
                "drug_node_id": drug_node_id,
                "chembl_id": chembl_id,
                "target_name": target_name or "",
                "target_chembl_id": row.get("target_chembl_id", ""),
                "strength_score": strength_score,
                "best_pchembl": best_pchembl_float,
                "activity_count": activity_count,
            })
        
        console.print(f"    Valid rows to insert: {len(rows):,}")
        
        if not rows:
            return 0
        
        # Batch insert claims (using string concatenation for bulk insert)
        batch_size = 500
        total_inserted = 0
        
        for i in track(range(0, len(rows), batch_size), description="    Loading"):
            batch = rows[i:i + batch_size]
            
            # Build VALUES clause for batch claim insert
            values_parts = []
            for row in batch:
                pchembl_str = str(row["best_pchembl"]) if row["best_pchembl"] is not None else "null"
                strength_str = str(row["strength_score"]) if row["strength_score"] is not None else "NULL"
                # Escape quotes in target_name for JSON and SQL
                target_name_escaped = str(row["target_name"]).replace("'", "''").replace('"', '\\"')
                target_chembl_escaped = str(row["target_chembl_id"]).replace("'", "''")
                meta = (
                    f'{{"target_chembl_id": "{target_chembl_escaped}", '
                    f'"target_name": "{target_name_escaped}", '
                    f'"best_pchembl": {pchembl_str}, "activity_count": {row["activity_count"]}}}'
                )
                meta_escaped = meta.replace("'", "''")
                
                values_parts.append(
                    f"('{self.claim_type}', {dataset_id}, NULL, "
                    f"'{target_chembl_escaped}', {strength_str}, N'{meta_escaped}')"
                )
            
            if not values_parts:
                continue
            
            # Insert claims and get back claim_keys + $node_ids
            sql = f"""
                INSERT INTO kg.Claim (claim_type, dataset_id, polarity, source_record_id, strength_score, meta_json)
                OUTPUT INSERTED.claim_key, INSERTED.$node_id
                VALUES {', '.join(values_parts)}
            """
            cursor.execute(sql)
            inserted = cursor.fetchall()
            
            # Build HasClaim edges (Drug -> Claim)
            if inserted:
                edge_values = []
                for idx, (_claim_key, claim_node_id) in enumerate(inserted):
                    drug_node_id = batch[idx]["drug_node_id"]
                    edge_values.append(f"('{drug_node_id}', '{claim_node_id}', 'subject')")
                
                if edge_values:
                    edge_sql = f"""
                        INSERT INTO kg.HasClaim ($from_id, $to_id, [role])
                        VALUES {', '.join(edge_values)}
                    """
                    cursor.execute(edge_sql)
            
            total_inserted += len(inserted)
        
        console.print(f"    Inserted {total_inserted:,} {self.claim_type} claims")
        return total_inserted
