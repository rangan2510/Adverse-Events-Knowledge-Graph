"""
SIDER dataset parser.

Parses raw SIDER TSV files to bronze Parquet format.
"""

from pathlib import Path

import polars as pl
from rich.console import Console
from rich.table import Table

from kg_ae.datasets.base import BaseParser

console = Console()


class SiderParser(BaseParser):
    """Parse SIDER TSV files to Parquet."""

    source_key = "sider"

    def parse(self) -> dict[str, Path]:
        """
        Parse SIDER raw files to bronze Parquet.

        Returns:
            Dict mapping table names to Parquet file paths
        """
        console.print("[bold cyan]SIDER Parser[/]")
        results = {}

        # Parse drug names
        drug_names_path = self._parse_drug_names()
        if drug_names_path:
            results["drug_names"] = drug_names_path

        # Parse side effects
        side_effects_path = self._parse_side_effects()
        if side_effects_path:
            results["side_effects"] = side_effects_path

        # Parse frequencies
        freq_path = self._parse_frequencies()
        if freq_path:
            results["frequencies"] = freq_path

        # Summary table
        if results:
            table = Table(title="SIDER Parse Summary", show_header=True)
            table.add_column("Table", style="cyan")
            table.add_column("File", style="dim")
            for name, path in results.items():
                table.add_row(name, path.name)
            console.print(table)

        return results

    def _parse_drug_names(self) -> Path | None:
        """Parse drug_names.tsv to Parquet."""
        src = self.raw_dir / "drug_names.tsv"
        if not src.exists():
            return None

        dest = self.bronze_dir / "drug_names.parquet"

        # drug_names.tsv has no header, columns are:
        # STITCH_ID, drug_name
        df = pl.read_csv(
            src,
            separator="\t",
            has_header=False,
            new_columns=["stitch_id", "drug_name"],
        )

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] drug_names: {len(df):,} rows")
        return dest

    def _parse_side_effects(self) -> Path | None:
        """Parse meddra_all_se.tsv.gz to Parquet."""
        src = self.raw_dir / "meddra_all_se.tsv.gz"
        if not src.exists():
            return None

        dest = self.bronze_dir / "side_effects.parquet"

        # meddra_all_se.tsv columns:
        # STITCH_ID (flat), STITCH_ID (stereo), UMLS_CUI (label), MedDRA_type,
        # UMLS_CUI (MedDRA), side_effect_name
        df = pl.read_csv(
            src,
            separator="\t",
            has_header=False,
            new_columns=[
                "stitch_id_flat",
                "stitch_id_stereo",
                "umls_cui_label",
                "meddra_type",
                "umls_cui_meddra",
                "side_effect_name",
            ],
        )

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] side_effects: {len(df):,} rows")
        return dest

    def _parse_frequencies(self) -> Path | None:
        """Parse meddra_freq.tsv.gz to Parquet."""
        src = self.raw_dir / "meddra_freq.tsv.gz"
        if not src.exists():
            return None

        dest = self.bronze_dir / "frequencies.parquet"

        # meddra_freq.tsv columns:
        # STITCH_ID (flat), STITCH_ID (stereo), UMLS_CUI (label), placebo,
        # frequency, frequency_lower, frequency_upper, MedDRA_type,
        # UMLS_CUI (MedDRA), side_effect_name
        df = pl.read_csv(
            src,
            separator="\t",
            has_header=False,
            new_columns=[
                "stitch_id_flat",
                "stitch_id_stereo",
                "umls_cui_label",
                "placebo",
                "frequency",
                "frequency_lower",
                "frequency_upper",
                "meddra_type",
                "umls_cui_meddra",
                "side_effect_name",
            ],
        )

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] frequencies: {len(df):,} rows")
        return dest
