"""
LLM tool functions for knowledge graph queries.

These are the deterministic tools that the LLM orchestrator can call.
All tools return structured data (never prose).
"""

from kg_ae.tools.adverse_events import (
    DrugAdverseEvent,
    DrugLabelSection,
    FAERSSignal,
    get_drug_adverse_events,
    get_drug_faers_signals,
    get_drug_label_sections,
    get_drug_profile,
)
from kg_ae.tools.evidence import (
    ClaimDetail,
    ClaimEvidence,
    get_claim_evidence,
    get_entity_claims,
)
from kg_ae.tools.mechanism import (
    DiseaseGene,
    DrugTarget,
    GeneDisease,
    GeneInteractor,
    GenePathway,
    expand_gene_context,
    expand_mechanism,
    get_disease_genes,
    get_drug_targets,
    get_gene_diseases,
    get_gene_interactors,
    get_gene_pathways,
)
from kg_ae.tools.paths import (
    MechanisticPath,
    PathStep,
    ScoringPolicy,
    explain_paths,
    find_drug_to_ae_paths,
    score_paths,
    score_paths_with_evidence,
)
from kg_ae.tools.resolve import (
    ResolvedEntity,
    resolve_adverse_events,
    resolve_diseases,
    resolve_drugs,
    resolve_genes,
)
from kg_ae.tools.subgraph import (
    Edge,
    Node,
    Subgraph,
    build_subgraph,
    score_edges,
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
