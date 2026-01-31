"""
Reactome dataset parser.

Parses raw Reactome files to bronze Parquet format.
"""

from pathlib import Path

import polars as pl

from kg_ae.datasets.base import BaseParser


class ReactomeParser(BaseParser):
    """Parse Reactome TSV files to Parquet."""

    source_key = "reactome"

    def parse(self) -> dict[str, Path]:
        """
        Parse Reactome raw files to bronze Parquet.

        Returns:
            Dict mapping table names to Parquet file paths
        """
        results = {}

        # Parse pathways (ID -> name)
        pathways_path = self._parse_pathways()
        if pathways_path:
            results["pathways"] = pathways_path

        # Parse pathway hierarchy
        hierarchy_path = self._parse_hierarchy()
        if hierarchy_path:
            results["hierarchy"] = hierarchy_path

        # Parse UniProt to pathway mapping
        uniprot_path = self._parse_uniprot_mapping()
        if uniprot_path:
            results["uniprot_pathways"] = uniprot_path

        # Parse Ensembl to pathway mapping
        ensembl_path = self._parse_ensembl_mapping()
        if ensembl_path:
            results["ensembl_pathways"] = ensembl_path

        return results

    def _parse_pathways(self) -> Path | None:
        """Parse ReactomePathways.txt to Parquet."""
        src = self.raw_dir / "ReactomePathways.txt"
        if not src.exists():
            return None

        dest = self.bronze_dir / "pathways.parquet"

        # Format: pathway_id \t pathway_name \t species
        df = pl.read_csv(
            src,
            separator="\t",
            has_header=False,
            new_columns=["pathway_id", "pathway_name", "species"],
        )

        df.write_parquet(dest)
        print(f"  [parsed] pathways: {len(df):,} rows → {dest.name}")
        return dest

    def _parse_hierarchy(self) -> Path | None:
        """Parse ReactomePathwaysRelation.txt to Parquet."""
        src = self.raw_dir / "ReactomePathwaysRelation.txt"
        if not src.exists():
            return None

        dest = self.bronze_dir / "hierarchy.parquet"

        # Format: parent_pathway_id \t child_pathway_id
        df = pl.read_csv(
            src,
            separator="\t",
            has_header=False,
            new_columns=["parent_pathway_id", "child_pathway_id"],
        )

        df.write_parquet(dest)
        print(f"  [parsed] hierarchy: {len(df):,} rows → {dest.name}")
        return dest

    def _parse_uniprot_mapping(self) -> Path | None:
        """Parse UniProt2Reactome.txt to Parquet."""
        src = self.raw_dir / "UniProt2Reactome.txt"
        if not src.exists():
            return None

        dest = self.bronze_dir / "uniprot_pathways.parquet"

        # Format: uniprot_id \t pathway_id \t url \t pathway_name \t evidence_code \t species
        df = pl.read_csv(
            src,
            separator="\t",
            has_header=False,
            new_columns=[
                "uniprot_id",
                "pathway_id",
                "url",
                "pathway_name",
                "evidence_code",
                "species",
            ],
        )

        df.write_parquet(dest)
        print(f"  [parsed] uniprot_pathways: {len(df):,} rows → {dest.name}")
        return dest

    def _parse_ensembl_mapping(self) -> Path | None:
        """Parse Ensembl2Reactome.txt to Parquet."""
        src = self.raw_dir / "Ensembl2Reactome.txt"
        if not src.exists():
            return None

        dest = self.bronze_dir / "ensembl_pathways.parquet"

        # Format: ensembl_id \t pathway_id \t url \t pathway_name \t evidence_code \t species
        df = pl.read_csv(
            src,
            separator="\t",
            has_header=False,
            new_columns=[
                "ensembl_id",
                "pathway_id",
                "url",
                "pathway_name",
                "evidence_code",
                "species",
            ],
        )

        df.write_parquet(dest)
        print(f"  [parsed] ensembl_pathways: {len(df):,} rows → {dest.name}")
        return dest
