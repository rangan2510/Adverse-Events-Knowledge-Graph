"""
CTD dataset parser.

Parses CTD TSV.gz files to extract:
- Chemical-gene interactions
- Chemical-disease associations  
- Gene-disease associations

CTD files have commented header lines (starting with #), and the actual
column names are specified in a "# Fields:" comment. Data rows have no header.
"""

import gzip
from pathlib import Path

import polars as pl
from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseParser

console = Console()


class CTDParser(BaseParser):
    """Parse CTD TSV files to Parquet."""

    source_key = "ctd"

    def parse(self) -> dict[str, Path]:
        """
        Parse CTD raw files to bronze Parquet.

        Returns:
            Dict mapping table names to Parquet file paths
        """
        console.print("[bold cyan]CTD Parse[/]")
        results = {}

        # Parse chemical-gene interactions
        chem_gene_path = self._parse_chem_gene()
        if chem_gene_path:
            results["chem_gene"] = chem_gene_path

        # Parse chemical-disease associations
        chem_disease_path = self._parse_chem_disease()
        if chem_disease_path:
            results["chem_disease"] = chem_disease_path

        # Parse gene-disease associations
        gene_disease_path = self._parse_gene_disease()
        if gene_disease_path:
            results["gene_disease"] = gene_disease_path

        # Parse chemical vocabulary for ID mapping
        chemicals_path = self._parse_chemicals()
        if chemicals_path:
            results["chemicals"] = chemicals_path

        # Summary table
        table = Table(title="CTD Parse Summary", show_header=True)
        table.add_column("Table", style="cyan")
        table.add_column("Output", style="green")
        for name, path in results.items():
            table.add_row(name, path.name)
        console.print(table)

        return results

    def _count_header_lines(self, path: Path) -> int:
        """Count comment lines at start of CTD file."""
        count = 0
        opener = gzip.open if path.suffix == ".gz" else open
        mode = "rt" if path.suffix == ".gz" else "r"
        
        with opener(path, mode, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("#"):
                    count += 1
                else:
                    break
        return count

    def _parse_chem_gene(self) -> Path | None:
        """Parse chemical-gene interactions."""
        src = self.raw_dir / "CTD_chem_gene_ixns.tsv.gz"
        if not src.exists():
            console.print(f"  [dim][skip] {src.name} not found[/]")
            return None

        dest = self.bronze_dir / "chem_gene.parquet"
        skip = self._count_header_lines(src)

        # CTD chem_gene columns (from their header comment):
        # ChemicalName, ChemicalID, CasRN, GeneSymbol, GeneID, GeneForms,
        # Organism, OrganismID, Interaction, InteractionActions, PubMedIDs
        columns = [
            "chemical_name", "chemical_id", "cas_rn", "gene_symbol", "gene_id",
            "gene_forms", "organism", "organism_id", "interaction",
            "interaction_actions", "pubmed_ids"
        ]
        
        df = pl.read_csv(
            src,
            separator="\t",
            skip_rows=skip,
            has_header=False,  # CTD has no header row, just commented field names
            new_columns=columns,
            infer_schema_length=10000,
            ignore_errors=True,
        )

        # Filter to human only (taxon 9606)
        df = df.filter(pl.col("organism_id") == 9606)

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] chem_gene: {len(df):,} human interactions → {dest.name}")
        return dest

    def _parse_chem_disease(self) -> Path | None:
        """Parse chemical-disease associations."""
        src = self.raw_dir / "CTD_chemicals_diseases.tsv.gz"
        if not src.exists():
            console.print(f"  [dim][skip] {src.name} not found[/]")
            return None

        dest = self.bronze_dir / "chem_disease.parquet"
        skip = self._count_header_lines(src)

        # CTD chem_disease columns (from their header comment):
        # ChemicalName, ChemicalID, CasRN, DiseaseName, DiseaseID,
        # DirectEvidence, InferenceGeneSymbol, InferenceScore, OmimIDs, PubMedIDs
        columns = [
            "chemical_name", "chemical_id", "cas_rn", "disease_name", "disease_id",
            "direct_evidence", "inference_gene", "inference_score", "omim_ids", "pubmed_ids"
        ]
        
        df = pl.read_csv(
            src,
            separator="\t",
            skip_rows=skip,
            has_header=False,
            new_columns=columns,
            infer_schema_length=10000,
            ignore_errors=True,
        )

        # Keep only curated (direct evidence) associations for higher quality
        df_curated = df.filter(pl.col("direct_evidence").is_not_null())
        console.print(f"    [dim]chem_disease: {len(df_curated):,} curated / {len(df):,} total[/]")
        df = df_curated

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] chem_disease: {len(df):,} associations → {dest.name}")
        return dest

    def _parse_gene_disease(self) -> Path | None:
        """Parse gene-disease associations."""
        src = self.raw_dir / "CTD_genes_diseases.tsv.gz"
        if not src.exists():
            console.print(f"  [dim][skip] {src.name} not found[/]")
            return None

        dest = self.bronze_dir / "gene_disease.parquet"
        skip = self._count_header_lines(src)

        # CTD gene_disease columns:
        # GeneSymbol, GeneID, DiseaseName, DiseaseID, DirectEvidence,
        # InferenceChemicalName, InferenceScore, OmimIDs, PubMedIDs
        columns = [
            "gene_symbol", "gene_id", "disease_name", "disease_id",
            "direct_evidence", "inference_chemical", "inference_score",
            "omim_ids", "pubmed_ids"
        ]
        
        df = pl.read_csv(
            src,
            separator="\t",
            skip_rows=skip,
            has_header=False,
            new_columns=columns,
            infer_schema_length=10000,
            ignore_errors=True,
        )

        # Keep only curated associations (direct evidence exists)
        df_curated = df.filter(pl.col("direct_evidence").is_not_null())
        console.print(f"    [dim]gene_disease: {len(df_curated):,} curated / {len(df):,} total[/]")
        df = df_curated

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] gene_disease: {len(df):,} associations → {dest.name}")
        return dest

    def _parse_chemicals(self) -> Path | None:
        """Parse chemical vocabulary for ID cross-references."""
        src = self.raw_dir / "CTD_chemicals.tsv.gz"
        if not src.exists():
            console.print(f"  [dim][skip] {src.name} not found[/]")
            return None

        dest = self.bronze_dir / "chemicals.parquet"
        skip = self._count_header_lines(src)

        # CTD chemicals columns (from their header comment):
        # ChemicalName, ChemicalID, CasRN, Definition, ParentIDs,
        # TreeNumbers, ParentTreeNumbers, Synonyms, DrugBankIDs
        columns = [
            "chemical_name", "chemical_id", "cas_rn", "definition",
            "parent_ids", "tree_numbers", "parent_tree_numbers",
            "synonyms", "drugbank_ids"
        ]
        
        df = pl.read_csv(
            src,
            separator="\t",
            skip_rows=skip,
            has_header=False,
            new_columns=columns,
            infer_schema_length=10000,
            ignore_errors=True,
        )

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] chemicals: {len(df):,} entries → {dest.name}")
        return dest
