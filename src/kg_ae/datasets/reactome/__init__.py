"""
Reactome pathway database ETL module.

Reactome provides curated pathway data linking genes to biological pathways.
License: CC BY 4.0
"""

from kg_ae.datasets.reactome.download import ReactomeDownloader
from kg_ae.datasets.reactome.load import ReactomeLoader
from kg_ae.datasets.reactome.normalize import ReactomeNormalizer
from kg_ae.datasets.reactome.parse import ReactomeParser

__all__ = [
    "ReactomeDownloader",
    "ReactomeParser",
    "ReactomeNormalizer",
    "ReactomeLoader",
]
