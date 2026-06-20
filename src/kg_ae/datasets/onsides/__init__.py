"""
OnSIDES dataset: adverse drug events extracted from drug labels.

Source: https://github.com/tatonetti-lab/onsides (Tatonetti Lab)
License: MIT (commercial use OK)
Version: v3.1.1 (April 2026), quarterly updates

OnSIDES is the modern, higher-recall successor to SIDER. It extracts drug-ADE
pairs from structured product labels (US/EU/UK/JP) using a fine-tuned
PubMedBERT model, and maps drugs to RxNorm ingredients and effects to MedDRA
preferred terms. Kept alongside SIDER as independent evidence.
"""

from kg_ae.datasets.onsides.download import OnsidesDownloader
from kg_ae.datasets.onsides.normalize import OnsidesNormalizer
from kg_ae.datasets.onsides.parse import OnsidesParser

__all__ = ["OnsidesDownloader", "OnsidesParser", "OnsidesNormalizer"]
