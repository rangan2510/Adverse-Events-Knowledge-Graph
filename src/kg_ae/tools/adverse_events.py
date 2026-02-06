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
                MAX(cae.frequency) AS frequency,
                MIN(cae.relation)  AS relation
            FROM kg.Drug d
                , kg.HasClaim hc
                , kg.Claim c
                , kg.ClaimAdverseEvent cae
                , kg.AdverseEvent ae
            WHERE MATCH(d-(hc)->c-(cae)->ae)
              AND d.drug_key = ?
              AND (cae.frequency IS NULL OR cae.frequency >= ?)
            GROUP BY d.drug_key, d.preferred_name,
                     ae.ae_key, ae.ae_label
            ORDER BY frequency DESC
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
                MAX(cae.frequency) AS frequency,
                MIN(cae.relation)  AS relation
            FROM kg.Drug d
                , kg.HasClaim hc
                , kg.Claim c
                , kg.ClaimAdverseEvent cae
                , kg.AdverseEvent ae
            WHERE MATCH(d-(hc)->c-(cae)->ae)
              AND d.drug_key = ?
            GROUP BY d.drug_key, d.preferred_name,
                     ae.ae_key, ae.ae_label
            ORDER BY frequency DESC
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


@dataclass
class DrugLabelSection:
    """Drug label section content."""
    drug_key: int
    drug_name: str
    section_name: str
    content: str
    effective_date: str | None = None
    brand_name: str | None = None


@dataclass
class FAERSSignal:
    """FAERS disproportionality signal for a drug-AE pair."""
    drug_key: int
    drug_name: str
    ae_key: int
    ae_label: str
    prr: float | None = None  # Proportional Reporting Ratio
    ror: float | None = None  # Reporting Odds Ratio
    chi2: float | None = None  # Chi-squared statistic
    count: int = 0  # Number of reports


def get_drug_label_sections(
    drug_key: int,
    sections: list[str] | None = None,
) -> list[DrugLabelSection]:
    """
    Get FDA label sections for a drug.

    Available sections vary by drug but commonly include:
    - adverse_reactions
    - warnings
    - contraindications
    - drug_interactions
    - boxed_warning

    Args:
        drug_key: The drug's primary key
        sections: List of section names to retrieve, or None for all available

    Returns:
        List of DrugLabelSection with content for each available section
    """
    import json

    # Get claims with DRUG_LABEL type for this drug
    rows = execute(
        """
        SELECT 
            d.drug_key, d.preferred_name,
            c.statement_json,
            e.payload_json
        FROM kg.Drug d
            , kg.HasClaim hc
            , kg.Claim c
            , kg.SupportedBy sb
            , kg.Evidence e
        WHERE MATCH(d-(hc)->c-(sb)->e)
          AND d.drug_key = ?
          AND c.claim_type = 'DRUG_LABEL'
          AND e.payload_json IS NOT NULL
        """,
        (drug_key,),
        commit=False,
    )

    results = []
    for row in rows:
        drug_name = row[1]
        statement = json.loads(row[2]) if row[2] else {}
        payload = json.loads(row[3]) if row[3] else {}

        effective_date = statement.get("effective_date")
        brand_name = statement.get("brand_name")

        # Extract requested sections from payload
        for section_name, content in payload.items():
            if sections is None or section_name in sections:
                results.append(
                    DrugLabelSection(
                        drug_key=drug_key,
                        drug_name=drug_name,
                        section_name=section_name,
                        content=content,
                        effective_date=effective_date,
                        brand_name=brand_name,
                    )
                )

    return results


def get_drug_faers_signals(
    drug_key: int,
    top_k: int = 200,
    min_count: int = 1,
    min_prr: float | None = None,
) -> list[FAERSSignal]:
    """
    Get FAERS disproportionality signals for a drug.

    Returns drug-AE pairs with PRR, ROR, chi-squared from FAERS data.

    Args:
        drug_key: The drug's primary key
        top_k: Maximum number of signals to return
        min_count: Minimum report count threshold
        min_prr: Minimum PRR threshold (optional)

    Returns:
        List of FAERSSignal sorted by PRR descending
    """
    import json

    # Query FAERS claims for this drug
    rows = execute(
        f"""
        SELECT TOP {top_k}
            d.drug_key, d.preferred_name,
            ae.ae_key, ae.ae_label,
            c.meta_json
        FROM kg.Drug d
            , kg.HasClaim hc
            , kg.Claim c
            , kg.ClaimAdverseEvent cae
            , kg.AdverseEvent ae
        WHERE MATCH(d-(hc)->c-(cae)->ae)
          AND d.drug_key = ?
          AND c.claim_type = 'DRUG_AE_FAERS'
        ORDER BY c.strength_score DESC
        """,
        (drug_key,),
        commit=False,
    )

    results = []
    for row in rows:
        meta = json.loads(row[4]) if row[4] else {}

        prr = meta.get("prr")
        ror = meta.get("ror")
        chi2 = meta.get("chi2")
        count = meta.get("count", 0)

        # Apply filters
        if count < min_count:
            continue
        if min_prr is not None and (prr is None or prr < min_prr):
            continue

        results.append(
            FAERSSignal(
                drug_key=row[0],
                drug_name=row[1],
                ae_key=row[2],
                ae_label=row[3],
                prr=prr,
                ror=ror,
                chi2=chi2,
                count=count,
            )
        )

    # Sort by PRR descending
    results.sort(key=lambda x: x.prr or 0, reverse=True)
    return results
