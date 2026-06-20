"""
Path finding and explanation tools.

Find and rank mechanistic paths through the knowledge graph using the
GraphStore traversal primitives.
"""

from dataclasses import dataclass, field

from kg_ae.graph import get_store
from kg_ae.tools.mechanism import get_drug_targets, get_gene_diseases, get_gene_pathways


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
    """Find mechanistic paths from drug to adverse event(s).

    When ``ae_key`` is given, only paths that genuinely terminate at (or whose
    endpoint disease is associated with) that adverse event are returned, so the
    result cannot be padded with unrelated target-disease pairs. The endpoint
    AE node is always appended, making the chain Drug -> ... -> AdverseEvent.

    When ``ae_key`` is None, returns mechanistic context paths
    (Drug -> Gene -> Pathway and Drug -> Gene -> Disease) for exploration.
    """
    store = get_store()
    drug_name = store.node_label("Drug", drug_key)
    paths: list[MechanisticPath] = []

    targets = get_drug_targets(drug_key)

    if ae_key is not None:
        ae_label = store.node_label("AdverseEvent", ae_key)

        # 1. Direct Drug -> AdverseEvent edge (strongest: the graph asserts it).
        for e in store.out_edges("Drug", drug_key, dst_type="AdverseEvent"):
            if e.dst_key != ae_key:
                continue
            paths.append(
                MechanisticPath(
                    steps=[
                        PathStep("Drug", drug_key, drug_name),
                        PathStep("AdverseEvent", ae_key, ae_label, "CAUSES"),
                    ],
                    score=e.frequency or e.strength_score or 0.7,
                    evidence_count=1,
                )
            )

        # 2. Mechanistic chain that actually reaches the AE:
        #    Drug -> Gene -> Disease where that Disease is the AE label, or
        #    Drug -> Gene -> Pathway -> (gene in pathway also linked to AE).
        # We only keep a Drug -> Gene -> Disease path when the disease label
        # matches the queried adverse-event label (string-level join, since AE
        # and Disease ontologies differ). This prevents unrelated disease leaps.
        ae_label_lc = ae_label.lower().strip()
        for t in targets:
            for dis in get_gene_diseases(t.gene_key):
                if dis.disease_label.lower().strip() != ae_label_lc:
                    continue
                paths.append(
                    MechanisticPath(
                        steps=[
                            PathStep("Drug", drug_key, drug_name),
                            PathStep("Gene", t.gene_key, t.gene_symbol, "TARGETS"),
                            PathStep("Disease", dis.disease_key, dis.disease_label, "ASSOCIATED_WITH"),
                            PathStep("AdverseEvent", ae_key, ae_label, "MATCHES"),
                        ],
                        score=(dis.score or 0.5) * 0.9,
                        evidence_count=2,
                    )
                )

        paths.sort(key=lambda p: p.score, reverse=True)
        return paths[:max_paths]

    # No specific AE: return mechanistic context paths for exploration.
    # Path type 2: Drug -> Gene -> Pathway
    for t in targets:
        for pw in get_gene_pathways(t.gene_key):
            paths.append(
                MechanisticPath(
                    steps=[
                        PathStep("Drug", drug_key, drug_name),
                        PathStep("Gene", t.gene_key, t.gene_symbol, "TARGETS"),
                        PathStep("Pathway", pw.pathway_key, pw.pathway_label, "IN_PATHWAY"),
                    ],
                    score=0.8,
                    evidence_count=2,
                )
            )
            if len(paths) >= max_paths * 3:
                break

    # Path type 3: Drug -> Gene -> Disease
    for t in targets:
        for dis in get_gene_diseases(t.gene_key):
            paths.append(
                MechanisticPath(
                    steps=[
                        PathStep("Drug", drug_key, drug_name),
                        PathStep("Gene", t.gene_key, t.gene_symbol, "TARGETS"),
                        PathStep("Disease", dis.disease_key, dis.disease_label, "ASSOCIATED_WITH"),
                    ],
                    score=dis.score or 0.5,
                    evidence_count=2,
                )
            )
            if len(paths) >= max_paths * 4:
                break

    paths.sort(key=lambda p: p.score, reverse=True)
    return paths[:max_paths]


def explain_paths(
    drug_key: int,
    ae_key: int | None = None,
    condition_keys: list[int] | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Generate ranked mechanistic explanations for a drug-AE relationship."""
    paths = find_drug_to_ae_paths(drug_key, ae_key, max_paths=top_k * 2)

    if condition_keys:
        condition_set = set(condition_keys)
        for path in paths:
            for step in path.steps:
                if step.node_type == "Disease" and step.node_key in condition_set:
                    path.score *= 1.5  # boost relevance

    paths.sort(key=lambda p: p.score, reverse=True)
    return [p.to_dict() for p in paths[:top_k]]


@dataclass
class ScoringPolicy:
    """Policy for scoring mechanistic paths."""

    source_weights: dict[str, float] = field(
        default_factory=lambda: {
            "drugcentral": 1.0,
            "opentargets": 0.95,
            "chembl": 0.9,
            "reactome": 0.9,
            "gtop": 0.85,
            "sider": 0.8,
            "clingen": 0.85,
            "ctd": 0.7,
            "string": 0.6,
            "faers": 0.5,
            "openfda": 0.5,
            "hpo": 0.7,
        }
    )
    multi_source_bonus: float = 1.2
    min_evidence: int = 1
    length_penalty: float = 0.95


def score_paths(
    paths: list[MechanisticPath],
    policy: ScoringPolicy | None = None,
) -> list[MechanisticPath]:
    """Score and rank mechanistic paths using a deterministic policy."""
    if policy is None:
        policy = ScoringPolicy()

    scored_paths = []
    for path in paths:
        if path.evidence_count < policy.min_evidence:
            continue
        score = path.score if path.score else 0.5
        num_hops = len(path.steps) - 1
        if num_hops > 0:
            score *= policy.length_penalty**num_hops
        if path.evidence_count > 1:
            score *= policy.multi_source_bonus
        path.score = score
        scored_paths.append(path)

    scored_paths.sort(key=lambda p: p.score, reverse=True)
    return scored_paths


def score_paths_with_evidence(
    paths: list[MechanisticPath],
    policy: ScoringPolicy | None = None,
) -> list[dict]:
    """Score paths and return a per-path breakdown for explainability."""
    if policy is None:
        policy = ScoringPolicy()

    breakdowns: list[dict] = []
    for path in paths:
        if path.evidence_count < policy.min_evidence:
            continue
        base = path.score if path.score else 0.5
        num_hops = max(len(path.steps) - 1, 0)
        length_factor = policy.length_penalty**num_hops
        multi_source = policy.multi_source_bonus if path.evidence_count > 1 else 1.0
        final = base * length_factor * multi_source
        breakdowns.append(
            {
                "path": str(path),
                "scoring": {
                    "base_score": base,
                    "num_hops": num_hops,
                    "length_factor": length_factor,
                    "multi_source_factor": multi_source,
                    "evidence_count": path.evidence_count,
                    "final_score": final,
                },
                "final_score": final,
            }
        )
    breakdowns.sort(key=lambda b: b["final_score"], reverse=True)
    return breakdowns
