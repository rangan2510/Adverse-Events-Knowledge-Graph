"""
Mechanism expansion tools.

Expand drugs to targets (genes) and genes to pathways.
"""

from dataclasses import dataclass, field

from kg_ae.db import execute


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
    """
    Get all gene targets for a drug.

    Args:
        drug_key: The drug's primary key

    Returns:
        List of DrugTarget objects
    """
    rows = execute(
        """
        SELECT 
            d.drug_key, d.preferred_name,
            g.gene_key, g.symbol,
            cg.relation, cg.effect,
            c.claim_type
        FROM kg.Drug d
            , kg.HasClaim hc
            , kg.Claim c
            , kg.ClaimGene cg
            , kg.Gene g
        WHERE MATCH(d-(hc)->c-(cg)->g)
          AND d.drug_key = ?
        """,
        (drug_key,),
        commit=False,
    )
    return [
        DrugTarget(
            drug_key=row[0],
            drug_name=row[1],
            gene_key=row[2],
            gene_symbol=row[3],
            relation=row[4],
            effect=row[5],
            claim_type=row[6],
        )
        for row in rows
    ]


def get_gene_pathways(gene_key: int) -> list[GenePathway]:
    """
    Get all pathways for a gene.

    Args:
        gene_key: The gene's primary key

    Returns:
        List of GenePathway objects
    """
    rows = execute(
        """
        SELECT 
            g.gene_key, g.symbol,
            p.pathway_key, p.label, p.reactome_id
        FROM kg.Gene g
            , kg.HasClaim hc
            , kg.Claim c
            , kg.ClaimPathway cp
            , kg.Pathway p
        WHERE MATCH(g-(hc)->c-(cp)->p)
          AND g.gene_key = ?
        """,
        (gene_key,),
        commit=False,
    )
    return [
        GenePathway(
            gene_key=row[0],
            gene_symbol=row[1],
            pathway_key=row[2],
            pathway_label=row[3],
            reactome_id=row[4],
        )
        for row in rows
    ]


def get_gene_diseases(gene_key: int, min_score: float = 0.0) -> list[GeneDisease]:
    """
    Get all disease associations for a gene.

    Args:
        gene_key: The gene's primary key
        min_score: Minimum association score (0-1)

    Returns:
        List of GeneDisease objects sorted by score descending
    """
    rows = execute(
        """
        SELECT 
            g.gene_key, g.symbol,
            dis.disease_key, dis.label, dis.efo_id,
            c.strength_score
        FROM kg.Gene g
            , kg.HasClaim hc
            , kg.Claim c
            , kg.ClaimDisease cd
            , kg.Disease dis
        WHERE MATCH(g-(hc)->c-(cd)->dis)
          AND g.gene_key = ?
          AND (c.strength_score IS NULL OR c.strength_score >= ?)
        ORDER BY c.strength_score DESC
        """,
        (gene_key, min_score),
        commit=False,
    )
    return [
        GeneDisease(
            gene_key=row[0],
            gene_symbol=row[1],
            disease_key=row[2],
            disease_label=row[3],
            efo_id=row[4],
            score=row[5],
        )
        for row in rows
    ]


def expand_mechanism(drug_key: int) -> dict:
    """
    Expand full mechanism for a drug: targets + their pathways.

    Args:
        drug_key: The drug's primary key

    Returns:
        Dict with 'targets' and 'pathways' lists
    """
    targets = get_drug_targets(drug_key)
    
    all_pathways = []
    seen_pathways = set()
    
    for target in targets:
        pathways = get_gene_pathways(target.gene_key)
        for pw in pathways:
            if pw.pathway_key not in seen_pathways:
                seen_pathways.add(pw.pathway_key)
                all_pathways.append(pw)

    return {
        "targets": targets,
        "pathways": all_pathways,
    }


def expand_gene_context(gene_keys: list[int], min_disease_score: float = 0.3) -> dict:
    """
    Expand context for genes: pathways + disease associations.

    Args:
        gene_keys: List of gene primary keys
        min_disease_score: Minimum score for disease associations

    Returns:
        Dict with 'pathways' and 'diseases' by gene_key
    """
    result = {"pathways": {}, "diseases": {}}
    
    for gene_key in gene_keys:
        result["pathways"][gene_key] = get_gene_pathways(gene_key)
        result["diseases"][gene_key] = get_gene_diseases(gene_key, min_disease_score)

    return result
