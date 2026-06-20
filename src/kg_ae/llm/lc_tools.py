"""
LangChain tool definitions.

Wraps the deterministic GraphStore tools (and the optional Tavily web-search
tool) as LangChain ``@tool`` functions so a LangChain/LangGraph agent can call
them. Graph-tool results are dataclasses; we convert to plain dicts and
truncate long lists so the context window stays bounded.

Tavily is registered only when web search is enabled (online, non-airgapped).
It is scoped to entity resolution / verification: it returns short snippets the
agent may use to map a messy term to a canonical name, but it never becomes the
answer source. Graph evidence remains the only citable ground truth.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from langchain_core.tools import StructuredTool, tool

from kg_ae.config import settings
from kg_ae.tools import (
    expand_mechanism,
    explain_paths,
    find_drug_to_ae_paths,
    get_claim_evidence,
    get_disease_genes,
    get_drug_adverse_events,
    get_drug_drug_interactions,
    get_drug_faers_signals,
    get_drug_label_sections,
    get_drug_profile,
    get_drug_targets,
    get_entity_claims,
    get_gene_diseases,
    get_gene_interactors,
    get_gene_pathways,
    resolve_adverse_events,
    resolve_diseases,
    resolve_drugs,
    resolve_genes,
)

# Maximum items to return per tool (prevents context overflow).
MAX_ITEMS_PER_TOOL = 30


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses to dicts and truncate long lists."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        truncated = obj[:MAX_ITEMS_PER_TOOL]
        out = [_to_jsonable(x) for x in truncated]
        if len(obj) > MAX_ITEMS_PER_TOOL:
            out.append({"_truncated": True, "_total": len(obj), "_shown": MAX_ITEMS_PER_TOOL})
        return out
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


# --------------------------------------------------------------------------
# Graph tools
# --------------------------------------------------------------------------
@tool
def tool_resolve_drugs(names: list[str]) -> dict:
    """Resolve drug names to integer drug keys. Call FIRST for any drug name."""
    return _to_jsonable(resolve_drugs(names))


@tool
def tool_resolve_genes(symbols: list[str]) -> dict:
    """Resolve gene symbols to integer gene keys."""
    return _to_jsonable(resolve_genes(symbols))


@tool
def tool_resolve_diseases(terms: list[str]) -> dict:
    """Resolve disease terms to integer disease keys."""
    return _to_jsonable(resolve_diseases(terms))


@tool
def tool_resolve_adverse_events(terms: list[str]) -> dict:
    """Resolve adverse-event terms (e.g. 'myopathy') to integer AE keys."""
    return _to_jsonable(resolve_adverse_events(terms))


@tool
def tool_get_drug_targets(drug_key: int) -> list:
    """Get gene/protein targets for a drug (mechanism of action). Needs a drug_key."""
    return _to_jsonable(get_drug_targets(drug_key))


@tool
def tool_get_drug_adverse_events(drug_key: int, limit: int = 50) -> list:
    """Get known adverse events for a drug (SIDER), sorted by frequency. Needs a drug_key."""
    return _to_jsonable(get_drug_adverse_events(drug_key, limit=limit))


@tool
def tool_get_drug_faers_signals(drug_key: int, top_k: int = 50) -> list:
    """Get FAERS disproportionality signals (PRR/ROR) for a drug. Needs a drug_key."""
    return _to_jsonable(get_drug_faers_signals(drug_key, top_k=top_k))


@tool
def tool_get_drug_drug_interactions(drug_a_key: int, drug_b_key: int, limit: int = 50) -> list:
    """Get adverse events reported for the COMBINATION of two drugs (TWOSIDES / polypharmacy).

    Needs two drug_keys. Use for drug-drug interaction questions.
    """
    return _to_jsonable(get_drug_drug_interactions(drug_a_key, drug_b_key, limit=limit))


@tool
def tool_get_drug_profile(drug_key: int) -> dict:
    """Get a drug summary: identifiers, targets, and top adverse events. Needs a drug_key."""
    return _to_jsonable(get_drug_profile(drug_key))


@tool
def tool_get_gene_pathways(gene_key: int) -> list:
    """Get Reactome pathways containing a gene. Needs a gene_key."""
    return _to_jsonable(get_gene_pathways(gene_key))


@tool
def tool_get_gene_diseases(gene_key: int, min_score: float = 0.0) -> list:
    """Get Open Targets disease associations for a gene. Needs a gene_key."""
    return _to_jsonable(get_gene_diseases(gene_key, min_score=min_score))


@tool
def tool_expand_mechanism(drug_key: int) -> dict:
    """Expand a drug's full mechanism: targets plus their pathways. Needs a drug_key."""
    return _to_jsonable(expand_mechanism(drug_key))


@tool
def tool_find_drug_to_ae_paths(drug_key: int, ae_key: int | None = None, max_paths: int = 5) -> list:
    """Find mechanistic paths from a drug to adverse events via gene/pathway/disease nodes."""
    return _to_jsonable(find_drug_to_ae_paths(drug_key, ae_key=ae_key, max_paths=max_paths))


@tool
def tool_explain_paths(drug_key: int, ae_key: int | None = None, top_k: int = 5) -> list:
    """Rank mechanistic drug->AE paths by evidence-weighted score (best insight tool).

    Returns the top scored explanations with their score and the node chain.
    Prefer this over raw path-finding when the question asks WHY a drug may cause
    an adverse event, so the answer is ordered by mechanistic strength. Needs a
    drug_key; pass an ae_key to focus on a specific adverse event.
    """
    return _to_jsonable(explain_paths(drug_key, ae_key=ae_key, top_k=top_k))


@tool
def tool_get_disease_genes(disease_key: int, min_score: float = 0.0, limit: int = 50) -> list:
    """Get genes associated with a disease (reverse lookup; Open Targets/CTD/ClinGen).

    Use to reason about shared mechanism: which genes drive a disease, then which
    drugs target those genes. Needs a disease_key.
    """
    return _to_jsonable(get_disease_genes(disease_key, min_score=min_score, limit=limit))


@tool
def tool_get_gene_interactors(gene_key: int, min_score: float = 0.7, limit: int = 30) -> list:
    """Get STRING protein-protein interactors of a gene (indirect mechanism).

    Use to extend a drug's mechanism one hop: drug -> target gene -> interacting
    gene -> pathway/disease. Needs a gene_key. Scores are STRING combined (0-1).
    """
    return _to_jsonable(get_gene_interactors(gene_key, min_score=min_score, limit=limit))


@tool
def tool_get_drug_label_sections(drug_key: int, sections: list[str] | None = None) -> list:
    """Get FDA label sections for a drug (openFDA): boxed warnings, contraindications, etc.

    High-value clinical context to corroborate graph-derived adverse events.
    Needs a drug_key. Optionally pass section names to filter.
    """
    return _to_jsonable(get_drug_label_sections(drug_key, sections=sections))


@tool
def tool_get_claim_evidence(claim_key: int) -> dict | None:
    """Get the full provenance/evidence trail for a specific claim_key."""
    return _to_jsonable(get_claim_evidence(claim_key))


@tool
def tool_get_entity_claims(entity_type: str, entity_key: int, limit: int = 30) -> list:
    """Get all claims for an entity. entity_type is one of Drug, Gene, Disease, Pathway, AdverseEvent."""
    return _to_jsonable(get_entity_claims(entity_type, entity_key, limit=limit))


GRAPH_TOOLS: list[StructuredTool] = [
    tool_resolve_drugs,
    tool_resolve_genes,
    tool_resolve_diseases,
    tool_resolve_adverse_events,
    tool_get_drug_targets,
    tool_get_drug_adverse_events,
    tool_get_drug_faers_signals,
    tool_get_drug_drug_interactions,
    tool_get_drug_profile,
    tool_get_gene_pathways,
    tool_get_gene_diseases,
    tool_expand_mechanism,
    tool_find_drug_to_ae_paths,
    tool_explain_paths,
    tool_get_disease_genes,
    tool_get_gene_interactors,
    tool_get_drug_label_sections,
    tool_get_claim_evidence,
    tool_get_entity_claims,
]


def _build_tavily_tool() -> StructuredTool | None:
    """Build the scoped Tavily web-search tool, or None if unavailable/disabled."""
    if not settings.web_search_enabled():
        return None
    api_key = settings.resolved_tavily_api_key()
    if not api_key:
        return None
    try:
        from langchain_tavily import TavilySearch
    except ImportError:
        try:
            # older integration package
            from langchain_community.tools.tavily_search import TavilySearchResults as TavilySearch  # type: ignore
        except ImportError:
            return None

    search = TavilySearch(max_results=3, tavily_api_key=api_key)

    @tool
    def tool_web_verify(query: str) -> Any:
        """Verify or normalize a biomedical term via web search (entity resolution only).

        Use ONLY to map a messy or unknown term to a canonical drug/gene/disease
        name, or to sanity-check an identifier. Do NOT use it as a source of
        mechanistic facts: only the graph tools provide citable evidence. Never
        send patient-specific details to this tool.
        """
        return search.invoke({"query": query})

    return tool_web_verify


def build_tools() -> list[StructuredTool]:
    """Return the active tool set: graph tools plus Tavily when enabled."""
    tools = list(GRAPH_TOOLS)
    tavily = _build_tavily_tool()
    if tavily is not None:
        tools.append(tavily)
    return tools
