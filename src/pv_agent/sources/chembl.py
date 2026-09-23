"""ChEMBL: molecule lookup, mechanism of action, regulatory warnings."""

from __future__ import annotations

from dataclasses import dataclass

from pv_agent.sources.http import NotFound, get_json

BASE = "https://www.ebi.ac.uk/chembl/api/data"


@dataclass
class Molecule:
    chembl_id: str
    name: str
    kind: str
    max_phase: float | None


def find_molecule(name: str) -> Molecule | None:
    """Exact preferred-name match only. The search endpoint is fuzzy and returns analogues."""
    data = get_json(f"{BASE}/molecule/search.json", {"q": name, "limit": 10})
    for m in data.get("molecules") or []:
        if (m.get("pref_name") or "").lower() == name.lower():
            return Molecule(m["molecule_chembl_id"], m["pref_name"], m.get("molecule_type") or "", m.get("max_phase"))
    return None


@dataclass
class Mechanism:
    action: str
    mechanism: str
    target_chembl_id: str
    target_name: str


def mechanisms(chembl_id: str) -> list[Mechanism]:
    try:
        data = get_json(f"{BASE}/mechanism.json", {"molecule_chembl_id": chembl_id})
    except NotFound:
        return []
    return [
        Mechanism(
            action=m.get("action_type") or "",
            mechanism=m.get("mechanism_of_action") or "",
            target_chembl_id=m.get("target_chembl_id") or "",
            target_name=m.get("target_pref_name") or "",
        )
        for m in data.get("mechanisms") or []
    ]


@dataclass
class Warning:
    kind: str  # Black Box Warning, Withdrawn
    toxicity: str
    country: str
    year: int | None
    description: str


def warnings(chembl_id: str) -> list[Warning]:
    """Regulatory warnings and withdrawals, by country."""
    try:
        data = get_json(f"{BASE}/drug_warning.json", {"molecule_chembl_id": chembl_id})
    except NotFound:
        return []
    return [
        Warning(
            kind=w.get("warning_type") or "",
            toxicity=w.get("warning_class") or "",
            country=w.get("warning_country") or "",
            year=w.get("warning_year"),
            description=(w.get("warning_description") or "")[:300],
        )
        for w in data.get("drug_warnings") or []
    ]
