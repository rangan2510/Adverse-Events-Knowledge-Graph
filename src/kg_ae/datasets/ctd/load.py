"""
CTD dataset loader.

Loads CTD curated data into SQL Server graph tables:
- Chemical-gene interactions → DRUG_GENE_CTD claims
- Chemical-disease associations → DRUG_DISEASE_CTD claims
- Gene-disease associations → GENE_DISEASE_CTD claims

Optimized with preloaded caches for fast name→key lookups.
"""

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


class CTDLoader(BaseLoader):
    """Load CTD data into SQL Server graph."""

    source_key = "ctd"

    def __init__(self):
        super().__init__()
        self.bronze_dir = settings.bronze_dir / self.source_key
        self._drug_cache: dict[str, int] = {}  # lowercase name -> key
        self._gene_cache: dict[str, int] = {}  # uppercase symbol -> key
        self._disease_cache: dict[str, int] = {}  # lowercase label -> key
        self._node_id_cache: dict[tuple[str, int], str] = {}  # (table, key) -> $node_id
        self._caches_loaded = False

    # ==================== Cache Preloading ====================

    def _preload_caches(self) -> None:
        """Preload all lookup caches from the database."""
        if self._caches_loaded:
            return

        console.print("  [dim]Preloading entity caches...[/]")

        # Load all drugs (case-insensitive)
        result = self._execute("SELECT drug_key, preferred_name FROM kg.Drug")
        for row in result:
            self._drug_cache[row[1].lower()] = row[0]
        console.print(f"    [green]✓[/] Drug cache: {len(self._drug_cache):,} entries")

        # Load all genes (case-insensitive symbols)
        result = self._execute("SELECT gene_key, symbol FROM kg.Gene")
        for row in result:
            self._gene_cache[row[1].upper()] = row[0]
        console.print(f"    [green]✓[/] Gene cache: {len(self._gene_cache):,} entries")

        # Load all diseases (case-insensitive)
        result = self._execute("SELECT disease_key, label FROM kg.Disease")
        for row in result:
            self._disease_cache[row[1].lower()] = row[0]
        console.print(f"    [green]✓[/] Disease cache: {len(self._disease_cache):,} entries")

        self._caches_loaded = True

    # ==================== Helper Methods ====================

    def _execute_scalar(self, sql: str, params: tuple = ()) -> Any:
        """Execute SQL and return single scalar value."""
        result = self._execute(sql, params)
        return result[0][0] if result else None

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

    def _find_drug_by_name(self, name: str) -> int | None:
        """Find drug by name (case-insensitive, from cache)."""
        return self._drug_cache.get(name.lower())

    def _find_gene_by_symbol(self, symbol: str) -> int | None:
        """Find gene by symbol (case-insensitive, from cache)."""
        return self._gene_cache.get(symbol.upper())

    def _find_disease_by_label(self, label: str) -> int | None:
        """Find disease by label (case-insensitive, from cache)."""
        return self._disease_cache.get(label.lower())

    def _create_disease(self, label: str, disease_id: str | None) -> int | None:
        """Create a new disease node and add to cache."""
        # Truncate label if too long
        if len(label) > 400:
            label = label[:397] + "..."

        # Parse disease_id for MESH/OMIM
        xrefs = {}
        if disease_id:
            if disease_id.startswith("MESH:"):
                xrefs["mesh_id"] = disease_id
            elif disease_id.startswith("OMIM:"):
                xrefs["omim_id"] = disease_id
            else:
                xrefs["ctd_id"] = disease_id

        disease_key = self._execute_scalar(
            """
            INSERT INTO kg.Disease (label, xrefs_json)
            OUTPUT INSERTED.disease_key
            VALUES (?, ?)
            """,
            (label, json.dumps(xrefs) if xrefs else None),
        )

        if disease_key:
            self._disease_cache[label.lower()] = disease_key
        return disease_key

    # ==================== Main Load ====================

    def load(self) -> dict[str, int]:
        """
        Load CTD data into graph tables.

        Returns:
            Dict with counts of loaded entities
        """
        console.print("[bold cyan]CTD Load[/]")

        # Preload caches for fast lookups
        self._preload_caches()

        # Ensure dataset registration
        dataset_id = self.ensure_dataset(
            dataset_key="ctd",
            dataset_name="Comparative Toxicogenomics Database",
            license_name="Open Access (non-commercial)",
            source_url="https://ctdbase.org/",
        )

        stats = {}

        # Load chemical-gene interactions
        # NOTE: Skipped for now - 500K rows takes too long with single-row inserts
        # TODO: Implement bulk insert via staging table
        chem_gene_path = self.bronze_dir / "chem_gene.parquet"
        if chem_gene_path.exists():
            console.print("  [dim][skip] chem-gene: 500K rows - use bulk loader[/]")
            # cg_stats = self._load_chem_gene(chem_gene_path, dataset_id)
            # stats.update(cg_stats)

        # Load gene-disease associations
        gene_disease_path = self.bronze_dir / "gene_disease.parquet"
        if gene_disease_path.exists():
            gd_stats = self._load_gene_disease(gene_disease_path, dataset_id)
            stats.update(gd_stats)

        # Load chemical-disease associations
        chem_disease_path = self.bronze_dir / "chem_disease.parquet"
        if chem_disease_path.exists():
            cd_stats = self._load_chem_disease(chem_disease_path, dataset_id)
            stats.update(cd_stats)

        # Summary table
        table = Table(title="CTD Load Summary", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Count", justify="right", style="green")
        for k, v in stats.items():
            table.add_row(k.replace("_", " ").title(), f"{v:,}")
        console.print(table)

        return stats

    # ==================== Chemical-Gene Loading ====================

    def _load_chem_gene(self, path: Path, dataset_id: int) -> dict[str, int]:
        """Load chemical-gene interactions as claims."""
        df = pl.read_parquet(path)
        total = len(df)
        console.print(f"  [yellow]Processing[/] {total:,} chemical-gene interactions...")

        # Pre-filter using caches to avoid iterating over all 1.3M rows
        # Create lookup DataFrames from caches
        drug_lookup = pl.DataFrame(
            {
                "chemical_name_lower": list(self._drug_cache.keys()),
                "drug_key": list(self._drug_cache.values()),
            }
        )
        gene_lookup = pl.DataFrame(
            {
                "gene_symbol_upper": list(self._gene_cache.keys()),
                "gene_key": list(self._gene_cache.values()),
            }
        )

        # Add lowercase/uppercase columns and join
        df_filtered = (
            df.with_columns(
                [
                    pl.col("chemical_name").str.to_lowercase().alias("chemical_name_lower"),
                    pl.col("gene_symbol").str.to_uppercase().alias("gene_symbol_upper"),
                ]
            )
            .join(drug_lookup, on="chemical_name_lower", how="inner")
            .join(gene_lookup, on="gene_symbol_upper", how="inner")
        )

        match_count = len(df_filtered)
        console.print(f"    [dim]Matched {match_count:,} / {total:,} rows ({100 * match_count / total:.1f}%)[/]")

        if match_count == 0:
            console.print("  [loaded] chem-gene: 0 claims")
            return {"chem_gene_claims": 0}

        claims_created = 0
        errors = 0

        with Progress() as progress:
            task = progress.add_task("[cyan]Loading chem-gene", total=match_count)

            for row in df_filtered.iter_rows(named=True):
                try:
                    drug_key = row["drug_key"]
                    gene_key = row["gene_key"]

                    # Create claim
                    claim_key = self._create_chem_gene_claim(drug_key, gene_key, row, dataset_id)
                    if claim_key:
                        claims_created += 1

                except Exception as e:
                    if errors < 3:
                        console.print(f"\n  [warn] Error: {e}")
                    errors += 1

                progress.update(task, advance=1)

        console.print(f"    [green]✓[/] chem-gene: {claims_created:,} claims")
        return {"chem_gene_claims": claims_created}

    def _create_chem_gene_claim(self, drug_key: int, gene_key: int, row: dict, dataset_id: int) -> int | None:
        """Create a chemical-gene interaction claim."""
        interaction = row.get("interaction", "")
        actions = row.get("interaction_actions", "")
        pubmed_ids = row.get("pubmed_ids", "")

        # Build statement with embedded pubmed_ids
        statement = {
            "interaction": interaction[:500] if interaction else None,
            "actions": actions[:200] if actions else None,
            "chemical_id": row.get("chemical_id"),
            "gene_id": row.get("gene_id"),
            "pubmed_ids": pubmed_ids.split("|")[:20] if pubmed_ids else None,
        }

        # Score based on evidence count (PubMed IDs)
        pmid_count = len(pubmed_ids.split("|")) if pubmed_ids else 0
        score = min(0.5 + (pmid_count * 0.1), 1.0)

        # Parse action for effect
        effect = None
        if actions:
            actions_lower = actions.lower()
            if "increase" in actions_lower:
                effect = "increases"
            elif "decrease" in actions_lower:
                effect = "decreases"
            elif "affect" in actions_lower:
                effect = "affects"

        # Insert claim
        claim_key = self._execute_scalar(
            """
            INSERT INTO kg.Claim (claim_type, strength_score, dataset_id, source_record_id, statement_json)
            OUTPUT INSERTED.claim_key
            VALUES ('DRUG_GENE_CTD', ?, ?, ?, ?)
            """,
            (score, dataset_id, f"{row.get('chemical_id')}_{row.get('gene_id')}", json.dumps(statement)),
        )

        if not claim_key:
            return None

        # Get node IDs (using cache)
        drug_node_id = self._get_node_id("kg.Drug", drug_key)
        gene_node_id = self._get_node_id("kg.Gene", gene_key)
        claim_node_id = self._get_node_id("kg.Claim", claim_key)

        if drug_node_id and claim_node_id:
            self._execute(
                "INSERT INTO kg.HasClaim ($from_id, $to_id, [role]) VALUES (?, ?, 'subject')",
                (drug_node_id, claim_node_id),
            )

        if gene_node_id and claim_node_id:
            self._execute(
                "INSERT INTO kg.ClaimGene ($from_id, $to_id, relation, effect) VALUES (?, ?, 'interacts', ?)",
                (claim_node_id, gene_node_id, effect),
            )

        return claim_key

    # ==================== Gene-Disease Loading ====================

    def _load_gene_disease(self, path: Path, dataset_id: int) -> dict[str, int]:
        """Load gene-disease associations as claims."""
        df = pl.read_parquet(path)
        total = len(df)
        console.print(f"  [yellow]Processing[/] {total:,} gene-disease associations...")

        # Pre-filter genes using cache
        gene_lookup = pl.DataFrame(
            {
                "gene_symbol_upper": list(self._gene_cache.keys()),
                "gene_key": list(self._gene_cache.values()),
            }
        )

        df_filtered = df.with_columns(
            [
                pl.col("gene_symbol").str.to_uppercase().alias("gene_symbol_upper"),
                pl.col("disease_name").str.to_lowercase().alias("disease_name_lower"),
            ]
        ).join(gene_lookup, on="gene_symbol_upper", how="inner")

        match_count = len(df_filtered)
        console.print(f"    [dim]Matched {match_count:,} / {total:,} gene rows ({100 * match_count / total:.1f}%)[/]")

        if match_count == 0:
            console.print("  [loaded] gene-disease: 0 claims")
            return {"gene_disease_ctd_claims": 0, "diseases_created": 0}

        claims_created = 0
        diseases_created = 0
        errors = 0

        with Progress() as progress:
            task = progress.add_task("[cyan]Loading gene-disease", total=match_count)

            for row in df_filtered.iter_rows(named=True):
                try:
                    gene_key = row["gene_key"]
                    disease_name = row["disease_name"]
                    disease_name_lower = row["disease_name_lower"]

                    if not disease_name:
                        progress.update(task, advance=1)
                        continue

                    # Find or create disease
                    disease_key = self._disease_cache.get(disease_name_lower)
                    if not disease_key:
                        disease_key = self._create_disease(disease_name, row.get("disease_id"))
                        if disease_key:
                            diseases_created += 1
                        else:
                            progress.update(task, advance=1)
                            continue

                    # Create claim
                    claim_key = self._create_gene_disease_claim(gene_key, disease_key, row, dataset_id)
                    if claim_key:
                        claims_created += 1

                except Exception as e:
                    if errors < 3:
                        console.print(f"\n  [warn] Error: {e}")
                    errors += 1

                progress.update(task, advance=1)

        console.print(f"    [green]✓[/] gene-disease: {claims_created:,} claims, {diseases_created:,} new diseases")
        return {"gene_disease_ctd_claims": claims_created, "diseases_created": diseases_created}

    def _create_gene_disease_claim(self, gene_key: int, disease_key: int, row: dict, dataset_id: int) -> int | None:
        """Create a gene-disease association claim."""
        direct_evidence = row.get("direct_evidence", "")
        pubmed_ids = row.get("pubmed_ids", "")

        statement = {
            "direct_evidence": direct_evidence,
            "disease_id": row.get("disease_id"),
            "gene_id": row.get("gene_id"),
            "pubmed_ids": pubmed_ids.split("|")[:20] if pubmed_ids else None,
        }

        # Score based on evidence type
        score = 0.8 if direct_evidence else 0.5
        pmid_count = len(pubmed_ids.split("|")) if pubmed_ids else 0
        score = min(score + (pmid_count * 0.05), 1.0)

        relation = "marker" if "marker" in (direct_evidence or "").lower() else "associated"

        claim_key = self._execute_scalar(
            """
            INSERT INTO kg.Claim (claim_type, strength_score, dataset_id, source_record_id, statement_json)
            OUTPUT INSERTED.claim_key
            VALUES ('GENE_DISEASE_CTD', ?, ?, ?, ?)
            """,
            (score, dataset_id, f"{row.get('gene_id')}_{row.get('disease_id')}", json.dumps(statement)),
        )

        if not claim_key:
            return None

        # Get node IDs
        gene_node_id = self._get_node_id("kg.Gene", gene_key)
        disease_node_id = self._get_node_id("kg.Disease", disease_key)
        claim_node_id = self._get_node_id("kg.Claim", claim_key)

        if gene_node_id and claim_node_id:
            self._execute(
                "INSERT INTO kg.HasClaim ($from_id, $to_id, [role]) VALUES (?, ?, 'subject')",
                (gene_node_id, claim_node_id),
            )

        if disease_node_id and claim_node_id:
            self._execute(
                "INSERT INTO kg.ClaimDisease ($from_id, $to_id, relation) VALUES (?, ?, ?)",
                (claim_node_id, disease_node_id, relation),
            )

        return claim_key

    # ==================== Chemical-Disease Loading ====================

    def _load_chem_disease(self, path: Path, dataset_id: int) -> dict[str, int]:
        """Load chemical-disease associations as claims."""
        df = pl.read_parquet(path)
        total = len(df)
        console.print(f"  [yellow]Processing[/] {total:,} chemical-disease associations...")

        # Pre-filter using drug cache
        drug_lookup = pl.DataFrame(
            {
                "chemical_name_lower": list(self._drug_cache.keys()),
                "drug_key": list(self._drug_cache.values()),
            }
        )

        df_filtered = df.with_columns(
            [
                pl.col("chemical_name").str.to_lowercase().alias("chemical_name_lower"),
                pl.col("disease_name").str.to_lowercase().alias("disease_name_lower"),
            ]
        ).join(drug_lookup, on="chemical_name_lower", how="inner")

        match_count = len(df_filtered)
        console.print(f"    [dim]Matched {match_count:,} / {total:,} drug rows ({100 * match_count / total:.1f}%)[/]")

        if match_count == 0:
            console.print("  [loaded] chem-disease: 0 claims")
            return {"chem_disease_claims": 0}

        claims_created = 0
        diseases_created = 0
        errors = 0

        with Progress() as progress:
            task = progress.add_task("[cyan]Loading chem-disease", total=match_count)

            for row in df_filtered.iter_rows(named=True):
                try:
                    drug_key = row["drug_key"]
                    disease_name = row["disease_name"]
                    disease_name_lower = row["disease_name_lower"]

                    if not disease_name:
                        progress.update(task, advance=1)
                        continue

                    # Find or create disease
                    disease_key = self._disease_cache.get(disease_name_lower)
                    if not disease_key:
                        disease_key = self._create_disease(disease_name, row.get("disease_id"))
                        if disease_key:
                            diseases_created += 1
                        else:
                            progress.update(task, advance=1)
                            continue

                    # Create claim
                    claim_key = self._create_chem_disease_claim(drug_key, disease_key, row, dataset_id)
                    if claim_key:
                        claims_created += 1

                except Exception as e:
                    if errors < 3:
                        console.print(f"\n  [warn] Error: {e}")
                    errors += 1

                progress.update(task, advance=1)

        console.print(f"    [green]✓[/] chem-disease: {claims_created:,} claims, {diseases_created:,} new diseases")
        return {"chem_disease_claims": claims_created}

    def _create_chem_disease_claim(self, drug_key: int, disease_key: int, row: dict, dataset_id: int) -> int | None:
        """Create a chemical-disease association claim."""
        direct_evidence = row.get("direct_evidence", "")
        pubmed_ids = row.get("pubmed_ids", "")

        statement = {
            "direct_evidence": direct_evidence,
            "disease_id": row.get("disease_id"),
            "chemical_id": row.get("chemical_id"),
            "pubmed_ids": pubmed_ids.split("|")[:20] if pubmed_ids else None,
        }

        # Score: therapeutic > marker
        if "therapeutic" in (direct_evidence or "").lower():
            score = 0.9
            relation = "therapeutic"
        else:
            score = 0.7
            relation = "marker"

        claim_key = self._execute_scalar(
            """
            INSERT INTO kg.Claim (claim_type, strength_score, dataset_id, source_record_id, statement_json)
            OUTPUT INSERTED.claim_key
            VALUES ('DRUG_DISEASE_CTD', ?, ?, ?, ?)
            """,
            (score, dataset_id, f"{row.get('chemical_id')}_{row.get('disease_id')}", json.dumps(statement)),
        )

        if not claim_key:
            return None

        # Get node IDs
        drug_node_id = self._get_node_id("kg.Drug", drug_key)
        disease_node_id = self._get_node_id("kg.Disease", disease_key)
        claim_node_id = self._get_node_id("kg.Claim", claim_key)

        if drug_node_id and claim_node_id:
            self._execute(
                "INSERT INTO kg.HasClaim ($from_id, $to_id, [role]) VALUES (?, ?, 'subject')",
                (drug_node_id, claim_node_id),
            )

        if disease_node_id and claim_node_id:
            self._execute(
                "INSERT INTO kg.ClaimDisease ($from_id, $to_id, relation) VALUES (?, ?, ?)",
                (claim_node_id, disease_node_id, relation),
            )

        return claim_key
