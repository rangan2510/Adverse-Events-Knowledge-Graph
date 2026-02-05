"""
ChEMBL dataset module.

Provides drug-target interactions with quantitative bioactivity data
(IC50, Ki, EC50, etc.) from the ChEMBL database.
"""

from kg_ae.datasets.chembl.download import ChEMBLDownloader
from kg_ae.datasets.chembl.load import ChEMBLLoader
from kg_ae.datasets.chembl.parse import ChEMBLParser

__all__ = ["ChEMBLDownloader", "ChEMBLParser", "ChEMBLLoader"]
