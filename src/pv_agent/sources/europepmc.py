"""Europe PMC literature search."""

from __future__ import annotations

from dataclasses import dataclass

from pv_agent.sources.http import get_json

SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


@dataclass
class Article:
    pmid: str | None
    title: str
    journal: str | None
    year: str | None
    abstract: str | None
    url: str


def search(query: str, limit: int = 6) -> list[Article]:
    data = get_json(SEARCH, {"query": query, "format": "json", "pageSize": limit, "resultType": "core"})
    out = []
    for r in (data.get("resultList") or {}).get("result") or []:
        src, rid = r.get("source") or "MED", r.get("id") or ""
        out.append(
            Article(
                pmid=rid if src == "MED" else None,
                title=r.get("title") or "",
                journal=r.get("journalTitle"),
                year=(r.get("firstPublicationDate") or "")[:4] or None,
                abstract=(r.get("abstractText") or "")[:600] or None,
                url=f"https://europepmc.org/article/{src}/{rid}",
            )
        )
    return out
