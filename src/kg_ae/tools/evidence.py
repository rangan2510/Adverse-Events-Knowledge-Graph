"""
Evidence retrieval tools.

Get provenance and supporting evidence for claims. In the file-based graph a
"claim" is an edge carrying its claim payload plus an evidence list, so this
module reads those edges from the GraphStore. This is the audit backbone:
every association is traceable to a dataset and source record.
"""

from dataclasses import dataclass

from kg_ae.graph import GraphEdge, get_store

# Map node type -> the edge field used to traverse from that entity
_ENTITY_TYPES = {"Drug", "Gene", "Disease", "Pathway", "AdverseEvent"}


@dataclass
class ClaimEvidence:
    """Evidence supporting a claim."""

    evidence_key: int
    evidence_type: str
    source_record_id: str | None
    source_url: str | None
    payload: dict | None
    support_strength: float | None
    dataset_key: str | None


@dataclass
class ClaimDetail:
    """Detailed claim with all linked evidence."""

    claim_key: int
    claim_type: str
    strength_score: float | None
    polarity: int | None
    statement: dict | None
    dataset_key: str | None
    evidence: list[ClaimEvidence]


def _edge_to_detail(edge: GraphEdge) -> ClaimDetail:
    evidence_list = [
        ClaimEvidence(
            evidence_key=i,
            evidence_type=ev.get("evidence_type") or (edge.claim_type or ""),
            source_record_id=ev.get("source_record_id"),
            source_url=ev.get("source_url"),
            payload=ev.get("payload"),
            support_strength=edge.strength_score,
            dataset_key=ev.get("dataset") or edge.dataset,
        )
        for i, ev in enumerate(edge.evidence)
    ]
    return ClaimDetail(
        claim_key=edge.claim_key or -1,
        claim_type=edge.claim_type or "",
        strength_score=edge.strength_score,
        polarity=edge.polarity,
        statement=edge.statement or None,
        dataset_key=edge.dataset,
        evidence=evidence_list,
    )


def get_claim_evidence(claim_key: int) -> ClaimDetail | None:
    """Get full evidence trail for a claim, or None if the claim is not found."""
    store = get_store()
    edge = store.get_claim(claim_key)
    if edge is None:
        return None
    return _edge_to_detail(edge)


def get_entity_claims(
    entity_type: str,
    entity_key: int,
    claim_types: list[str] | None = None,
    limit: int = 100,
) -> list[ClaimDetail]:
    """Get all claims (outgoing edges) for an entity.

    Args:
        entity_type: One of Drug, Gene, Disease, Pathway, AdverseEvent
        entity_key: The entity's integer key
        claim_types: Filter by claim types, or None for all
        limit: Maximum claims to return
    """
    if entity_type not in _ENTITY_TYPES:
        return []
    store = get_store()
    wanted = set(claim_types) if claim_types else None
    details: list[ClaimDetail] = []
    for edge in store.out_edges(entity_type, entity_key):
        if wanted is not None and edge.claim_type not in wanted:
            continue
        details.append(_edge_to_detail(edge))
    details.sort(key=lambda d: d.strength_score or 0, reverse=True)
    return details[:limit]
