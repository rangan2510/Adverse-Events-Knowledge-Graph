"""CTD normalizer (bronze -> silver): chemical-gene and gene-disease relations."""

from pathlib import Path

import polars as pl
from rich.console import Console

from kg_ae.datasets.base import BaseNormalizer

console = Console()


class CtdNormalizer(BaseNormalizer):
    """Normalize CTD to silver drug-gene and gene-disease rows."""

    source_key = "ctd"

    def normalize(self) -> dict[str, Path]:
        console.print("[bold cyan]CTD Normalizer[/]")
        results: dict[str, Path] = {}

        chem_gene = self.bronze_dir / "chem_gene.parquet"
        if chem_gene.exists():
            df = pl.read_parquet(chem_gene)
            # Restrict to human and require interaction action.
            cg = df.filter(
                pl.col("organism").str.contains("(?i)homo sapiens").fill_null(False)
                if "organism" in df.columns
                else pl.lit(True)
            ).select(
                [
                    pl.col("chemical_name").str.to_lowercase().str.strip_chars().alias("drug_name"),
                    pl.col("gene_symbol").str.strip_chars().alias("gene_symbol"),
                    pl.col("interaction_actions").alias("interaction_actions"),
                ]
            ).filter(
                pl.col("drug_name").is_not_null() & pl.col("gene_symbol").is_not_null()
            ).unique(["drug_name", "gene_symbol"])
            out = self.silver_dir / "chem_gene.parquet"
            cg.write_parquet(out)
            results["chem_gene"] = out
            console.print(f"  [green][ok][/] chem_gene: {cg.height:,} rows")

        gene_disease = self.bronze_dir / "gene_disease.parquet"
        if gene_disease.exists():
            df = pl.read_parquet(gene_disease)
            # Prefer direct evidence rows; keep inference rows with a score.
            gd = df.select(
                [
                    pl.col("gene_symbol").str.strip_chars().alias("gene_symbol"),
                    pl.col("disease_name").str.strip_chars().alias("disease_label"),
                    pl.col("disease_id").alias("disease_id"),
                    pl.col("direct_evidence").alias("direct_evidence"),
                    pl.col("inference_score").cast(pl.Float64, strict=False).alias("inference_score"),
                ]
            ).filter(
                pl.col("gene_symbol").is_not_null() & pl.col("disease_label").is_not_null()
            ).unique(["gene_symbol", "disease_id"])
            out = self.silver_dir / "gene_disease.parquet"
            gd.write_parquet(out)
            results["gene_disease"] = out
            console.print(f"  [green][ok][/] gene_disease: {gd.height:,} rows")

        return results
