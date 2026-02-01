"""
LLM tool functions for knowledge graph queries.

These are the deterministic tools that the LLM orchestrator can call.
All tools return structured data (never prose).
"""

from kg_ae.tools.resolve import (
    resolve_drugs,
    resolve_genes,
    resolve_diseases,
    resolve_adverse_events,
    ResolvedEntity,
)
from kg_ae.tools.mechanism import (
    get_drug_targets,
    get_gene_pathways,
    get_gene_diseases,
    get_disease_genes,
    get_gene_interactors,
    expand_mechanism,
    expand_gene_context,
    DrugTarget,
    GenePathway,
    GeneDisease,
    DiseaseGene,
    GeneInteractor,
)
from kg_ae.tools.adverse_events import (
    get_drug_adverse_events,
    get_drug_profile,
    get_drug_label_sections,
    get_drug_faers_signals,
    DrugAdverseEvent,
    DrugLabelSection,
    FAERSSignal,
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
    score_paths,
    score_paths_with_evidence,
    MechanisticPath,
    PathStep,
    ScoringPolicy,
)
from kg_ae.tools.evidence import (
    get_claim_evidence,
    get_entity_claims,
    ClaimEvidence,
    ClaimDetail,
)

__all__ = [
    # Resolve
    "resolve_drugs",
    "resolve_genes",
    "resolve_diseases",
    "resolve_adverse_events",
    "ResolvedEntity",
    # Mechanism
    "get_drug_targets",
    "get_gene_pathways",
    "get_gene_diseases",
    "get_disease_genes",
    "get_gene_interactors",
    "expand_mechanism",
    "expand_gene_context",
    "DrugTarget",
    "GenePathway",
    "GeneDisease",
    "DiseaseGene",
    "GeneInteractor",
    # Adverse Events
    "get_drug_adverse_events",
    "get_drug_profile",
    "get_drug_label_sections",
    "get_drug_faers_signals",
    "DrugAdverseEvent",
    "DrugLabelSection",
    "FAERSSignal",
    # Subgraph
    "build_subgraph",
    "score_edges",
    "Subgraph",
    "Node",
    "Edge",
    # Paths
    "find_drug_to_ae_paths",
    "explain_paths",
    "score_paths",
    "score_paths_with_evidence",
    "MechanisticPath",
    "PathStep",
    "ScoringPolicy",
    # Evidence
    "get_claim_evidence",
    "get_entity_claims",
    "ClaimEvidence",
    "ClaimDetail",
]
