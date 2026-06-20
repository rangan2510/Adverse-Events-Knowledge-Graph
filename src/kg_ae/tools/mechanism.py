"""
Mechanism expansion tools.

Expand drugs to targets (genes), genes to pathways, and genes to diseases,
plus reverse and interaction lookups. Backed by the in-memory GraphStore.
"""

from dataclasses import dataclass

from kg_ae.graph import get_store


@dataclass
class DrugTarget:
    """Drug-gene target relationship."""

    drug_key: int
    drug_name: str
    gene_key: int
    gene_symbol: str
    relation: str | None = None
    effect: str | None = None
    claim_type: str | None = None
    dataset: str | None = None


@dataclass
class GenePathway:
    """Gene-pathway membership."""

    gene_key: int
    gene_symbol: str
    pathway_key: int
    pathway_label: str
    reactome_id: str | None = None


@dataclass
class GeneDisease:
    """Gene-disease association."""

    gene_key: int
    gene_symbol: str
    disease_key: int
    disease_label: str
    score: float | None = None
    efo_id: str | None = None


def get_drug_targets(drug_key: int) -> list[DrugTarget]:
    """Get all unique gene targets for a drug (deduplicated by gene)."""
    store = get_store()
    drug_name = store.node_label("Drug", drug_key)
    by_gene: dict[int, DrugTarget] = {}
    counts: dict[int, int] = {}
    for e in store.out_edges("Drug", drug_key, dst_type="Gene"):
        counts[e.dst_key] = counts.get(e.dst_key, 0) + 1
        if e.dst_key not in by_gene:
            by_gene[e.dst_key] = DrugTarget(
                drug_key=drug_key,
                drug_name=drug_name,
                gene_key=e.dst_key,
                gene_symbol=store.node_label("Gene", e.dst_key),
                relation=e.relation,
                effect=e.effect,
                claim_type=e.claim_type,
                dataset=e.dataset,
            )
    return sorted(by_gene.values(), key=lambda t: (-counts[t.gene_key], t.gene_symbol))


def get_gene_pathways(gene_key: int) -> list[GenePathway]:
    """Get all unique pathways for a gene (deduplicated by pathway)."""
    store = get_store()
    gene_symbol = store.node_label("Gene", gene_key)
    by_pw: dict[int, GenePathway] = {}
    for e in store.out_edges("Gene", gene_key, dst_type="Pathway"):
        if e.dst_key not in by_pw:
            props = store.get_node("Pathway", e.dst_key) or {}
            by_pw[e.dst_key] = GenePathway(
                gene_key=gene_key,
                gene_symbol=gene_symbol,
                pathway_key=e.dst_key,
                pathway_label=store.node_label("Pathway", e.dst_key),
                reactome_id=props.get("reactome_id"),
            )
    return sorted(by_pw.values(), key=lambda p: p.pathway_label)


def get_gene_diseases(gene_key: int, min_score: float = 0.0) -> list[GeneDisease]:
    """Get all disease associations for a gene, sorted by score descending."""
    store = get_store()
    gene_symbol = store.node_label("Gene", gene_key)
    by_dis: dict[int, GeneDisease] = {}
    for e in store.out_edges("Gene", gene_key, dst_type="Disease"):
        score = e.strength_score
        if score is not None and score < min_score:
            continue
        existing = by_dis.get(e.dst_key)
        if existing is None or (score or 0) > (existing.score or 0):
            props = store.get_node("Disease", e.dst_key) or {}
            by_dis[e.dst_key] = GeneDisease(
                gene_key=gene_key,
                gene_symbol=gene_symbol,
                disease_key=e.dst_key,
                disease_label=store.node_label("Disease", e.dst_key),
                efo_id=props.get("efo_id"),
                score=score,
            )
    return sorted(by_dis.values(), key=lambda d: d.score or 0, reverse=True)


def expand_mechanism(drug_key: int) -> dict:
    """Expand full mechanism for a drug: targets + their pathways."""
    targets = get_drug_targets(drug_key)
    all_pathways = []
    seen_pathways = set()
    for target in targets:
        for pw in get_gene_pathways(target.gene_key):
            if pw.pathway_key not in seen_pathways:
                seen_pathways.add(pw.pathway_key)
                all_pathways.append(pw)
    return {"targets": targets, "pathways": all_pathways}


def expand_gene_context(gene_keys: list[int], min_disease_score: float = 0.3) -> dict:
    """Expand context for genes: pathways + disease associations by gene_key."""
    result: dict[str, dict] = {"pathways": {}, "diseases": {}}
    for gene_key in gene_keys:
        result["pathways"][gene_key] = get_gene_pathways(gene_key)
        result["diseases"][gene_key] = get_gene_diseases(gene_key, min_disease_score)
    return result


@dataclass
class DiseaseGene:
    """Disease-gene association (reverse of GeneDisease)."""

    disease_key: int
    disease_label: str
    gene_key: int
    gene_symbol: str
    score: float | None = None
    source: str | None = None  # opentargets, ctd, clingen, etc.


@dataclass
class GeneInteractor:
    """Gene-gene interaction from STRING."""

    gene_key: int
    gene_symbol: str
    interactor_key: int
    interactor_symbol: str
    score: float  # STRING combined score (0-1)


# Map source label -> claim_type used in the graph
_DISEASE_GENE_CLAIM_TYPES = {
    "opentargets": "GENE_DISEASE",
    "ctd": "GENE_DISEASE_CTD",
    "clingen": "GENE_DISEASE_CLINGEN",
}
_CLAIM_TYPE_TO_SOURCE = {v: k for k, v in _DISEASE_GENE_CLAIM_TYPES.items()}


def get_disease_genes(
    disease_key: int,
    sources: list[str] | None = None,
    min_score: float = 0.0,
    limit: int = 100,
) -> list[DiseaseGene]:
    """Get genes associated with a disease (reverse lookup).

    Aggregates from gene-disease sources (Open Targets, CTD, ClinGen) by
    traversing incoming Gene -> Disease edges.
    """
    store = get_store()
    allowed = (
        set(_DISEASE_GENE_CLAIM_TYPES.values())
        if sources is None
        else {_DISEASE_GENE_CLAIM_TYPES[s] for s in sources if s in _DISEASE_GENE_CLAIM_TYPES}
    )
    if not allowed:
        return []

    disease_label = store.node_label("Disease", disease_key)
    results: list[DiseaseGene] = []
    for e in store.in_edges("Disease", disease_key, src_type="Gene"):
        if e.claim_type not in allowed:
            continue
        if e.strength_score is not None and e.strength_score < min_score:
            continue
        results.append(
            DiseaseGene(
                disease_key=disease_key,
                disease_label=disease_label,
                gene_key=e.src_key,
                gene_symbol=store.node_label("Gene", e.src_key),
                score=e.strength_score,
                source=_CLAIM_TYPE_TO_SOURCE.get(e.claim_type or ""),
            )
        )
    results.sort(key=lambda d: d.score or 0, reverse=True)
    return results[:limit]


def get_gene_interactors(
    gene_key: int,
    min_score: float = 0.7,
    limit: int = 100,
) -> list[GeneInteractor]:
    """Get gene-gene interactions from STRING (claim_type GENE_GENE_STRING)."""
    store = get_store()
    gene_symbol = store.node_label("Gene", gene_key)
    results: list[GeneInteractor] = []
    for e in store.out_edges("Gene", gene_key, dst_type="Gene", claim_type="GENE_GENE_STRING"):
        if e.strength_score is None or e.strength_score < min_score:
            continue
        results.append(
            GeneInteractor(
                gene_key=gene_key,
                gene_symbol=gene_symbol,
                interactor_key=e.dst_key,
                interactor_symbol=store.node_label("Gene", e.dst_key),
                score=e.strength_score,
            )
        )
    results.sort(key=lambda g: g.score, reverse=True)
    return results[:limit]
