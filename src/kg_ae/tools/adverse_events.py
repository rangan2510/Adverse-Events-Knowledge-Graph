"""
Adverse event tools.

Get known adverse events for drugs (SIDER labels), FDA label sections
(openFDA), and FAERS disproportionality signals. Backed by the GraphStore.
"""

from dataclasses import dataclass

from kg_ae.graph import get_store


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
    """Get adverse events for a drug, sorted by frequency descending."""
    store = get_store()
    drug_name = store.node_label("Drug", drug_key)
    by_ae: dict[int, DrugAdverseEvent] = {}
    for e in store.out_edges("Drug", drug_key, dst_type="AdverseEvent"):
        freq = e.frequency
        if min_frequency is not None and (freq is None or freq < min_frequency):
            continue
        existing = by_ae.get(e.dst_key)
        if existing is None or (freq or 0) > (existing.frequency or 0):
            by_ae[e.dst_key] = DrugAdverseEvent(
                drug_key=drug_key,
                drug_name=drug_name,
                ae_key=e.dst_key,
                ae_label=store.node_label("AdverseEvent", e.dst_key),
                frequency=freq,
                relation=e.relation,
                dataset=e.dataset,
            )
    results = sorted(by_ae.values(), key=lambda a: a.frequency or 0, reverse=True)
    return results[:limit]


def get_drug_profile(drug_key: int) -> dict:
    """Get complete profile for a drug: basic info, targets, and top AEs."""
    from kg_ae.tools.mechanism import get_drug_targets

    store = get_store()
    props = store.get_node("Drug", drug_key)
    if props is None:
        return {"error": f"Drug {drug_key} not found"}

    drug_info = {
        "drug_key": drug_key,
        "preferred_name": props.get("preferred_name"),
        "drugcentral_id": props.get("drugcentral_id"),
        "chembl_id": props.get("chembl_id"),
    }
    targets = get_drug_targets(drug_key)
    aes = get_drug_adverse_events(drug_key, limit=20)
    return {
        "drug": drug_info,
        "targets": [{"gene_key": t.gene_key, "symbol": t.gene_symbol} for t in targets],
        "adverse_events": [{"ae_key": ae.ae_key, "label": ae.ae_label, "frequency": ae.frequency} for ae in aes],
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


@dataclass
class DrugDrugInteraction:
    """A drug-drug interaction adverse event (TWOSIDES)."""

    drug_a_key: int
    drug_b_key: int
    ae_key: int
    ae_label: str
    prr: float | None = None
    report_count: int | None = None
    dataset: str | None = None


def get_drug_drug_interactions(drug_a_key: int, drug_b_key: int, limit: int = 50) -> list[DrugDrugInteraction]:
    """Get adverse events reported for the combination of two drugs (TWOSIDES).

    Traverses Drug -> DrugCombination -> AdverseEvent: finds combination nodes
    that both drugs belong to, then the AEs of those combinations.
    """
    store = get_store()
    # Combinations drug A belongs to.
    a_combos = {e.dst_key for e in store.out_edges("Drug", drug_a_key, dst_type="DrugCombination")}
    if not a_combos:
        return []
    b_combos = {e.dst_key for e in store.out_edges("Drug", drug_b_key, dst_type="DrugCombination")}
    shared = a_combos & b_combos
    results: list[DrugDrugInteraction] = []
    for ckey in shared:
        for e in store.out_edges("DrugCombination", ckey, dst_type="AdverseEvent"):
            results.append(
                DrugDrugInteraction(
                    drug_a_key=drug_a_key,
                    drug_b_key=drug_b_key,
                    ae_key=e.dst_key,
                    ae_label=store.node_label("AdverseEvent", e.dst_key),
                    prr=e.meta.get("prr") if e.meta else e.strength_score,
                    report_count=e.meta.get("report_count") if e.meta else None,
                    dataset=e.dataset,
                )
            )
    results.sort(key=lambda x: x.prr or 0, reverse=True)
    return results[:limit]


def get_drug_label_sections(
    drug_key: int,
    sections: list[str] | None = None,
) -> list[DrugLabelSection]:
    """Get FDA label sections for a drug (claim_type DRUG_LABEL, openFDA).

    Label content is stored in the edge's evidence payload. Returns an empty
    list when no DRUG_LABEL claims are present in the graph.
    """
    store = get_store()
    drug_name = store.node_label("Drug", drug_key)
    results: list[DrugLabelSection] = []
    for e in store.out_edges("Drug", drug_key, claim_type="DRUG_LABEL"):
        statement = e.statement or {}
        for ev in e.evidence:
            payload = ev.get("payload") or {}
            for section_name, content in payload.items():
                if sections is None or section_name in sections:
                    results.append(
                        DrugLabelSection(
                            drug_key=drug_key,
                            drug_name=drug_name,
                            section_name=section_name,
                            content=str(content),
                            effective_date=statement.get("effective_date"),
                            brand_name=statement.get("brand_name"),
                        )
                    )
    return results


def get_drug_faers_signals(
    drug_key: int,
    top_k: int = 200,
    min_count: int = 1,
    min_prr: float | None = None,
) -> list[FAERSSignal]:
    """Get FAERS disproportionality signals for a drug (claim_type DRUG_AE_FAERS).

    Returns drug-AE pairs with PRR, ROR, chi-squared sourced from the edge meta.
    Returns an empty list when no FAERS claims are present in the graph.
    """
    store = get_store()
    drug_name = store.node_label("Drug", drug_key)
    results: list[FAERSSignal] = []
    for e in store.out_edges("Drug", drug_key, dst_type="AdverseEvent", claim_type="DRUG_AE_FAERS"):
        meta = e.meta or {}
        count = int(meta.get("count", 0) or 0)
        prr = meta.get("prr")
        if count < min_count:
            continue
        if min_prr is not None and (prr is None or prr < min_prr):
            continue
        results.append(
            FAERSSignal(
                drug_key=drug_key,
                drug_name=drug_name,
                ae_key=e.dst_key,
                ae_label=store.node_label("AdverseEvent", e.dst_key),
                prr=prr,
                ror=meta.get("ror"),
                chi2=meta.get("chi2"),
                count=count,
            )
        )
    results.sort(key=lambda x: x.prr or 0, reverse=True)
    return results[:top_k]
