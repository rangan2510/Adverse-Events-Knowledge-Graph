"""
STRING database loader.

Loads STRING protein-protein interactions into SQL Server graph tables
as GENE_GENE_STRING claims linking Gene nodes.
"""

import json
from pathlib import Path

import polars as pl
from rich.console import Console
from rich.progress import Progress

from kg_ae.config import settings
from kg_ae.datasets.base import BaseLoader

console = Console()


class STRINGLoader(BaseLoader):
    """Load STRING data into SQL Server graph."""

    source_key = "string"

    def __init__(self):
        super().__init__()
        self.bronze_dir = settings.bronze_dir / self.source_key
        self._gene_cache: dict[str, int] = {}  # uppercase symbol -> gene_key
        self._node_id_cache: dict[tuple[str, int], str] = {}
        self._caches_loaded = False

    def _preload_caches(self) -> None:
        """Preload gene lookup cache."""
        if self._caches_loaded:
            return

        console.print("  [dim]Preloading gene cache...[/]")
        result = self._execute("SELECT gene_key, symbol FROM kg.Gene")
        for row in result:
            self._gene_cache[row[1].upper()] = row[0]
        console.print(f"    Gene cache: {len(self._gene_cache):,} entries")
        self._caches_loaded = True

    def _get_node_id(self, table: str, key: int) -> str | None:
        """Get the $node_id for a graph node (cached)."""
        cache_key = (table, key)
        if cache_key in self._node_id_cache:
            return self._node_id_cache[cache_key]

        key_col = table.split(".")[-1].lower() + "_key"
        result = self._execute(
            f"SELECT $node_id FROM {table} WHERE {key_col} = ?",
            (key,),
        )
        node_id = result[0][0] if result else None
        if node_id:
            self._node_id_cache[cache_key] = node_id
        return node_id

    def _execute_scalar(self, sql: str, params: tuple = ()):
        """Execute SQL and return single scalar value."""
        result = self._execute(sql, params)
        return result[0][0] if result else None

    def load(self) -> dict[str, int]:
        """
        Load STRING data into graph tables.

        Returns:
            Dict with counts of loaded entities
        """
        self._preload_caches()

        # Ensure dataset registration
        dataset_id = self.ensure_dataset(
            dataset_key="string",
            dataset_name="STRING",
            dataset_version="12.0",
            license_name="CC BY 4.0",
            source_url="https://string-db.org/",
        )

        stats = {}

        # Load protein-protein interactions
        links_path = self.bronze_dir / "links.parquet"
        if links_path.exists():
            link_stats = self._load_links(links_path, dataset_id)
            stats.update(link_stats)
        else:
            console.print("  [skip] links.parquet not found")

        return stats

    def _load_links(self, path: Path, dataset_id: int) -> dict[str, int]:
        """Load protein-protein interactions as claims using batched inserts."""
        df = pl.read_parquet(path)
        total = len(df)
        console.print(f"  [load] Processing {total:,} protein-protein interactions...")

        # Pre-filter using gene cache (both genes must exist)
        gene_lookup = pl.DataFrame({
            "gene_upper": list(self._gene_cache.keys()),
            "gene_key": list(self._gene_cache.values()),
        })

        df_filtered = (
            df
            .with_columns([
                pl.col("gene1").str.to_uppercase().alias("gene1_upper"),
                pl.col("gene2").str.to_uppercase().alias("gene2_upper"),
            ])
            .join(
                gene_lookup.rename({"gene_upper": "gene1_upper", "gene_key": "gene1_key"}),
                on="gene1_upper",
                how="inner"
            )
            .join(
                gene_lookup.rename({"gene_upper": "gene2_upper", "gene_key": "gene2_key"}),
                on="gene2_upper",
                how="inner"
            )
        )

        # Remove self-interactions and duplicates (A-B and B-A)
        df_filtered = (
            df_filtered
            .filter(pl.col("gene1_key") != pl.col("gene2_key"))
            .with_columns([
                pl.min_horizontal("gene1_key", "gene2_key").alias("min_key"),
                pl.max_horizontal("gene1_key", "gene2_key").alias("max_key"),
            ])
            .unique(subset=["min_key", "max_key"])
        )

        match_count = len(df_filtered)
        console.print(f"    [dim]Matched {match_count:,} / {total:,} interactions ({100*match_count/total:.1f}%)[/]")

        if match_count == 0:
            console.print("  [loaded] links: 0 claims")
            return {"gene_gene_string_claims": 0}

        # Preload gene $node_id cache
        console.print("    [dim]Preloading gene node IDs...[/]")
        gene_node_ids = {}
        result = self._execute("SELECT gene_key, $node_id FROM kg.Gene")
        for row in result:
            gene_node_ids[row[0]] = row[1]

        claims_created = 0
        batch_size = 500

        with Progress() as progress:
            task = progress.add_task("[cyan]Loading STRING links", total=match_count)
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
                    score_norm = row["combined_score"] / 1000.0
                    source_id = f"{row['protein1']}_{row['protein2']}"
                    stmt_json = json.dumps({
                        "gene1": row["gene1"],
                        "gene2": row["gene2"],
                        "protein1": row["protein1"],
                        "protein2": row["protein2"],
                        "combined_score": row["combined_score"],
                    }).replace("'", "''")
                    claim_values.append(
                        f"('GENE_GENE_STRING', {score_norm}, {dataset_id}, '{source_id}', N'{stmt_json}')"
                    )

                # Insert claims in batch with OUTPUT
                claim_sql = f"""
                    INSERT INTO kg.Claim (claim_type, strength_score, dataset_id, source_record_id, statement_json)
                    OUTPUT INSERTED.claim_key
                    VALUES {', '.join(claim_values)}
                """
                claim_results = self._execute(claim_sql)
                claim_keys = [r[0] for r in claim_results]

                # Get claim node IDs
                if claim_keys:
                    placeholders = ",".join("?" * len(claim_keys))
                    claim_node_results = self._execute(
                        f"SELECT claim_key, $node_id FROM kg.Claim WHERE claim_key IN ({placeholders})",
                        tuple(claim_keys),
                    )
                    claim_node_ids = {r[0]: r[1] for r in claim_node_results}

                    # Build edge VALUES
                    has_claim_values = []
                    claim_gene_values = []

                    for _i, (claim_key, row) in enumerate(zip(claim_keys, batch, strict=False)):
                        gene1_key = row["gene1_key"]
                        gene2_key = row["gene2_key"]

                        gene1_node = gene_node_ids.get(gene1_key)
                        gene2_node = gene_node_ids.get(gene2_key)
                        claim_node = claim_node_ids.get(claim_key)

                        if gene1_node and claim_node:
                            has_claim_values.append(f"('{gene1_node}', '{claim_node}', 'subject')")
                        if gene2_node and claim_node:
                            claim_gene_values.append(f"('{claim_node}', '{gene2_node}', 'interacts')")

                    # Insert HasClaim edges
                    if has_claim_values:
                        self._execute(
                            f"INSERT INTO kg.HasClaim ($from_id, $to_id, [role]) VALUES {', '.join(has_claim_values)}"
                        )

                    # Insert ClaimGene edges
                    if claim_gene_values:
                        sql = "INSERT INTO kg.ClaimGene ($from_id, $to_id, relation) VALUES "
                        sql += ", ".join(claim_gene_values)
                        self._execute(sql)

                claims_created += len(claim_keys)
                progress.update(task, advance=len(batch))

        console.print(f"  [loaded] links: {claims_created:,} claims")
        return {"gene_gene_string_claims": claims_created}


