"""
BindingDB dataset: measured drug-target binding affinities.

Source: https://www.bindingdb.org
License: CC BY 4.0 (curated data) - commercial use OK
Version: monthly (e.g. BindingDB_All_202606)

BindingDB provides quantitative protein-ligand binding measurements
(Ki, Kd, IC50, EC50). We use it to add weighted, quantitative drug -> gene
target edges that complement DrugCentral's curated mechanism-of-action edges.
Targets join to genes via UniProt; ligands join to drugs by name.
"""

from kg_ae.datasets.bindingdb.download import BindingdbDownloader
from kg_ae.datasets.bindingdb.normalize import BindingdbNormalizer
from kg_ae.datasets.bindingdb.parse import BindingdbParser

__all__ = ["BindingdbDownloader", "BindingdbParser", "BindingdbNormalizer"]
