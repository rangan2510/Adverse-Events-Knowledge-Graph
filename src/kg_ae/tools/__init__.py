"""
LLM tool functions for knowledge graph queries.

These are the deterministic tools that the LLM orchestrator can call.
All tools return structured data (never prose).
"""

from kg_ae.tools.resolve import (
    resolve_drugs,
    resolve_genes,
    resolve_diseases,
    ResolvedEntity,
)
from kg_ae.tools.mechanism import (
    get_drug_targets,
    get_gene_pathways,
    get_gene_diseases,
    expand_mechanism,
    expand_gene_context,
    DrugTarget,
    GenePathway,
    GeneDisease,
)
from kg_ae.tools.adverse_events import (
    get_drug_adverse_events,
    get_drug_profile,
    DrugAdverseEvent,
)
from kg_ae.tools.subgraph import (
    build_subgraph,
    score_edges,
    Subgraph,
    Node,
    Edge,
)
from kg_ae.tools.paths import (
    find_drug_to_ae_paths,
    explain_paths,
    MechanisticPath,
    PathStep,
)

__all__ = [
    # Resolve
    "resolve_drugs",
    "resolve_genes",
    "resolve_diseases",
    "ResolvedEntity",
    # Mechanism
    "get_drug_targets",
    "get_gene_pathways",
    "get_gene_diseases",
    "expand_mechanism",
    "expand_gene_context",
    "DrugTarget",
    "GenePathway",
    "GeneDisease",
    # Adverse Events
    "get_drug_adverse_events",
    "get_drug_profile",
    "DrugAdverseEvent",
    # Subgraph
    "build_subgraph",
    "score_edges",
    "Subgraph",
    "Node",
    "Edge",
    # Paths
    "find_drug_to_ae_paths",
    "explain_paths",
    "MechanisticPath",
    "PathStep",
]
