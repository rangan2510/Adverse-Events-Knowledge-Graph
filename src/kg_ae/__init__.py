"""
kg_ae: Drug-Adverse Event Knowledge Graph

A pharmacovigilance knowledge graph system that identifies potential drug-adverse event
relationships through mechanistic pathways:

    Drug → Gene/Protein → Pathway → Disease/Condition → Adverse Event

Core constraints:
- Local-first, pure Python (no live web retrieval at runtime)
- File-based JSON knowledge graph loaded in memory (no database server)
- LLM orchestration only (never invents edges)
"""

import warnings

# LangChain still imports pydantic.v1 internally, which emits a benign UserWarning
# on Python 3.14+. We pin LangChain via uv.lock and do not use the v1 shim
# ourselves, so the warning is noise. Suppress it at import time.
warnings.filterwarnings(
    "ignore",
    message=r".*Pydantic V1 functionality isn't compatible with Python 3\.14.*",
    category=UserWarning,
)

__version__ = "0.1.0"
