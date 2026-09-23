"""Open Targets: drug targets and FAERS disproportionality.

Field names were checked by schema introspection. The adverse-event statistic is `logLR`, a
likelihood-ratio signal against the whole of FAERS; rows above `criticalValue` are
disproportionately reported for this drug.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pv_agent.sources.http import SourceUnavailable, post_json

API = "https://api.platform.opentargets.org/api/v4/graphql"


def _gql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    data = post_json(API, {"query": query, "variables": variables})
    if data.get("errors"):
        raise SourceUnavailable(f"opentargets: {data['errors'][0].get('message')}")
    return data.get("data") or {}


@dataclass
class Target:
    symbol: str
    ensembl_id: str
    action: str
    mechanism: str


def targets(chembl_id: str) -> list[Target]:
    data = _gql(
        """query($id: String!) { drug(chemblId: $id) {
             mechanismsOfAction { rows { mechanismOfAction actionType targets { id approvedSymbol } } } } }""",
        {"id": chembl_id},
    )
    rows = (((data.get("drug") or {}).get("mechanismsOfAction") or {}).get("rows")) or []
    return [
        Target(
            t.get("approvedSymbol") or "",
            t.get("id") or "",
            r.get("actionType") or "",
            r.get("mechanismOfAction") or "",
        )
        for r in rows
        for t in r.get("targets") or []
    ]


@dataclass
class Pharmacogenomic:
    gene: str
    variant: str
    phenotype: str
    evidence_level: str
    category: str


# PharmGKB levels, strongest first. Anything unlisted sorts last.
_LEVEL_ORDER = {"1A": 0, "1B": 1, "2A": 2, "2B": 3, "3": 4, "4": 5}


def pharmacogenomics(chembl_id: str, limit: int = 12) -> list[Pharmacogenomic]:
    """Variant -> gene -> drug-response rows from PharmGKB via Open Targets, toxicity rows only.

    The same endpoint carries efficacy and dosing rows; those describe whether the drug works,
    not why it harms, so they are dropped. Sorted by evidence level so 1A findings lead. The
    `page` argument is not accepted on this field; the whole list comes back and is cut here.
    """
    data = _gql(
        """query($id: String!) { drug(chemblId: $id) {
             pharmacogenomics { pgxCategory phenotypeText evidenceLevel variantRsId target { approvedSymbol } } } }""",
        {"id": chembl_id},
    )
    rows = ((data.get("drug") or {}).get("pharmacogenomics")) or []
    out = [
        Pharmacogenomic(
            gene=(r.get("target") or {}).get("approvedSymbol") or "",
            variant=r.get("variantRsId") or "",
            phenotype=r.get("phenotypeText") or "",
            evidence_level=r.get("evidenceLevel") or "",
            category=r.get("pgxCategory") or "",
        )
        for r in rows
        if r.get("pgxCategory") == "toxicity" and r.get("phenotypeText")
    ]
    out.sort(key=lambda p: _LEVEL_ORDER.get(p.evidence_level, 9))
    return out[:limit]


@dataclass
class Signal:
    event: str
    count: int
    log_lr: float
    above_threshold: bool


def signals(chembl_id: str, size: int = 15) -> list[Signal]:
    """FAERS disproportionality signals for a drug, strongest first."""
    data = _gql(
        """query($id: String!, $size: Int!) { drug(chemblId: $id) {
             adverseEvents(page: {index: 0, size: $size}) { criticalValue rows { name count logLR } } } }""",
        {"id": chembl_id, "size": size},
    )
    ae = (data.get("drug") or {}).get("adverseEvents") or {}
    critical = float(ae.get("criticalValue") or 0)
    return [
        Signal(r["name"], int(r.get("count") or 0), float(r.get("logLR") or 0), float(r.get("logLR") or 0) > critical)
        for r in ae.get("rows") or []
    ]
