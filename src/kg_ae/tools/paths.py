"""
Path finding and explanation tools.

Find and rank mechanistic paths through the knowledge graph.
"""

from dataclasses import dataclass, field

from kg_ae.db import execute


@dataclass
class PathStep:
    """Single step in a path."""
    node_type: str
    node_key: int
    node_label: str
    edge_type: str | None = None  # Edge leading to this node


@dataclass
class MechanisticPath:
    """A ranked path through the knowledge graph."""
    steps: list[PathStep] = field(default_factory=list)
    score: float = 0.0
    evidence_count: int = 0

    def __str__(self) -> str:
        parts = []
        for i, step in enumerate(self.steps):
            if i > 0 and step.edge_type:
                parts.append(f" --[{step.edge_type}]--> ")
            parts.append(f"{step.node_type}:{step.node_label}")
        return "".join(parts)

    def to_dict(self) -> dict:
        return {
            "path": [
                {
                    "type": s.node_type,
                    "key": s.node_key,
                    "label": s.node_label,
                    "edge": s.edge_type,
                }
                for s in self.steps
            ],
            "score": self.score,
            "evidence_count": self.evidence_count,
        }


def find_drug_to_ae_paths(
    drug_key: int,
    ae_key: int | None = None,
    max_paths: int = 10,
) -> list[MechanisticPath]:
    """
    Find mechanistic paths from drug to adverse event(s).

    Paths: Drug → Gene → (Pathway|Disease) → (connection to AE via shared genes)

    Args:
        drug_key: Starting drug
        ae_key: Specific AE to find paths to, or None for all AEs
        max_paths: Maximum paths to return

    Returns:
        List of MechanisticPath sorted by score
    """
    paths = []

    # Path type 1: Drug → Gene → Disease (where disease relates to AE)
    if ae_key:
        # Direct drug-AE path
        rows = execute(
            """
            SELECT 
                d.drug_key, d.preferred_name,
                ae.ae_key, ae.ae_label,
                cae.frequency
            FROM kg.Drug d
                , kg.HasClaim hc
                , kg.Claim c
                , kg.ClaimAdverseEvent cae
                , kg.AdverseEvent ae
            WHERE MATCH(d-(hc)->c-(cae)->ae)
              AND d.drug_key = ?
              AND ae.ae_key = ?
            """,
            (drug_key, ae_key),
            commit=False,
        )
        for row in rows:
            path = MechanisticPath(
                steps=[
                    PathStep("Drug", row[0], row[1]),
                    PathStep("AdverseEvent", row[2], row[3], edge_type="CAUSES"),
                ],
                score=row[4] or 0.5,
                evidence_count=1,
            )
            paths.append(path)

    # Path type 2: Drug → Gene → Pathway (mechanistic context)
    rows = execute(
        f"""
        SELECT TOP {max_paths}
            d.drug_key, d.preferred_name,
            g.gene_key, g.symbol,
            p.pathway_key, p.label
        FROM kg.Drug d
            , kg.HasClaim hc1
            , kg.Claim c1
            , kg.ClaimGene cg
            , kg.Gene g
            , kg.HasClaim hc2
            , kg.Claim c2
            , kg.ClaimPathway cp
            , kg.Pathway p
        WHERE MATCH(d-(hc1)->c1-(cg)->g)
          AND MATCH(g-(hc2)->c2-(cp)->p)
          AND d.drug_key = ?
        """,
        (drug_key,),
        commit=False,
    )
    for row in rows:
        path = MechanisticPath(
            steps=[
                PathStep("Drug", row[0], row[1]),
                PathStep("Gene", row[2], row[3], edge_type="TARGETS"),
                PathStep("Pathway", row[4], row[5], edge_type="IN_PATHWAY"),
            ],
            score=0.8,
            evidence_count=2,
        )
        paths.append(path)

    # Path type 3: Drug → Gene → Disease
    rows = execute(
        f"""
        SELECT TOP {max_paths}
            d.drug_key, d.preferred_name,
            g.gene_key, g.symbol,
            dis.disease_key, dis.label,
            c2.strength_score
        FROM kg.Drug d
            , kg.HasClaim hc1
            , kg.Claim c1
            , kg.ClaimGene cg
            , kg.Gene g
            , kg.HasClaim hc2
            , kg.Claim c2
            , kg.ClaimDisease cd
            , kg.Disease dis
        WHERE MATCH(d-(hc1)->c1-(cg)->g)
          AND MATCH(g-(hc2)->c2-(cd)->dis)
          AND d.drug_key = ?
        ORDER BY c2.strength_score DESC
        """,
        (drug_key,),
        commit=False,
    )
    for row in rows:
        path = MechanisticPath(
            steps=[
                PathStep("Drug", row[0], row[1]),
                PathStep("Gene", row[2], row[3], edge_type="TARGETS"),
                PathStep("Disease", row[4], row[5], edge_type="ASSOCIATED_WITH"),
            ],
            score=row[6] or 0.5,
            evidence_count=2,
        )
        paths.append(path)

    # Sort by score and return top paths
    paths.sort(key=lambda p: p.score, reverse=True)
    return paths[:max_paths]


def explain_paths(
    drug_key: int,
    ae_key: int | None = None,
    condition_keys: list[int] | None = None,
    top_k: int = 5,
) -> list[dict]:
    """
    Generate ranked mechanistic explanations for drug-AE relationship.

    Args:
        drug_key: The drug to explain
        ae_key: Optional specific AE to explain
        condition_keys: Optional patient conditions (disease_keys) for context
        top_k: Number of top paths to return

    Returns:
        List of path explanations with scores
    """
    paths = find_drug_to_ae_paths(drug_key, ae_key, max_paths=top_k * 2)

    # If conditions provided, boost paths that go through those diseases
    if condition_keys:
        condition_set = set(condition_keys)
        for path in paths:
            for step in path.steps:
                if step.node_type == "Disease" and step.node_key in condition_set:
                    path.score *= 1.5  # Boost relevance

    # Re-sort after boosting
    paths.sort(key=lambda p: p.score, reverse=True)

    return [p.to_dict() for p in paths[:top_k]]
