"""Tavily web search, restricted to regulator and literature domains.

Only known biomedical terms leave the machine. The query is rebuilt from an allowlist, so
anything that is not a resolved drug name or a pharmacovigilance word is dropped before the
request. Patient details cannot pass because they are never on the list.
"""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlparse

from tavily import TavilyClient

from pv_agent.config import get_settings

SAFE_WORDS = frozenset(
    {
        # fmt: off
        "mechanism",
        "adverse",
        "event",
        "reaction",
        "risk",
        "warning",
        "label",
        "contraindication",
        "interaction",
        "pathway",
        "target",
        "inhibitor",
        "inducer",
        "substrate",
        "agonist",
        "antagonist",
        "metabolism",
        "toxicity",
        "safety",
        "signal",
        "case",
        "report",
        "review",
        "guideline",
        "recall",
        "withdrawal",
        "incidence",
        "frequency",
        "dose",
        "adjustment",
        "monitoring",
        "product",
        "information",
        "smpc",
        "summary",
        "characteristics",
        "renal",
        "hepatic",
        "impairment",
        "pregnancy",
        # fmt: on
    }
)

# Backstop patterns. The allowlist is the real control; these catch anything that slipped in
# as part of a "drug name".
BLOCKED = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    re.compile(r"\+?\d[\d\s().-]{7,}\d"),
    re.compile(r"\b\d{1,3}\s*(year|yr)s?[- ]old\b", re.I),
    re.compile(r"\b(mr|mrs|ms|dr|miss)\.?\s+[A-Z][a-z]+", re.I),
)

STALE = ("no longer authorised", "no longer authorized", "withdrawn from the market")
HISTORICAL = ("/scientific-discussion", "/variation-report", "/assessment-report")


class UnsafeQuery(ValueError):
    pass


@dataclass
class Hit:
    title: str
    url: str
    domain: str
    text: str
    score: float
    caution: str | None


def build_query(terms: list[str], entities: list[str]) -> str:
    known = {e.lower() for e in entities}
    kept = []
    for t in terms:
        t = t.strip()
        if not t:
            continue
        if any(p.search(t) for p in BLOCKED):
            raise UnsafeQuery(f"blocked term: {t[:20]}")
        low = t.lower()
        if low in known or any(low in k or k in low for k in known) or low in SAFE_WORDS:
            kept.append(t)
    return " ".join(kept)


def _caution(url: str, text: str) -> str | None:
    low = text.lower()
    if any(m in low for m in STALE):
        return "Document states the product is no longer authorised. Not current guidance."
    if any(h in url.lower() for h in HISTORICAL):
        return "Historical assessment document, not current product information."
    return None


def search(terms: list[str], entities: list[str], *, domains: list[str] | None = None, limit: int = 8) -> list[Hit]:
    s = get_settings()
    if not s.web_search_enabled():
        raise RuntimeError("web search disabled or TAVILY_API_KEY unset")
    query = build_query(terms, entities)
    if not query:
        raise UnsafeQuery("no allowlisted terms remained")

    allowed = [d for d in (domains or s.web_domains) if d in s.web_domains] or s.web_domains
    client = TavilyClient(api_key=s.tavily_key)
    try:
        resp = client.search(
            query=query,
            search_depth="advanced",
            max_results=limit,
            include_domains=allowed,
            include_domains_mode="restrict",
            include_answer=False,
        )
    finally:
        with suppress(Exception):
            client.close()

    hits = []
    for r in resp.get("results") or []:
        url = r.get("url") or ""
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        if not any(host == d or host.endswith("." + d) for d in allowed):
            continue
        # EMA serves every document in every EU language; keep English.
        if re.search(r"/(bg|cs|da|de|el|es|et|fi|fr|ga|hr|hu|it|lt|lv|mt|nl|pl|pt|ro|sk|sl|sv)/", url):
            continue
        text = r.get("content") or ""
        hits.append(Hit(r.get("title") or "", url, host, text, float(r.get("score") or 0), _caution(url, text)))
    return hits
