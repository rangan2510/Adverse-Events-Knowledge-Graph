"""
kg_ae: Drug-Adverse Event Knowledge Graph

A pharmacovigilance knowledge graph system that identifies potential drug-adverse event
relationships through mechanistic pathways:

    Drug → Gene/Protein → Pathway → Disease/Condition → Adverse Event

Core constraints:
- Local-first, pure Python (no live web retrieval at runtime)
- SQL Server 2025 backend with graph tables + JSON + vector embeddings
- LLM orchestration only (never invents edges)
"""

__version__ = "0.1.0"
