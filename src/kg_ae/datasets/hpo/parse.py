"""
HPO (Human Phenotype Ontology) parser.

Parses HPO phenotype-disease and gene-phenotype annotation files.
"""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.config import settings
from kg_ae.datasets.base import BaseParser

console = Console()


class HPOParser(BaseParser):
    """Parse HPO annotation files."""

    source_key = "hpo"

    def __init__(self):
        super().__init__()
        self.raw_dir = settings.raw_dir / self.source_key
        self.bronze_dir = settings.bronze_dir / self.source_key
        self.bronze_dir.mkdir(parents=True, exist_ok=True)

    def parse(self) -> dict[str, Path]:
        """
        Parse HPO annotation files.
        
        Returns:
            Dict mapping file types to output paths
        """
        console.print("[bold cyan]HPO Parser[/]")
        
        parsed = {}
        
        # Parse genes_to_phenotype (gene → phenotype associations)
        genes_path = self.raw_dir / "genes_to_phenotype.txt"
        if genes_path.exists():
            result = self._parse_genes_to_phenotype(genes_path)
            if result:
                parsed["genes_to_phenotype"] = result
        
        # Parse phenotype_to_genes (phenotype → gene associations)
        pheno_genes_path = self.raw_dir / "phenotype_to_genes.txt"
        if pheno_genes_path.exists():
            result = self._parse_phenotype_to_genes(pheno_genes_path)
            if result:
                parsed["phenotype_to_genes"] = result
        
        # Parse phenotype.hpoa (disease → phenotype annotations)
        phenotype_path = self.raw_dir / "phenotype.hpoa"
        if phenotype_path.exists():
            result = self._parse_phenotype_hpoa(phenotype_path)
            if result:
                parsed["disease_phenotype"] = result
        
        if not parsed:
            console.print("  [skip] No HPO data found in raw/")
        
        return parsed

    def _parse_genes_to_phenotype(self, path: Path) -> Path | None:
        """Parse genes_to_phenotype.txt - gene-phenotype associations."""
        console.print(f"  Parsing {path.name}...")
        
        try:
            # Format: gene_id\tgene_symbol\thpo_id\thpo_name\tfrequency...
            # Find header line (starts with #)
            with open(path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if line.startswith("#") and "gene" in line.lower():
                        header_line = i
                        break
                else:
                    header_line = 0
            
            df = pl.read_csv(
                path,
                separator="\t",
                skip_rows=header_line,
                comment_prefix="#",
                infer_schema_length=10000,
                ignore_errors=True,
            )
            
            # Normalize column names
            col_map = {
                c: c.lower().replace(" ", "_").replace("-", "_").replace("<", "").replace(">", "")
                for c in df.columns
            }
            df = df.rename(col_map)
            
            console.print(f"    Columns: {df.columns}")
            console.print(f"    Raw rows: {len(df):,}")
            
            # Filter to human genes (NCBI gene IDs)
            if "ncbi_gene_id" in df.columns:
                df = df.filter(pl.col("ncbi_gene_id").is_not_null())
            
            output_path = self.bronze_dir / "genes_to_phenotype.parquet"
            df.write_parquet(output_path)
            console.print(f"    genes_to_phenotype: {len(df):,} rows → genes_to_phenotype.parquet")
            
            return output_path
            
        except Exception as e:
            console.print(f"    [warn] Parse error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _parse_phenotype_to_genes(self, path: Path) -> Path | None:
        """Parse phenotype_to_genes.txt - phenotype-gene associations."""
        console.print(f"  Parsing {path.name}...")
        
        try:
            df = pl.read_csv(
                path,
                separator="\t",
                comment_prefix="#",
                infer_schema_length=10000,
                ignore_errors=True,
            )
            
            # Normalize column names
            col_map = {
                c: c.lower().replace(" ", "_").replace("-", "_").replace("<", "").replace(">", "")
                for c in df.columns
            }
            df = df.rename(col_map)
            
            console.print(f"    Columns: {df.columns}")
            console.print(f"    Raw rows: {len(df):,}")
            
            output_path = self.bronze_dir / "phenotype_to_genes.parquet"
            df.write_parquet(output_path)
            console.print(f"    phenotype_to_genes: {len(df):,} rows → phenotype_to_genes.parquet")
            
            return output_path
            
        except Exception as e:
            console.print(f"    [warn] Parse error: {e}")
            return None

    def _parse_phenotype_hpoa(self, path: Path) -> Path | None:
        """Parse phenotype.hpoa - disease-phenotype annotations."""
        console.print(f"  Parsing {path.name}...")
        
        try:
            # Skip comment lines at the start
            with open(path, encoding="utf-8") as f:
                skip_rows = 0
                for line in f:
                    if line.startswith("#"):
                        skip_rows += 1
                    else:
                        break
            
            df = pl.read_csv(
                path,
                separator="\t",
                skip_rows=skip_rows,
                infer_schema_length=10000,
                ignore_errors=True,
            )
            
            # Normalize column names
            df = df.rename({c: c.lower().replace(" ", "_").replace("-", "_") for c in df.columns})
            
            console.print(f"    Columns: {df.columns}")
            console.print(f"    Raw rows: {len(df):,}")
            
            # Filter to OMIM/ORPHA diseases (skip generic entries)
            if "database_id" in df.columns:
                df = df.filter(
                    pl.col("database_id").str.starts_with("OMIM:") |
                    pl.col("database_id").str.starts_with("ORPHA:")
                )
                console.print(f"    After OMIM/ORPHA filter: {len(df):,}")
            
            output_path = self.bronze_dir / "disease_phenotype.parquet"
            df.write_parquet(output_path)
            console.print(f"    disease_phenotype: {len(df):,} rows → disease_phenotype.parquet")
            
            return output_path
            
        except Exception as e:
            console.print(f"    [warn] Parse error: {e}")
            import traceback
            traceback.print_exc()
            return None
