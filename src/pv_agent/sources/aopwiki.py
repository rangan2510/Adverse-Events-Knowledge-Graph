"""AOP-Wiki: adverse outcome pathways, as causal chains from molecular event to clinical outcome.

The only source here that gives a narrative: drug -> molecular initiating event -> key events
-> adverse outcome, with genes on each link. Coverage is thin for pharmaceuticals (the wiki was
built for environmental toxicology; about 9 of 21 common drugs probed were present), so absence
means nothing and callers must say so.

Schema facts learned by introspection, because the documentation disagrees with the data:
- Stressors are typed NCIt C54571, not aopo:Stressor.
- A stressor links to its pathways with dcterms:isPartOf, not aopo:has_stressor.
- Genes on a relationship are edam:data_1025 nodes found by named-entity recognition over the
  text, so they include noise (CNP, NES, HPD on an immunology pathway). Filter them.
- Some pathways have key events but no relationships yet: they are drafts, not chains.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pv_agent.sources.http import get_json

SPARQL = "https://aopwiki.rdf.bigcat-bioinformatics.org/sparql"

PREFIXES = """
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX aopo: <http://aopkb.org/aop_ontology#>
PREFIX edam: <http://edamontology.org/>
PREFIX ncit: <http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#>
"""


def _query(sparql: str) -> list[dict]:
    data = get_json(SPARQL, {"query": PREFIXES + sparql, "format": "json"})
    return ((data.get("results") or {}).get("bindings")) or []


def _value(row: dict, key: str) -> str:
    return (row.get(key) or {}).get("value") or ""


@dataclass
class Link:
    upstream: str
    downstream: str
    genes: list[str] = field(default_factory=list)


@dataclass
class OutcomePathway:
    id: str
    title: str
    url: str
    initiating_event: str
    adverse_outcome: str
    links: list[Link] = field(default_factory=list)

    @property
    def is_draft(self) -> bool:
        return not self.links


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def find_pathways(drug: str) -> list[OutcomePathway]:
    """Pathways that list the drug as a stressor. Empty when the drug is not in the wiki."""
    rows = _query(
        f"""
        SELECT DISTINCT ?aop ?title ?mie ?ao WHERE {{
          ?s a ncit:C54571 ; dc:title ?name ; dcterms:isPartOf ?aop .
          FILTER(CONTAINS(LCASE(?name), "{_escape(drug.lower())}"))
          ?aop a aopo:AdverseOutcomePathway ; dc:title ?title .
          OPTIONAL {{ ?aop aopo:has_molecular_initiating_event ?m . ?m dc:title ?mie }}
          OPTIONAL {{ ?aop aopo:has_adverse_outcome ?a . ?a dc:title ?ao }}
        }} LIMIT 6
        """
    )
    seen: dict[str, OutcomePathway] = {}
    for r in rows:
        uri = _value(r, "aop")
        if uri not in seen:
            seen[uri] = OutcomePathway(
                id=uri.rsplit("/", 1)[-1],
                title=_value(r, "title"),
                url=uri.replace("identifiers.org/aop/", "aopwiki.org/aops/"),
                initiating_event=_value(r, "mie"),
                adverse_outcome=_value(r, "ao"),
            )
        # Several initiating events or outcomes can hang off one pathway; keep the first of each.
        p = seen[uri]
        p.initiating_event = p.initiating_event or _value(r, "mie")
        p.adverse_outcome = p.adverse_outcome or _value(r, "ao")
    return list(seen.values())


def chain(pathway_uri: str, known_genes: set[str]) -> list[Link]:
    """Ordered key-event relationships for a pathway, with the genes the wiki mentions on each.

    Genes come from named-entity recognition over the relationship text, so they mix real
    pathway members (NFATC1, PPP3CA) with false hits (CNP matches the word cyclophilin; NES
    matches nestin). No frequency rule separates them: CNP appears on every link of the
    calcineurin pathway. So genes we already trust for this drug go first, the rest follow, and
    the caller labels the whole list as text-mined rather than curated.
    """
    rows = _query(
        f"""
        SELECT ?up ?down (GROUP_CONCAT(DISTINCT ?g; separator="|") AS ?genes) WHERE {{
          <{pathway_uri}> aopo:has_key_event_relationship ?ker .
          ?ker aopo:has_upstream_key_event ?u ; aopo:has_downstream_key_event ?d .
          ?u dc:title ?up . ?d dc:title ?down .
          OPTIONAL {{ ?ker edam:data_1025 ?gn . ?gn rdfs:label ?g }}
        }} GROUP BY ?up ?down
        """
    )
    links = []
    for r in rows:
        found = sorted({g for g in _value(r, "genes").split("|") if g})
        ordered = [g for g in found if g in known_genes] + [g for g in found if g not in known_genes]
        links.append(Link(_value(r, "up"), _value(r, "down"), ordered[:6]))
    return _order(links)


def _order(links: list[Link]) -> list[Link]:
    """Put the links in causal order by following downstream -> upstream matches."""
    if not links:
        return links
    downstream = {ln.downstream for ln in links}
    ordered = [ln for ln in links if ln.upstream not in downstream]  # the start has no predecessor
    remaining = [ln for ln in links if ln not in ordered]
    while remaining and ordered:
        tail = ordered[-1].downstream
        nxt = next((ln for ln in remaining if ln.upstream == tail), None)
        if nxt is None:
            break
        ordered.append(nxt)
        remaining.remove(nxt)
    return ordered + remaining
