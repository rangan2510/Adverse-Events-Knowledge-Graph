"""
SIDER dataset: Drug-ADR pairs from drug labels.

Source: http://sideeffects.embl.de/
License: CC BY-NC-SA (non-commercial use)
Version: 4.1 (October 2015)

Key files:
- meddra_all_se.tsv.gz: All drug-side effect pairs with MedDRA terms
- drug_names.tsv: Drug name mappings (STITCH ID → name)
"""

from kg_ae.datasets.sider.download import SiderDownloader
from kg_ae.datasets.sider.load import SiderLoader
from kg_ae.datasets.sider.normalize import SiderNormalizer
from kg_ae.datasets.sider.parse import SiderParser

__all__ = ["SiderDownloader", "SiderParser", "SiderNormalizer", "SiderLoader"]
