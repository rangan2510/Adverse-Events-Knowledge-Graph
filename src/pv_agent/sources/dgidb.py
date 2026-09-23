"""DGIdb: drug-gene interactions in both directions.

`interactionScore` measures how unusual a pairing is, not how well evidenced. For atorvastatin
it ranked an untyped PharmGKB row (LPP, 8.8) above the real mechanism (HMGCR inhibitor, 0.43,
five sources). So rows are ranked by having an interaction type, then source count, then score.
"""

from __future__ import annotations

from dataclasses import dataclass

from pv_agent.sources.http import SourceUnavailable, post_json

API = "https://dgidb.org/api/graphql"


@dataclass
class Interaction:
    gene: str
    drug: str
    types: list[str]
    sources: list[str]
    score: float

    @property
    def curated(self) -> bool:
        return bool(self.types)


def _rows(query: str, names: list[str], key: str) -> list[Interaction]:
    data = post_json(API, {"query": query, "variables": {"names": names}})
    if data.get("errors"):
        raise SourceUnavailable(f"dgidb: {data['errors'][0].get('message')}")
    out = []
    for node in ((data.get("data") or {}).get(key) or {}).get("nodes") or []:
        for row in node.get("interactions") or []:
            other = row.get("drug") or row.get("gene") or {}
            gene = node["name"] if key == "genes" else other.get("name", "")
            drug = other.get("name", "") if key == "genes" else node["name"]
            out.append(
                Interaction(
                    gene=gene,
                    drug=drug,
                    types=[t["type"] for t in row.get("interactionTypes") or [] if t.get("type")],
                    sources=[s["sourceDbName"] for s in row.get("sources") or [] if s.get("sourceDbName")],
                    score=float(row.get("interactionScore") or 0),
                )
            )
    out.sort(key=lambda i: (i.curated, len(i.sources), i.score), reverse=True)
    return out


_DRUG = """query($names: [String!]) { drugs(names: $names) { nodes { name interactions {
  interactionScore interactionTypes { type } gene { name } sources { sourceDbName } } } } }"""
_GENE = """query($names: [String!]) { genes(names: $names) { nodes { name interactions {
  interactionScore interactionTypes { type } drug { name } sources { sourceDbName } } } } }"""


def drug_targets(drug: str, limit: int = 10) -> list[Interaction]:
    return _rows(_DRUG, [drug.upper()], "drugs")[:limit]


def gene_drugs(gene: str, limit: int = 15) -> list[Interaction]:
    return _rows(_GENE, [gene.upper()], "genes")[:limit]
