"""
openFDA dataset parser.

Parses FDA drug labeling JSON files to extract:
- Drug identifiers (NDC, brand names, generic names)
- Adverse reaction sections from labels
- Warnings and contraindications
"""

import json
import re
import zipfile
from pathlib import Path

import polars as pl
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from kg_ae.datasets.base import BaseParser

console = Console()


class OpenFDAParser(BaseParser):
    """Parse openFDA JSON files to Parquet."""

    source_key = "openfda"

    def parse(self) -> dict[str, Path]:
        """
        Parse openFDA raw files to bronze Parquet.

        Returns:
            Dict mapping table names to Parquet file paths
        """
        console.print("[bold cyan]openFDA Parser[/]")
        results = {}

        # Parse drug labels
        labels_path = self._parse_labels()
        if labels_path:
            results["labels"] = labels_path

        # Parse NDC
        ndc_path = self._parse_ndc()
        if ndc_path:
            results["ndc"] = ndc_path

        # Summary table
        if results:
            table = Table(title="openFDA Parse Summary", show_header=True)
            table.add_column("Table", style="cyan")
            table.add_column("File", style="dim")
            for name, path in results.items():
                table.add_row(name, path.name)
            console.print(table)

        return results

    def _parse_labels(self) -> Path | None:
        """Parse drug label JSON files to extract AE sections."""
        label_dir = self.raw_dir / "label"
        if not label_dir.exists():
            console.print(f"  [dim][skip] {label_dir.name} not found[/]")
            return None

        zip_files = list(label_dir.glob("*.zip"))
        if not zip_files:
            console.print("  [dim][skip] No label zip files found[/]")
            return None

        dest = self.bronze_dir / "labels.parquet"
        records = []

        console.print(f"  Processing {len(zip_files)} label files...")

        with Progress() as progress:
            task = progress.add_task("[cyan]Parsing labels", total=len(zip_files))

            for zip_path in zip_files:
                try:
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        for name in zf.namelist():
                            if name.endswith(".json"):
                                with zf.open(name) as f:
                                    data = json.load(f)
                                    for result in data.get("results", []):
                                        record = self._extract_label_record(result)
                                        if record:
                                            records.append(record)
                except Exception as e:
                    console.print(f"\n  [yellow][warn][/] Error processing {zip_path.name}: {e}")

                progress.update(task, advance=1)

        if not records:
            console.print("  [yellow][warn][/] No label records extracted")
            return None

        df = pl.DataFrame(records)

        # Deduplicate by set_id (SPL ID), keeping most recent
        df = df.sort("effective_time", descending=True, nulls_last=True)
        df = df.unique(subset=["set_id"], keep="first")

        df.write_parquet(dest)
        console.print(f"    [green]✓[/] labels: {len(df):,} unique labels")
        return dest

    def _extract_label_record(self, result: dict) -> dict | None:
        """Extract relevant fields from a label result."""
        openfda = result.get("openfda", {})

        # Get drug identifiers
        brand_names = openfda.get("brand_name", [])
        generic_names = openfda.get("generic_name", [])
        rxcui = openfda.get("rxcui", [])
        spl_id = openfda.get("spl_id", [])
        unii = openfda.get("unii", [])

        # Skip if no useful identifiers
        if not brand_names and not generic_names:
            return None

        # Get text sections
        adverse_reactions = self._clean_section(result.get("adverse_reactions", []))
        warnings = self._clean_section(result.get("warnings", []))
        contraindications = self._clean_section(result.get("contraindications", []))
        boxed_warning = self._clean_section(result.get("boxed_warning", []))
        drug_interactions = self._clean_section(result.get("drug_interactions", []))

        # Skip if no safety info
        if not any([adverse_reactions, warnings, contraindications, boxed_warning]):
            return None

        return {
            "set_id": result.get("set_id"),
            "spl_id": spl_id[0] if spl_id else None,
            "effective_time": result.get("effective_time"),
            "brand_name": brand_names[0] if brand_names else None,
            "brand_names_json": json.dumps(brand_names) if brand_names else None,
            "generic_name": generic_names[0] if generic_names else None,
            "generic_names_json": json.dumps(generic_names) if generic_names else None,
            "rxcui_json": json.dumps(rxcui) if rxcui else None,
            "unii_json": json.dumps(unii) if unii else None,
            "adverse_reactions": adverse_reactions,
            "warnings": warnings,
            "contraindications": contraindications,
            "boxed_warning": boxed_warning,
            "drug_interactions": drug_interactions,
        }

    def _clean_section(self, sections: list[str] | str | None) -> str | None:
        """Clean and join section text."""
        if not sections:
            return None
        if isinstance(sections, str):
            sections = [sections]

        # Join sections
        text = " ".join(sections)

        # Remove excessive whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Truncate very long sections (keep first 10KB)
        if len(text) > 10000:
            text = text[:10000] + "..."

        return text if text else None

    def _parse_ndc(self) -> Path | None:
        """Parse NDC (National Drug Code) JSON to Parquet."""
        ndc_dir = self.raw_dir / "ndc"
        if not ndc_dir.exists():
            console.print(f"  [dim][skip] {ndc_dir.name} not found[/]")
            return None

        zip_files = list(ndc_dir.glob("*.zip"))
        if not zip_files:
            console.print("  [dim][skip] No NDC zip files found[/]")
            return None

        dest = self.bronze_dir / "ndc.parquet"
        records = []

        console.print("  Processing NDC data...")

        for zip_path in zip_files:
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    for name in zf.namelist():
                        if name.endswith(".json"):
                            with zf.open(name) as f:
                                data = json.load(f)
                                for result in data.get("results", []):
                                    record = self._extract_ndc_record(result)
                                    if record:
                                        records.append(record)
            except Exception as e:
                console.print(f"  [yellow][warn][/] Error processing {zip_path.name}: {e}")

        if not records:
            console.print("  [yellow][warn][/] No NDC records extracted")
            return None

        df = pl.DataFrame(records)
        df.write_parquet(dest)
        console.print(f"    [green]✓[/] ndc: {len(df):,} products")
        return dest

    def _extract_ndc_record(self, result: dict) -> dict | None:
        """Extract relevant fields from an NDC result."""
        product_ndc = result.get("product_ndc")
        if not product_ndc:
            return None

        openfda = result.get("openfda", {})

        return {
            "product_ndc": product_ndc,
            "generic_name": result.get("generic_name"),
            "brand_name": result.get("brand_name"),
            "labeler_name": result.get("labeler_name"),
            "dosage_form": result.get("dosage_form"),
            "route": json.dumps(result.get("route", [])) if result.get("route") else None,
            "product_type": result.get("product_type"),
            "rxcui_json": json.dumps(openfda.get("rxcui", [])) if openfda.get("rxcui") else None,
            "unii_json": json.dumps(openfda.get("unii", [])) if openfda.get("unii") else None,
            "spl_id": openfda.get("spl_id", [None])[0],
        }
