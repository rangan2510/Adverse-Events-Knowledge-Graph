"""
STRING database parser.

Parses STRING protein-protein interaction files to Parquet.
Maps STRING protein IDs to gene symbols using aliases.
"""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.config import settings

console = Console()


class STRINGParser:
    """Parse STRING TSV files to Parquet."""

    source_key = "string"

    def __init__(self):
        self.raw_dir = settings.raw_dir / self.source_key
        self.bronze_dir = settings.bronze_dir / self.source_key
        self.bronze_dir.mkdir(parents=True, exist_ok=True)

    def parse(self) -> dict[str, Path]:
        """
        Parse STRING raw files to bronze Parquet.

        Returns:
            Dict mapping table names to Parquet file paths
        """
        results = {}

        # First, build protein ID to gene symbol mapping
        alias_path = self._parse_aliases()
        if alias_path:
            results["aliases"] = alias_path

        # Then parse protein links with gene symbol mapping
        links_path = self._parse_links()
        if links_path:
            results["links"] = links_path

        return results

    def _parse_aliases(self) -> Path | None:
        """Parse protein aliases to build ID mapping."""
        # Try different filename patterns
        src_patterns = [
            self.raw_dir / "9606.protein.aliases.v12.0.txt.gz",
            self.raw_dir / "9606.protein.aliases.v11.5.txt.gz",
        ]
        
        src = None
        for pattern in src_patterns:
            if pattern.exists():
                src = pattern
                break
        
        if not src:
            console.print("  [skip] protein.aliases not found")
            return None

        dest = self.bronze_dir / "aliases.parquet"

        console.print(f"  Parsing {src.name}...")

        # STRING aliases format: protein_id, alias, source
        # We want to extract gene symbols (from Ensembl_gene, BioMart_HUGO, etc.)
        df = pl.read_csv(
            src,
            separator="\t",
            has_header=True,
            new_columns=["string_id", "alias", "source"],
            infer_schema_length=10000,
        )

        # Filter to useful alias sources for gene symbol mapping
        # Priority: BioMart_HUGO > Ensembl_gene > BLAST_UniProt_GN
        symbol_sources = [
            "BioMart_HUGO",
            "Ensembl_gene", 
            "BLAST_UniProt_GN",
            "Ensembl_HGNC_symbol",
        ]
        
        df_symbols = df.filter(pl.col("source").is_in(symbol_sources))
        
        # Keep best alias per protein (prefer HUGO)
        df_best = (
            df_symbols
            .with_columns([
                pl.when(pl.col("source") == "BioMart_HUGO").then(1)
                .when(pl.col("source") == "Ensembl_HGNC_symbol").then(2)
                .when(pl.col("source") == "Ensembl_gene").then(3)
                .otherwise(4)
                .alias("priority")
            ])
            .sort("priority")
            .group_by("string_id")
            .first()
            .select(["string_id", "alias"])
            .rename({"alias": "gene_symbol"})
        )

        df_best.write_parquet(dest)
        console.print(f"  [parsed] aliases: {len(df_best):,} protein→symbol mappings → {dest.name}")
        return dest

    def _parse_links(self) -> Path | None:
        """Parse protein-protein interaction links."""
        src_patterns = [
            self.raw_dir / "9606.protein.links.v12.0.txt.gz",
            self.raw_dir / "9606.protein.links.v11.5.txt.gz",
        ]
        
        src = None
        for pattern in src_patterns:
            if pattern.exists():
                src = pattern
                break
        
        if not src:
            console.print("  [skip] protein.links not found")
            return None

        dest = self.bronze_dir / "links.parquet"
        alias_path = self.bronze_dir / "aliases.parquet"

        console.print(f"  Parsing {src.name}...")

        # STRING links format: protein1 protein2 combined_score
        # Space-separated (not tab!)
        df = pl.read_csv(
            src,
            separator=" ",
            has_header=True,
            infer_schema_length=10000,
        )

        total = len(df)
        console.print(f"    Raw interactions: {total:,}")

        # Filter to high-confidence interactions (score >= 700)
        df = df.filter(pl.col("combined_score") >= 700)
        console.print(f"    High-confidence (≥700): {len(df):,}")

        # Load alias mapping if available
        if alias_path.exists():
            aliases = pl.read_parquet(alias_path)
            
            # Join to get gene symbols for both proteins
            df = (
                df
                .join(
                    aliases.rename({"string_id": "protein1", "gene_symbol": "gene1"}),
                    on="protein1",
                    how="left"
                )
                .join(
                    aliases.rename({"string_id": "protein2", "gene_symbol": "gene2"}),
                    on="protein2", 
                    how="left"
                )
            )

            # Keep only rows where both proteins have gene symbols
            df_mapped = df.filter(
                pl.col("gene1").is_not_null() & pl.col("gene2").is_not_null()
            )
            console.print(f"    With gene symbols: {len(df_mapped):,}")
            df = df_mapped

        df.write_parquet(dest)
        console.print(f"  [parsed] links: {len(df):,} interactions → {dest.name}")
        return dest
