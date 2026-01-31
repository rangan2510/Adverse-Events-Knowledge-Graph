"""
Subgraph extraction tools.

Build and export subgraphs from the knowledge graph.
"""

from dataclasses import dataclass, field
from typing import Any

from kg_ae.db import execute


@dataclass
class Node:
    """Graph node."""
    id: str
    type: str
    label: str
    properties: dict = field(default_factory=dict)


@dataclass
class Edge:
    """Graph edge."""
    source: str
    target: str
    type: str
    weight: float = 1.0
    properties: dict = field(default_factory=dict)


@dataclass
class Subgraph:
    """Extracted subgraph."""
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "nodes": [
                {"id": n.id, "type": n.type, "label": n.label, **n.properties}
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "type": e.type,
                    "weight": e.weight,
                    **e.properties,
                }
                for e in self.edges
            ],
        }

    def to_cytoscape(self) -> dict:
        """Convert to Cytoscape.js format."""
        elements = []
        for n in self.nodes:
            elements.append({
                "data": {"id": n.id, "label": n.label, "type": n.type, **n.properties},
                "group": "nodes",
            })
        for e in self.edges:
            elements.append({
                "data": {
                    "source": e.source,
                    "target": e.target,
                    "type": e.type,
                    "weight": e.weight,
                    **e.properties,
                },
                "group": "edges",
            })
        return {"elements": elements}


def build_subgraph(
    drug_keys: list[int],
    include_targets: bool = True,
    include_pathways: bool = True,
    include_diseases: bool = True,
    include_aes: bool = True,
    max_pathways_per_gene: int = 5,
    max_diseases_per_gene: int = 5,
    max_aes_per_drug: int = 10,
    min_disease_score: float = 0.3,
) -> Subgraph:
    """
    Build a subgraph centered on given drugs.

    Args:
        drug_keys: List of drug primary keys
        include_targets: Include drug→gene edges
        include_pathways: Include gene→pathway edges
        include_diseases: Include gene→disease edges
        include_aes: Include drug→AE edges
        max_pathways_per_gene: Limit pathways per gene
        max_diseases_per_gene: Limit diseases per gene
        max_aes_per_drug: Limit AEs per drug
        min_disease_score: Minimum disease association score

    Returns:
        Subgraph object
    """
    from kg_ae.tools.mechanism import get_drug_targets, get_gene_pathways, get_gene_diseases
    from kg_ae.tools.adverse_events import get_drug_adverse_events

    graph = Subgraph()
    seen_nodes = set()
    seen_edges = set()

    def add_node(node_id: str, node_type: str, label: str, **props):
        if node_id not in seen_nodes:
            seen_nodes.add(node_id)
            graph.nodes.append(Node(id=node_id, type=node_type, label=label, properties=props))

    def add_edge(source: str, target: str, edge_type: str, weight: float = 1.0, **props):
        edge_key = (source, target, edge_type)
        if edge_key not in seen_edges:
            seen_edges.add(edge_key)
            graph.edges.append(Edge(source=source, target=target, type=edge_type, weight=weight, properties=props))

    gene_keys = set()

    for drug_key in drug_keys:
        # Get drug info
        rows = execute(
            "SELECT drug_key, preferred_name FROM kg.Drug WHERE drug_key = ?",
            (drug_key,),
            commit=False,
        )
        if not rows:
            continue
        drug_id = f"drug:{drug_key}"
        add_node(drug_id, "Drug", rows[0][1])

        # Drug → Gene targets
        if include_targets:
            targets = get_drug_targets(drug_key)
            for t in targets:
                gene_id = f"gene:{t.gene_key}"
                add_node(gene_id, "Gene", t.gene_symbol)
                add_edge(drug_id, gene_id, "TARGETS", relation=t.relation, effect=t.effect)
                gene_keys.add(t.gene_key)

        # Drug → AE
        if include_aes:
            aes = get_drug_adverse_events(drug_key, limit=max_aes_per_drug)
            for ae in aes:
                ae_id = f"ae:{ae.ae_key}"
                add_node(ae_id, "AdverseEvent", ae.ae_label)
                add_edge(drug_id, ae_id, "CAUSES", weight=ae.frequency or 0.01, frequency=ae.frequency)

    # Gene → Pathway
    if include_pathways:
        for gene_key in gene_keys:
            gene_id = f"gene:{gene_key}"
            pathways = get_gene_pathways(gene_key)[:max_pathways_per_gene]
            for pw in pathways:
                pw_id = f"pathway:{pw.pathway_key}"
                add_node(pw_id, "Pathway", pw.pathway_label, reactome_id=pw.reactome_id)
                add_edge(gene_id, pw_id, "IN_PATHWAY")

    # Gene → Disease
    if include_diseases:
        for gene_key in gene_keys:
            gene_id = f"gene:{gene_key}"
            diseases = get_gene_diseases(gene_key, min_score=min_disease_score)[:max_diseases_per_gene]
            for dis in diseases:
                dis_id = f"disease:{dis.disease_key}"
                add_node(dis_id, "Disease", dis.disease_label, efo_id=dis.efo_id)
                add_edge(gene_id, dis_id, "ASSOCIATED_WITH", weight=dis.score or 0.5, score=dis.score)

    return graph


def score_edges(graph: Subgraph, weights: dict[str, float] | None = None) -> Subgraph:
    """
    Apply evidence-based scoring to graph edges.

    Default weights prioritize:
    - Curated interactions > label-listed AE > FAERS signals

    Args:
        graph: Input subgraph
        weights: Optional custom weights by edge type

    Returns:
        Subgraph with updated edge weights
    """
    default_weights = {
        "TARGETS": 1.0,      # Curated drug-target
        "IN_PATHWAY": 0.9,   # Curated pathway membership
        "ASSOCIATED_WITH": 0.8,  # Gene-disease from Open Targets
        "CAUSES": 0.7,       # Drug-AE from SIDER
    }
    weights = weights or default_weights

    for edge in graph.edges:
        base_weight = weights.get(edge.type, 0.5)
        # Incorporate existing weight (e.g., frequency, score)
        if edge.weight and edge.weight > 0:
            edge.weight = base_weight * edge.weight
        else:
            edge.weight = base_weight

    return graph
