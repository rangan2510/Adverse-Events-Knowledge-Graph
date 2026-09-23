"""RxNorm: drug identity, spelling variants, brand names, ATC class.

Exact matching fails on ordinary spelling variation (ciclosporin, co-trimoxazole, paracetamol),
so resolution falls through to RxNav's approximate matcher. That handles British and INN
spellings and plain typos without a hand-kept alias table.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from pv_agent.sources.http import SourceUnavailable, get_json

BASE = "https://rxnav.nlm.nih.gov/REST"


@dataclass
class Drug:
    query: str
    rxcui: str
    name: str
    tty: str
    match: str  # "exact" or "approximate"
    brands: list[str] = field(default_factory=list)
    atc_classes: list[str] = field(default_factory=list)


def _properties(rxcui: str) -> dict[str, Any]:
    return get_json(f"{BASE}/rxcui/{rxcui}/properties.json").get("properties") or {}


def _brands(rxcui: str) -> list[str]:
    data = get_json(f"{BASE}/rxcui/{rxcui}/related.json", {"tty": "BN"})
    groups = (data.get("relatedGroup") or {}).get("conceptGroup") or []
    return [p["name"] for g in groups for p in (g.get("conceptProperties") or []) if p.get("name")]


def _atc(rxcui: str) -> list[str]:
    data = get_json(f"{BASE}/rxclass/class/byRxcui.json", {"rxcui": rxcui, "relaSource": "ATC"})
    items = (data.get("rxclassDrugInfoList") or {}).get("rxclassDrugInfo") or []
    out: list[str] = []
    for item in items:
        concept = item.get("rxclassMinConceptItem") or {}
        label = concept.get("className")
        if label and label not in out:
            out.append(label)
    return out


def _ingredient_rxcui(rxcui: str, tty: str) -> str:
    """Walk a brand or clinical drug up to its ingredient, where brands and ATC live."""
    if tty in ("IN", "MIN", "PIN"):
        return rxcui
    # RxNav wants space-separated ttys; MIN first so a combination maps to its multi-ingredient.
    data = get_json(f"{BASE}/rxcui/{rxcui}/related.json", {"tty": "MIN IN"})
    groups = (data.get("relatedGroup") or {}).get("conceptGroup") or []
    for wanted in ("MIN", "IN"):
        for g in groups:
            if g.get("tty") == wanted:
                for p in g.get("conceptProperties") or []:
                    if p.get("rxcui"):
                        return p["rxcui"]
    return rxcui


def resolve(name: str) -> Drug | None:
    """Resolve a drug name. Returns None only when nothing plausible matches."""
    name = name.strip()
    exact = get_json(f"{BASE}/rxcui.json", {"name": name})
    ids = (exact.get("idGroup") or {}).get("rxnormId") or []
    match = "exact"

    if not ids:
        approx = get_json(f"{BASE}/approximateTerm.json", {"term": name, "maxEntries": 5})
        candidates = (approx.get("approximateGroup") or {}).get("candidate") or []
        # Candidates repeat per synonym; take the top-scored distinct concept only.
        seen: dict[str, float] = {}
        for c in candidates:
            if c.get("rxcui"):
                seen.setdefault(c["rxcui"], float(c.get("score") or 0))
        if not seen:
            return None
        # Score is RxNav's own relevance; below 5 the match is too loose to trust. Some top
        # hits are retired concepts with no term type ("co-trimoxazole" -> 404949), so walk
        # down the list to the first live one.
        ranked = sorted(seen, key=seen.get, reverse=True)
        ids = [r for r in ranked if seen[r] >= 5 and _properties(r).get("tty")]
        if not ids:
            return None
        match = "approximate"

    props = _properties(ids[0])
    rxcui = _ingredient_rxcui(ids[0], props.get("tty") or "")
    if rxcui != ids[0]:
        props = _properties(rxcui)

    drug = Drug(query=name, rxcui=rxcui, name=props.get("name") or name, tty=props.get("tty") or "", match=match)
    with suppress(SourceUnavailable):
        drug.brands = _brands(rxcui)
    with suppress(SourceUnavailable):
        drug.atc_classes = _atc(rxcui)
    return drug
