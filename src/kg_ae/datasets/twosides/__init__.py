"""
TWOSIDES dataset: drug-drug interaction adverse-event signals.

Source: https://nsides.io (Tatonetti Lab), TWOSIDES.csv.gz
License: none stated (treated as research-only)
Coverage: 3,300+ drugs, 63,000+ pairs (FAERS-mined disproportionality)

TWOSIDES is the only comprehensive open drug-drug-effect resource. It powers
the polypharmacy capability: (drug A + drug B) -> adverse event, modelled in the
graph via a DrugCombination node. Drugs join to existing drug nodes by name;
the AE joins by MedDRA label.
"""

from kg_ae.datasets.twosides.download import TwosidesDownloader
from kg_ae.datasets.twosides.normalize import TwosidesNormalizer
from kg_ae.datasets.twosides.parse import TwosidesParser

__all__ = ["TwosidesDownloader", "TwosidesParser", "TwosidesNormalizer"]
