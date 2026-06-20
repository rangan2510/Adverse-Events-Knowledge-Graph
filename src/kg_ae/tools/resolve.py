"""
Entity resolution tools.

Resolve drug names, gene symbols, disease terms, and adverse-event labels to
canonical integer keys using the in-memory GraphStore.
"""

from dataclasses import dataclass

from kg_ae.graph import get_store


@dataclass
class ResolvedEntity:
    """Resolved entity with confidence."""

    key: int
    name: str
    source: str
    confidence: float = 1.0


def _prefer_richer(node_type: str, keys: list[int]) -> int:
    """For drugs, prefer the record carrying a drugcentral_id (richer data)."""
    if node_type != "Drug":
        return keys[0]
    store = get_store()
    for key in keys:
        props = store.get_node("Drug", key) or {}
        if props.get("drugcentral_id"):
            return key
    return keys[0]


def _resolve(node_type: str, query: str, label_source: str, partial_conf: float = 0.8) -> ResolvedEntity | None:
    store = get_store()
    q = query.strip()

    exact = store.find_by_name(node_type, q)
    if exact:
        key = _prefer_richer(node_type, exact)
        return ResolvedEntity(key=key, name=store.node_label(node_type, key), source=label_source, confidence=1.0)

    partial = store.find_by_partial_name(node_type, q)
    if partial:
        # shortest label wins (closest to the query)
        key = min(partial, key=lambda k: len(store.node_label(node_type, k)))
        return ResolvedEntity(
            key=key,
            name=store.node_label(node_type, key),
            source=f"{label_source}_partial",
            confidence=partial_conf,
        )
    return None


def resolve_drugs(names: list[str]) -> dict[str, ResolvedEntity | None]:
    """Resolve drug names to drug_key. Prefers records with a drugcentral_id."""
    return {name: _resolve("Drug", name, "preferred_name") for name in names}


def resolve_genes(symbols: list[str]) -> dict[str, ResolvedEntity | None]:
    """Resolve gene symbols to gene_key."""
    return {symbol: _resolve("Gene", symbol, "symbol") for symbol in symbols}


def resolve_diseases(terms: list[str]) -> dict[str, ResolvedEntity | None]:
    """Resolve disease terms to disease_key."""
    return {term: _resolve("Disease", term, "label", partial_conf=0.7) for term in terms}


def resolve_adverse_events(terms: list[str]) -> dict[str, ResolvedEntity | None]:
    """Resolve adverse-event labels to ae_key.

    Critical for user queries mentioning AE terms like "myopathy", "hepatotoxicity".
    """
    return {term: _resolve("AdverseEvent", term, "ae_label", partial_conf=0.7) for term in terms}
