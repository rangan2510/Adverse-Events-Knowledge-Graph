"""
Open Targets Platform ETL module.

Open Targets provides gene-disease associations from multiple sources.
License: CC0 (public domain)
"""

from kg_ae.datasets.opentargets.download import OpenTargetsDownloader
from kg_ae.datasets.opentargets.load import OpenTargetsLoader
from kg_ae.datasets.opentargets.normalize import OpenTargetsNormalizer
from kg_ae.datasets.opentargets.parse import OpenTargetsParser

__all__ = [
    "OpenTargetsDownloader",
    "OpenTargetsParser",
    "OpenTargetsNormalizer",
    "OpenTargetsLoader",
]
