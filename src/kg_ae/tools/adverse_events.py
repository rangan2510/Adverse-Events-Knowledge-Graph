"""
Adverse event tools.

Get known adverse events for drugs from SIDER/labels.
"""

from dataclasses import dataclass

from kg_ae.db import execute


@dataclass
class DrugAdverseEvent:
    """Drug-adverse event association."""
    drug_key: int
    drug_name: str
    ae_key: int
    ae_label: str
    frequency: float | None = None
    relation: str | None = None
    dataset: str | None = None


def get_drug_adverse_events(
    drug_key: int,
    min_frequency: float | None = None,
    limit: int = 100,
) -> list[DrugAdverseEvent]:
    """
    Get adverse events for a drug.

    Args:
        drug_key: The drug's primary key
        min_frequency: Minimum frequency threshold (0-1), None for all
        limit: Maximum number of results

    Returns:
        List of DrugAdverseEvent sorted by frequency descending
    """
    if min_frequency is not None:
        rows = execute(
            f"""
            SELECT TOP {limit}
                d.drug_key, d.preferred_name,
                ae.ae_key, ae.ae_label,
                cae.frequency, cae.relation
            FROM kg.Drug d
                , kg.HasClaim hc
                , kg.Claim c
                , kg.ClaimAdverseEvent cae
                , kg.AdverseEvent ae
            WHERE MATCH(d-(hc)->c-(cae)->ae)
              AND d.drug_key = ?
              AND (cae.frequency IS NULL OR cae.frequency >= ?)
            ORDER BY cae.frequency DESC
            """,
            (drug_key, min_frequency),
            commit=False,
        )
    else:
        rows = execute(
            f"""
            SELECT TOP {limit}
                d.drug_key, d.preferred_name,
                ae.ae_key, ae.ae_label,
                cae.frequency, cae.relation
            FROM kg.Drug d
                , kg.HasClaim hc
                , kg.Claim c
                , kg.ClaimAdverseEvent cae
                , kg.AdverseEvent ae
            WHERE MATCH(d-(hc)->c-(cae)->ae)
              AND d.drug_key = ?
            ORDER BY cae.frequency DESC
            """,
            (drug_key,),
            commit=False,
        )

    return [
        DrugAdverseEvent(
            drug_key=row[0],
            drug_name=row[1],
            ae_key=row[2],
            ae_label=row[3],
            frequency=row[4],
            relation=row[5],
        )
        for row in rows
    ]


def get_drug_profile(drug_key: int) -> dict:
    """
    Get complete profile for a drug: basic info, targets, and top AEs.

    Args:
        drug_key: The drug's primary key

    Returns:
        Dict with drug info, targets, and adverse_events
    """
    from kg_ae.tools.mechanism import get_drug_targets

    # Get drug info
    rows = execute(
        """
        SELECT drug_key, preferred_name, drugcentral_id, chembl_id
        FROM kg.Drug
        WHERE drug_key = ?
        """,
        (drug_key,),
        commit=False,
    )
    if not rows:
        return {"error": f"Drug {drug_key} not found"}

    row = rows[0]
    drug_info = {
        "drug_key": row[0],
        "preferred_name": row[1],
        "drugcentral_id": row[2],
        "chembl_id": row[3],
    }

    targets = get_drug_targets(drug_key)
    aes = get_drug_adverse_events(drug_key, limit=20)

    return {
        "drug": drug_info,
        "targets": [{"gene_key": t.gene_key, "symbol": t.gene_symbol} for t in targets],
        "adverse_events": [
            {"ae_key": ae.ae_key, "label": ae.ae_label, "frequency": ae.frequency}
            for ae in aes
        ],
    }
