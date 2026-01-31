"""
Dataset acquisition and parsing modules.

Each data source has its own submodule with:
- download.py: Fetch raw data + checksum verification
- parse.py: Raw → bronze (Parquet/CSV, source-shaped)
- normalize.py: Bronze → silver (canonical IDs applied)

Supported sources:
- sider: Drug-ADR pairs from drug labels (SIDER 4.1)
- drugcentral: Drug identity, targets, indications
- chembl: Bioactivity and drug-target relationships
- reactome: Pathway membership and hierarchy
- opentargets: Gene-disease associations
- openfda: FAERS adverse event reports and drug labeling
"""

SOURCES = [
    "sider",
    "drugcentral",
    "chembl",
    "reactome",
    "opentargets",
    "openfda",
]
