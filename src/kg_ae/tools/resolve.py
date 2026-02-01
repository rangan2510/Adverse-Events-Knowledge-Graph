"""
Entity resolution tools.

Resolve drug names, gene symbols, and disease terms to canonical IDs.
"""

from dataclasses import dataclass

from kg_ae.db import execute


@dataclass
class ResolvedEntity:
    """Resolved entity with confidence."""
    key: int
    name: str
    source: str
    confidence: float = 1.0


def resolve_drugs(names: list[str]) -> dict[str, ResolvedEntity | None]:
    """
    Resolve drug names to drug_key.

    Prefers drugs with more identifiers (e.g., drugcentral_id) for richer data.

    Args:
        names: List of drug names to resolve

    Returns:
        Dict mapping input name to ResolvedEntity or None if not found
    """
    results = {}
    for name in names:
        name_lower = name.lower().strip()
        
        # Try exact match, prefer records with drugcentral_id (richer data)
        rows = execute(
            """
            SELECT drug_key, preferred_name, drugcentral_id
            FROM kg.Drug
            WHERE LOWER(preferred_name) = ?
            ORDER BY CASE WHEN drugcentral_id IS NOT NULL THEN 0 ELSE 1 END
            """,
            (name_lower,),
            commit=False,
        )
        if rows:
            results[name] = ResolvedEntity(
                key=rows[0][0],
                name=rows[0][1],
                source="preferred_name",
                confidence=1.0,
            )
            continue

        # Try LIKE match, prefer records with identifiers
        rows = execute(
            """
            SELECT TOP 1 drug_key, preferred_name
            FROM kg.Drug
            WHERE LOWER(preferred_name) LIKE ?
            ORDER BY CASE WHEN drugcentral_id IS NOT NULL THEN 0 ELSE 1 END, LEN(preferred_name)
            """,
            (f"%{name_lower}%",),
            commit=False,
        )
        if rows:
            results[name] = ResolvedEntity(
                key=rows[0][0],
                name=rows[0][1],
                source="preferred_name_partial",
                confidence=0.8,
            )
            continue

        results[name] = None

    return results


def resolve_genes(symbols: list[str]) -> dict[str, ResolvedEntity | None]:
    """
    Resolve gene symbols to gene_key.

    Args:
        symbols: List of gene symbols

    Returns:
        Dict mapping input symbol to ResolvedEntity or None
    """
    results = {}
    for symbol in symbols:
        symbol_upper = symbol.upper().strip()
        
        rows = execute(
            """
            SELECT gene_key, symbol
            FROM kg.Gene
            WHERE UPPER(symbol) = ?
            """,
            (symbol_upper,),
            commit=False,
        )
        if rows:
            results[symbol] = ResolvedEntity(
                key=rows[0][0],
                name=rows[0][1],
                source="symbol",
                confidence=1.0,
            )
        else:
            results[symbol] = None

    return results


def resolve_diseases(terms: list[str]) -> dict[str, ResolvedEntity | None]:
    """
    Resolve disease terms to disease_key.

    Args:
        terms: List of disease terms

    Returns:
        Dict mapping input term to ResolvedEntity or None
    """
    results = {}
    for term in terms:
        term_lower = term.lower().strip()
        
        # Exact match
        rows = execute(
            """
            SELECT disease_key, label
            FROM kg.Disease
            WHERE LOWER(label) = ?
            """,
            (term_lower,),
            commit=False,
        )
        if rows:
            results[term] = ResolvedEntity(
                key=rows[0][0],
                name=rows[0][1],
                source="label",
                confidence=1.0,
            )
            continue

        # Partial match
        rows = execute(
            """
            SELECT TOP 1 disease_key, label
            FROM kg.Disease
            WHERE LOWER(label) LIKE ?
            ORDER BY LEN(label)
            """,
            (f"%{term_lower}%",),
            commit=False,
        )
        if rows:
            results[term] = ResolvedEntity(
                key=rows[0][0],
                name=rows[0][1],
                source="label_partial",
                confidence=0.7,
            )
            continue

        results[term] = None

    return results


def resolve_adverse_events(terms: list[str]) -> dict[str, ResolvedEntity | None]:
    """
    Resolve adverse event terms to ae_key.

    Uses exact match, then partial match on ae_label.
    Critical for user queries mentioning AE terms like "myopathy", "hepatotoxicity".

    Args:
        terms: List of adverse event terms to resolve

    Returns:
        Dict mapping input term to ResolvedEntity or None if not found
    """
    results = {}
    for term in terms:
        term_lower = term.lower().strip()

        # Exact match on ae_label
        rows = execute(
            """
            SELECT ae_key, ae_label
            FROM kg.AdverseEvent
            WHERE LOWER(ae_label) = ?
            """,
            (term_lower,),
            commit=False,
        )
        if rows:
            results[term] = ResolvedEntity(
                key=rows[0][0],
                name=rows[0][1],
                source="ae_label",
                confidence=1.0,
            )
            continue

        # Partial match on ae_label
        rows = execute(
            """
            SELECT TOP 1 ae_key, ae_label
            FROM kg.AdverseEvent
            WHERE LOWER(ae_label) LIKE ?
            ORDER BY LEN(ae_label)
            """,
            (f"%{term_lower}%",),
            commit=False,
        )
        if rows:
            results[term] = ResolvedEntity(
                key=rows[0][0],
                name=rows[0][1],
                source="ae_label_partial",
                confidence=0.7,
            )
            continue

        # Try matching via ae_code if provided (e.g., MedDRA codes)
        rows = execute(
            """
            SELECT TOP 1 ae_key, ae_label
            FROM kg.AdverseEvent
            WHERE ae_code = ?
            """,
            (term,),
            commit=False,
        )
        if rows:
            results[term] = ResolvedEntity(
                key=rows[0][0],
                name=rows[0][1],
                source="ae_code",
                confidence=1.0,
            )
            continue

        results[term] = None

    return results
