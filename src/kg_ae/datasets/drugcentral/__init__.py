"""
DrugCentral dataset: Drug identity, targets, and indications.

Source: https://drugcentral.org/
License: CC BY-SA 4.0

Key files:
- drug.target.interaction.tsv.gz: Drug-target interactions
- structures.smiles.tsv: Drug structures with IDs (DrugCentral, CAS, InChI)
- FDA+EMA+PMDA_Approved.csv: Approved drug list with cross-references
"""

from kg_ae.datasets.drugcentral.download import DrugCentralDownloader
from kg_ae.datasets.drugcentral.load import DrugCentralLoader
from kg_ae.datasets.drugcentral.normalize import DrugCentralNormalizer
from kg_ae.datasets.drugcentral.parse import DrugCentralParser

__all__ = [
    "DrugCentralDownloader",
    "DrugCentralParser",
    "DrugCentralNormalizer",
    "DrugCentralLoader",
]
