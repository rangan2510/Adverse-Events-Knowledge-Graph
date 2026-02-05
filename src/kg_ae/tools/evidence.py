"""
Evidence retrieval tools.

Get provenance and supporting evidence for claims.
"""

import json
from dataclasses import dataclass

from kg_ae.db import execute


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


def get_claim_evidence(claim_key: int) -> ClaimDetail | None:
    """
    Get full evidence trail for a claim.

    This is the audit backbone - returns all provenance for any claim.

    Args:
        claim_key: The claim's primary key

    Returns:
        ClaimDetail with all linked Evidence records, or None if claim not found
    """
    # Get claim details (regular query, no MATCH)
    claim_rows = execute(
        """
        SELECT 
            c.claim_key, c.claim_type, c.strength_score, c.polarity,
            c.statement_json, d.dataset_key
        FROM kg.Claim c
        LEFT JOIN kg.Dataset d ON c.dataset_id = d.dataset_id
        WHERE c.claim_key = ?
        """,
        (claim_key,),
        commit=False,
    )

    if not claim_rows:
        return None

    row = claim_rows[0]
    statement = json.loads(row[4]) if row[4] else None

    # Get linked evidence via SupportedBy (no JOIN with MATCH)
    # First get evidence keys via MATCH, then join with Dataset separately
    evidence_rows = execute(
        """
        SELECT 
            e.evidence_key, e.evidence_type, e.source_record_id,
            e.source_url, e.payload_json, sb.support_strength,
            e.dataset_id
        FROM kg.Claim c
            , kg.SupportedBy sb
            , kg.Evidence e
        WHERE MATCH(c-(sb)->e)
          AND c.claim_key = ?
        """,
        (claim_key,),
        commit=False,
    )

    evidence_list = []
    for ev_row in evidence_rows:
        payload = json.loads(ev_row[4]) if ev_row[4] else None
        
        # Get dataset_key separately if dataset_id exists
        dataset_key = None
        if ev_row[6]:
            ds_rows = execute(
                "SELECT dataset_key FROM kg.Dataset WHERE dataset_id = ?",
                (ev_row[6],),
                commit=False,
            )
            if ds_rows:
                dataset_key = ds_rows[0][0]
        
        evidence_list.append(
            ClaimEvidence(
                evidence_key=ev_row[0],
                evidence_type=ev_row[1],
                source_record_id=ev_row[2],
                source_url=ev_row[3],
                payload=payload,
                support_strength=ev_row[5],
                dataset_key=dataset_key,
            )
        )

    return ClaimDetail(
        claim_key=row[0],
        claim_type=row[1],
        strength_score=row[2],
        polarity=row[3],
        statement=statement,
        dataset_key=row[5],
        evidence=evidence_list,
    )


def get_entity_claims(
    entity_type: str,
    entity_key: int,
    claim_types: list[str] | None = None,
    limit: int = 100,
) -> list[ClaimDetail]:
    """
    Get all claims for an entity.

    Args:
        entity_type: One of 'Drug', 'Gene', 'Disease', 'Pathway', 'AdverseEvent'
        entity_key: The entity's primary key
        claim_types: Filter by claim types, or None for all
        limit: Maximum claims to return

    Returns:
        List of ClaimDetail with evidence
    """
    # Map entity type to table and key column
    entity_map = {
        "Drug": ("kg.Drug", "drug_key"),
        "Gene": ("kg.Gene", "gene_key"),
        "Disease": ("kg.Disease", "disease_key"),
        "Pathway": ("kg.Pathway", "pathway_key"),
        "AdverseEvent": ("kg.AdverseEvent", "ae_key"),
    }

    if entity_type not in entity_map:
        return []

    table, key_col = entity_map[entity_type]

    # Build query based on claim type filter
    if claim_types:
        placeholders = ",".join("?" for _ in claim_types)
        query = f"""
            SELECT TOP {limit} c.claim_key
            FROM {table} ent
                , kg.HasClaim hc
                , kg.Claim c
            WHERE MATCH(ent-(hc)->c)
              AND ent.{key_col} = ?
              AND c.claim_type IN ({placeholders})
            ORDER BY c.strength_score DESC
        """
        params = (entity_key, *claim_types)
    else:
        query = f"""
            SELECT TOP {limit} c.claim_key
            FROM {table} ent
                , kg.HasClaim hc
                , kg.Claim c
            WHERE MATCH(ent-(hc)->c)
              AND ent.{key_col} = ?
            ORDER BY c.strength_score DESC
        """
        params = (entity_key,)

    rows = execute(query, params, commit=False)

    # Get full details for each claim
    results = []
    for row in rows:
        claim_detail = get_claim_evidence(row[0])
        if claim_detail:
            results.append(claim_detail)

    return results
