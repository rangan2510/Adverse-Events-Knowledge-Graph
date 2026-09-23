"""openFDA: US product labels and FAERS report counts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pv_agent.sources.http import NotFound, get_json

LABEL = "https://api.fda.gov/drug/label.json"
EVENT = "https://api.fda.gov/drug/event.json"

SECTIONS = {
    "boxed_warning": ("boxed_warning",),
    "contraindications": ("contraindications",),
    "warnings": ("warnings_and_cautions", "warnings", "precautions"),
    "adverse_reactions": ("adverse_reactions",),
    "drug_interactions": ("drug_interactions", "drug_interactions_table", "drug_and_or_laboratory_test_interactions"),
    "clinical_pharmacology": ("clinical_pharmacology", "pharmacokinetics", "mechanism_of_action"),
    "dosage": ("dosage_and_administration",),
}


@dataclass
class Label:
    set_id: str
    brand: str
    generic: str
    route: list[str]
    effective: str
    url: str
    sections: dict[str, str] = field(default_factory=dict)


def _text(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    parts = []
    for k in keys:
        v = record.get(k)
        if isinstance(v, list):
            parts.extend(x for x in v if isinstance(x, str))
    return " ".join(" ".join(parts).split())


def labels(generic: str, *, systemic: bool = True, limit: int = 8) -> list[Label]:
    """Labels for a generic name, systemic products first.

    A plain name search returns eye drops and creams ahead of tablets (15 of 26 cyclosporine
    labels are ophthalmic), which is how an earlier version concluded that no systemic
    cyclosporine label existed. Filter routes, then rank records that carry interaction text.
    """
    search = f'openfda.generic_name:"{generic}"'
    if systemic:
        search += ' AND NOT openfda.route:"OPHTHALMIC" AND NOT openfda.route:"TOPICAL"'
    try:
        data = get_json(LABEL, {"search": search, "limit": min(limit, 50)})
    except NotFound:
        return []
    out = []
    for r in data.get("results") or []:
        o = r.get("openfda") or {}
        set_id = r.get("set_id") or ""
        lab = Label(
            set_id=set_id,
            brand=", ".join(o.get("brand_name") or [])[:80],
            generic=", ".join(o.get("generic_name") or [])[:80],
            route=o.get("route") or [],
            effective=r.get("effective_time") or "",
            url=f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}",
        )
        for name, keys in SECTIONS.items():
            text = _text(r, keys)
            if text:
                lab.sections[name] = text
        out.append(lab)
    # Richest label first: more sections and more interaction text.
    out.sort(key=lambda x: (len(x.sections), len(x.sections.get("drug_interactions", ""))), reverse=True)
    return out


def _total(search: str) -> int:
    try:
        data = get_json(EVENT, {"search": search, "limit": 1})
    except NotFound:
        return 0
    return int((((data.get("meta") or {}).get("results") or {}).get("total")) or 0)


def _q(name: str) -> str:
    return f'patient.drug.medicinalproduct:"{name}"'


def reaction_counts(name: str, limit: int = 20) -> list[tuple[str, int]]:
    """Top reported reactions for a drug. Report volume, not incidence."""
    try:
        data = get_json(EVENT, {"search": _q(name), "count": "patient.reaction.reactionmeddrapt.exact", "limit": limit})
    except NotFound:
        return []
    return [(r["term"], int(r["count"])) for r in data.get("results") or [] if r.get("term")]


@dataclass
class PairCounts:
    a: str
    b: str
    reports_a: int
    reports_b: int
    reports_both: int
    event: str | None = None
    reports_both_with_event: int | None = None


def pair_counts(a: str, b: str, event: str | None = None) -> PairCounts:
    """Reports naming both drugs, with each drug's own total as denominators."""
    both = f"({_q(a)}) AND ({_q(b)})"
    out = PairCounts(a, b, _total(_q(a)), _total(_q(b)), _total(both))
    if event:
        out.event = event
        out.reports_both_with_event = _total(f'{both} AND patient.reaction.reactionmeddrapt:"{event}"')
    return out
