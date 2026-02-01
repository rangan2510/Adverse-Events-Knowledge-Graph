"""
FAERS (FDA Adverse Event Reporting System) dataset module.

Computes disproportionality signals (PRR, ROR) from openFDA bulk data
to identify drug-adverse event associations.
"""

from kg_ae.datasets.faers.download import FAERSDownloader
from kg_ae.datasets.faers.parse import FAERSParser
from kg_ae.datasets.faers.load import FAERSLoader

__all__ = ["FAERSDownloader", "FAERSParser", "FAERSLoader"]
