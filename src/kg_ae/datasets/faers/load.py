"""
FAERS loader.

Loads FAERS disproportionality signals into the knowledge graph.
Creates DRUG_AE_FAERS claims with PRR/ROR signal scores.
"""

from pathlib import Path

import polars as pl
from rich.console import Console
from rich.progress import track

from kg_ae.config import settings
from kg_ae.db import get_connection
from kg_ae.datasets.base import BaseLoader

console = Console()


class FAERSLoader(BaseLoader):
    """Load FAERS signal data."""

    source_key = "faers"
    claim_type = "DRUG_AE_FAERS"

    def __init__(self):
        super().__init__()
        self.bronze_dir = settings.bronze_dir / self.source_key

    def load(self) -> dict:
        """
        Load FAERS signals.
        
        Returns:
            Dict with counts per claim type
        """
        console.print("[bold cyan]FAERS Loader[/]")
        
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Register dataset
            dataset_id = self._ensure_dataset(
                cursor,
                dataset_key=self.source_key,
                dataset_name="FDA Adverse Event Reporting System (FAERS)",
                license_name="Public Domain",
                source_url="https://open.fda.gov/data/faers/",
            )
            
            results = {}
            
            # Load signals
            signals_path = self.bronze_dir / "signals.parquet"
            if signals_path.exists():
                count = self._load_signals(cursor, signals_path, dataset_id)
                results["drug_ae_signals"] = count
            else:
                console.print("  [skip] No signals.parquet found")
            
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

    def _load_signals(self, cursor, path: Path, dataset_id: int) -> int:
        """Load drug-AE signals using batched inserts."""
        console.print(f"\n  Loading {path.name}...")
        
        df = pl.read_parquet(path)
        console.print(f"    Input rows: {len(df):,}")
        
        # Preload drug $node_id mapping (by name - uppercase matching)
        cursor.execute("SELECT UPPER(preferred_name), $node_id FROM kg.Drug")
        drug_nodes = {row[0]: row[1] for row in cursor.fetchall()}
        console.print(f"    Drug nodes in DB: {len(drug_nodes):,}")
        
        # Preload AE $node_id mapping (by label - lowercase matching)
        cursor.execute("SELECT LOWER(ae_label), $node_id FROM kg.AdverseEvent")
        ae_nodes = {row[0]: row[1] for row in cursor.fetchall()}
        console.print(f"    AE nodes in DB: {len(ae_nodes):,}")
        
        # Filter to drugs and AEs we have
        drug_names_upper = set(drug_nodes.keys())
        ae_terms_lower = set(ae_nodes.keys())
        
        df_filtered = df.filter(
            pl.col("drug_name").is_in(list(drug_names_upper)) &
            pl.col("ae_term").is_in(list(ae_terms_lower))
        )
        console.print(f"    After drug+AE filter: {len(df_filtered):,}")
        
        if len(df_filtered) == 0:
            console.print("    [warn] No matching drug-AE pairs found")
            return 0
        
        # Build rows for insertion
        rows = []
        for row in df_filtered.iter_rows(named=True):
            drug_name = row.get("drug_name", "").upper()
            ae_term = row.get("ae_term", "").lower()
            
            drug_node_id = drug_nodes.get(drug_name)
            ae_node_id = ae_nodes.get(ae_term)
            
            if not drug_node_id or not ae_node_id:
                continue
            
            prr = row.get("prr", 1.0)
            ror = row.get("ror", 1.0)
            chi2 = row.get("chi2", 0.0)
            count = row.get("count", 0)
            
            # Normalize signal score: use log(PRR) scaled to 0-1
            # PRR=1 -> 0, PRR=10 -> 0.5, PRR=100 -> 1.0
            import math
            if prr > 1:
                strength_score = min(1.0, math.log10(prr) / 2)
            else:
                strength_score = 0.0
            
            rows.append({
                "drug_node_id": drug_node_id,
                "ae_node_id": ae_node_id,
                "drug_name": drug_name,
                "ae_term": ae_term,
                "prr": prr,
                "ror": ror,
                "chi2": chi2,
                "count": count,
                "strength_score": strength_score,
            })
        
        console.print(f"    Valid rows to insert: {len(rows):,}")
        
        if not rows:
            return 0
        
        # Batch insert claims using string concatenation
        batch_size = 500
        total_inserted = 0
        
        for i in track(range(0, len(rows), batch_size), description="    Loading"):
            batch = rows[i:i + batch_size]
            
            # Build VALUES clause for batch claim insert
            values_parts = []
            for row in batch:
                meta = f'{{"prr": {row["prr"]}, "ror": {row["ror"]}, "chi2": {row["chi2"]}, "count": {row["count"]}}}'
                meta_escaped = meta.replace("'", "''")
                source_id = f'{row["drug_name"]}|||{row["ae_term"]}'.replace("'", "''")
                strength_str = str(row["strength_score"]) if row["strength_score"] is not None else "NULL"
                
                values_parts.append(
                    f"('{self.claim_type}', {dataset_id}, NULL, N'{source_id}', {strength_str}, N'{meta_escaped}')"
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
                for idx, (claim_key, claim_node_id) in enumerate(inserted):
                    drug_node_id = batch[idx]["drug_node_id"]
                    edge_values.append(f"('{drug_node_id}', '{claim_node_id}', 'subject')")
                
                if edge_values:
                    edge_sql = f"""
                        INSERT INTO kg.HasClaim ($from_id, $to_id, [role])
                        VALUES {', '.join(edge_values)}
                    """
                    cursor.execute(edge_sql)
            
            # Build ClaimAdverseEvent edges (Claim -> AE)
            if inserted:
                ae_edge_values = []
                for idx, (claim_key, claim_node_id) in enumerate(inserted):
                    ae_node_id = batch[idx]["ae_node_id"]
                    prr = batch[idx]["prr"]
                    ae_edge_values.append(f"('{claim_node_id}', '{ae_node_id}', 'faers_signal', {prr})")
                
                if ae_edge_values:
                    ae_edge_sql = f"""
                        INSERT INTO kg.ClaimAdverseEvent ($from_id, $to_id, relation, signal_score)
                        VALUES {', '.join(ae_edge_values)}
                    """
                    cursor.execute(ae_edge_sql)
            
            total_inserted += len(inserted)
        
        console.print(f"    Inserted {total_inserted:,} {self.claim_type} claims")
        return total_inserted
