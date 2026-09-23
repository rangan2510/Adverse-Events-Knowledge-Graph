"""UniProt then Reactome: gene symbol to pathways.

Pick the reviewed (Swiss-Prot) accession. Unreviewed TrEMBL accessions have no Reactome
annotation and 404, which reads as "no biology" when it means "wrong accession".
"""

from __future__ import annotations

from dataclasses import dataclass

from pv_agent.sources.http import NotFound, get_json


def uniprot_accession(symbol: str) -> str | None:
    data = get_json(
        "https://rest.uniprot.org/uniprotkb/search",
        {"query": f"gene_exact:{symbol} AND organism_id:9606", "format": "json", "size": 10, "fields": "accession"},
    )
    results = data.get("results") or []
    reviewed = [r for r in results if r.get("entryType", "").lower().startswith("uniprotkb reviewed")]
    chosen = reviewed or results
    return chosen[0].get("primaryAccession") if chosen else None


@dataclass
class Pathway:
    id: str
    name: str
    lineage: str = ""


def pathways(symbol: str, limit: int = 15) -> tuple[str | None, list[Pathway]]:
    acc = uniprot_accession(symbol)
    if not acc:
        return None, []
    try:
        rows = get_json(f"https://reactome.org/ContentService/data/mapping/UniProt/{acc}/pathways")
    except NotFound:
        return acc, []
    return acc, [Pathway(r.get("stId") or "", r.get("displayName") or "") for r in rows[:limit]]


def lineage(pathway_id: str) -> str:
    """Parent chain for a pathway, most specific first: 'Xenobiotics > Phase I > Metabolism'.

    A flat pathway name says where a gene sits. The lineage says what biological process that
    is part of, which is what links an enzyme to an organ effect.
    """
    try:
        rows = get_json(f"https://reactome.org/ContentService/data/event/{pathway_id}/ancestors")
    except NotFound:
        return ""
    chain = rows[0] if rows and isinstance(rows[0], list) else []
    names = [e.get("displayName") for e in chain if e.get("displayName")]
    return " > ".join(names[:5])
