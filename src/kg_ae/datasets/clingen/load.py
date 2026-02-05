"""
ClinGen loader.

Loads ClinGen gene-disease validity curations into SQL Server graph.
Creates GENE_DISEASE_CLINGEN claims with validity classifications.
"""

import json
from pathlib import Path

import polars as pl
from rich.console import Console
from rich.progress import Progress

from kg_ae.config import settings
from kg_ae.datasets.base import BaseLoader

console = Console()


class ClinGenLoader(BaseLoader):
    """Load ClinGen data into SQL Server graph."""

    source_key = "clingen"

    # Validity classifications and their scores
    VALIDITY_SCORES = {
        "Definitive": 1.0,
        "Strong": 0.9,
        "Moderate": 0.7,
        "Limited": 0.5,
        "Disputed": 0.3,
        "Refuted": 0.1,
        "No Known Disease Relationship": 0.0,
    }

    def __init__(self):
        super().__init__()
        self.bronze_dir = settings.bronze_dir / self.source_key
        self._gene_cache: dict[str, int] = {}
        self._disease_cache: dict[str, int] = {}
        self._caches_loaded = False

    def _preload_caches(self) -> None:
        """Preload lookup caches."""
        if self._caches_loaded:
            return

        console.print("  [dim]Preloading caches...[/]")
        
        # Gene cache (symbol -> gene_key)
        result = self._execute("SELECT gene_key, symbol FROM kg.Gene")
        for row in result:
            self._gene_cache[row[1].upper()] = row[0]
        console.print(f"    Gene cache: {len(self._gene_cache):,} entries")
        
        # Disease cache (mondo_id -> disease_key)
        result = self._execute("SELECT disease_key, mondo_id FROM kg.Disease WHERE mondo_id IS NOT NULL")
        for row in result:
            self._disease_cache[row[1]] = row[0]
        console.print(f"    Disease cache (MONDO): {len(self._disease_cache):,} entries")
        
        self._caches_loaded = True

    def _execute_scalar(self, sql: str, params: tuple = ()):
        """Execute SQL and return single scalar value."""
        result = self._execute(sql, params)
        return result[0][0] if result else None

    def load(self) -> dict[str, int]:
        """
        Load ClinGen data into graph tables.
        
        Returns:
            Dict with counts of loaded entities
        """
        self._preload_caches()

        # Ensure dataset registration
        dataset_id = self.ensure_dataset(
            dataset_key="clingen",
            dataset_name="ClinGen Gene-Disease Validity",
            dataset_version="2024",
            license_name="CC BY 4.0",
            source_url="https://clinicalgenome.org/",
        )

        stats = {}

        validity_path = self.bronze_dir / "validity.parquet"
        if validity_path.exists():
            link_stats = self._load_validity(validity_path, dataset_id)
            stats.update(link_stats)
        else:
            console.print("  [skip] validity.parquet not found")

        return stats

    def _load_validity(self, path: Path, dataset_id: int) -> dict[str, int]:
        """Load gene-disease validity curations."""
        df = pl.read_parquet(path)
        total = len(df)
        console.print(f"  [load] Processing {total:,} gene-disease validity curations...")

        # Check required columns
        required_cols = {"gene_symbol"}
        if not required_cols.issubset(set(df.columns)):
            console.print(f"    [warn] Missing required columns. Have: {df.columns}")
            return {"clingen_claims": 0}

        # Pre-filter using gene cache
        gene_lookup = pl.DataFrame({
            "gene_upper": list(self._gene_cache.keys()),
            "gene_key": list(self._gene_cache.values()),
        })

        df_filtered = (
            df
            .with_columns(pl.col("gene_symbol").str.to_uppercase().alias("gene_upper"))
            .join(gene_lookup, on="gene_upper", how="inner")
        )

        # If we have MONDO IDs, also match diseases
        if "mondo_id" in df.columns and self._disease_cache:
            disease_lookup = pl.DataFrame({
                "mondo_id": list(self._disease_cache.keys()),
                "disease_key": list(self._disease_cache.values()),
            })
            df_filtered = df_filtered.join(disease_lookup, on="mondo_id", how="left")

        match_count = len(df_filtered)
        console.print(f"    [dim]Matched {match_count:,} / {total:,} curations ({100*match_count/total:.1f}%)[/]")

        if match_count == 0:
            console.print("  [loaded] validity: 0 claims")
            return {"clingen_claims": 0}

        # Preload gene node IDs
        gene_node_ids = {}
        result = self._execute("SELECT gene_key, $node_id FROM kg.Gene")
        for row in result:
            gene_node_ids[row[0]] = row[1]

        # Preload disease node IDs if we have disease matches
        disease_node_ids = {}
        if "disease_key" in df_filtered.columns:
            result = self._execute("SELECT disease_key, $node_id FROM kg.Disease")
            for row in result:
                disease_node_ids[row[0]] = row[1]

        claims_created = 0
        batch_size = 500

        with Progress() as progress:
            task = progress.add_task("[cyan]Loading ClinGen", total=match_count)
            rows = df_filtered.iter_rows(named=True)

            while True:
                batch = []
                for _ in range(batch_size):
                    try:
                        row = next(rows)
                        batch.append(row)
                    except StopIteration:
                        break

                if not batch:
                    break

                # Build batched claim VALUES
                claim_values = []
                for row in batch:
                    classification = row.get("classification", "Unknown")
                    score = self.VALIDITY_SCORES.get(classification, 0.5)
                    
                    source_id = f"{row['gene_symbol']}_{row.get('mondo_id', 'unknown')}"
                    stmt_json = json.dumps({
                        "gene_symbol": row["gene_symbol"],
                        "disease_label": row.get("disease_label"),
                        "mondo_id": row.get("mondo_id"),
                        "classification": classification,
                        "inheritance": row.get("inheritance"),
                    }).replace("'", "''")
                    
                    claim_values.append(
                        f"('GENE_DISEASE_CLINGEN', {score}, {dataset_id}, '{source_id}', N'{stmt_json}')"
                    )

                # Insert claims in batch
                claim_sql = f"""
                    INSERT INTO kg.Claim (claim_type, strength_score, dataset_id, source_record_id, statement_json)
                    OUTPUT INSERTED.claim_key
                    VALUES {', '.join(claim_values)}
                """
                claim_results = self._execute(claim_sql)
                claim_keys = [r[0] for r in claim_results]

                if claim_keys:
                    # Get claim node IDs
                    placeholders = ",".join("?" * len(claim_keys))
                    claim_node_results = self._execute(
                        f"SELECT claim_key, $node_id FROM kg.Claim WHERE claim_key IN ({placeholders})",
                        tuple(claim_keys),
                    )
                    claim_node_ids = {r[0]: r[1] for r in claim_node_results}

                    # Build edge VALUES
                    has_claim_values = []
                    claim_disease_values = []

                    for claim_key, row in zip(claim_keys, batch, strict=False):
                        gene_key = row["gene_key"]
                        gene_node = gene_node_ids.get(gene_key)
                        claim_node = claim_node_ids.get(claim_key)

                        if gene_node and claim_node:
                            has_claim_values.append(f"('{gene_node}', '{claim_node}', 'subject')")

                        # Link to disease if we have it
                        disease_key = row.get("disease_key")
                        if disease_key and claim_node:
                            disease_node = disease_node_ids.get(disease_key)
                            if disease_node:
                                classification = row.get("classification", "associated")
                                relation = "causes" if classification in ("Definitive", "Strong") else "associated"
                                claim_disease_values.append(
                                    f"('{claim_node}', '{disease_node}', '{relation}')"
                                )

                    # Insert HasClaim edges
                    if has_claim_values:
                        self._execute(
                            f"INSERT INTO kg.HasClaim ($from_id, $to_id, [role]) VALUES {', '.join(has_claim_values)}"
                        )

                    # Insert ClaimDisease edges
                    if claim_disease_values:
                        sql = "INSERT INTO kg.ClaimDisease ($from_id, $to_id, relation) VALUES "
                        sql += ", ".join(claim_disease_values)
                        self._execute(sql)

                claims_created += len(claim_keys)
                progress.update(task, advance=len(batch))

        console.print(f"  [loaded] validity: {claims_created:,} claims")
        return {"clingen_claims": claims_created}
