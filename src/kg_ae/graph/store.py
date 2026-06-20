"""
File-based knowledge graph store.

Replaces the SQL Server graph database with a set of JSON files loaded into
memory. This keeps the runtime fully local and airgap-friendly: no database
server, no driver, no network. The graph itself contains only public
biomedical reference data (no patient data), so it can be shipped as a build
artifact into an airgapped environment.

Layout of ``data/graph/``::

    nodes.json    {node_type: {key(str): {property: value, ...}}}
    edges.json    flattened entity->entity edges carrying the connecting
                  Claim payload:
                  [
                    {
                      "src_type": "Drug", "src_key": 42,
                      "dst_type": "Gene", "dst_key": 7,
                      "edge": "ClaimGene",
                      "claim_key": 1001,
                      "claim_type": "DRUG_TARGET",
                      "strength_score": 0.9,
                      "frequency": null,
                      "relation": "inhibitor",
                      "effect": "antagonist",
                      "polarity": -1,
                      "dataset": "drugcentral",
                      "meta": {...},
                      "statement": {...},
                      "evidence": [{...}, ...]
                    },
                    ...
                  ]
    meta.json     {"datasets": {...}, "built_at": "...", "counts": {...}}

The original SQL schema modelled associations as first-class ``Claim`` nodes
wired to entities via ``HasClaim`` / ``ClaimGene`` / etc. and to ``Evidence``
via ``SupportedBy``. We flatten that ``Entity-(HasClaim)->Claim-(ClaimX)->Entity``
pattern into a single edge record that still carries the full claim payload and
its evidence list, so provenance is preserved end to end.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from kg_ae.config import settings

# Node type -> the property that holds the human-facing label / name.
NODE_LABEL_FIELD: dict[str, str] = {
    "Drug": "preferred_name",
    "Gene": "symbol",
    "Pathway": "label",
    "Disease": "label",
    "AdverseEvent": "ae_label",
    "DrugCombination": "label",
}


@dataclass
class GraphEdge:
    """A flattened entity->entity edge carrying its Claim payload."""

    src_type: str
    src_key: int
    dst_type: str
    dst_key: int
    edge: str
    claim_key: int | None = None
    claim_type: str | None = None
    strength_score: float | None = None
    frequency: float | None = None
    relation: str | None = None
    effect: str | None = None
    polarity: int | None = None
    dataset: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    statement: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)


class GraphStore:
    """In-memory knowledge graph loaded from JSON files.

    Construct via :func:`get_store` so the (expensive) load happens once per
    process.
    """

    def __init__(self, graph_dir: Path) -> None:
        self.graph_dir = graph_dir
        self._nodes: dict[str, dict[int, dict[str, Any]]] = {}
        # adjacency[(src_type, src_key)] -> list[GraphEdge]
        self._out: dict[tuple[str, int], list[GraphEdge]] = defaultdict(list)
        # reverse adjacency for dst-keyed lookups (e.g. disease -> genes)
        self._in: dict[tuple[str, int], list[GraphEdge]] = defaultdict(list)
        # claim_key -> GraphEdge (for evidence lookups)
        self._claims: dict[int, GraphEdge] = {}
        # name_index[node_type][lowercased name] -> list[key]
        self._name_index: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        self.meta: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _load(self) -> None:
        nodes_path = self.graph_dir / "nodes.json"
        edges_path = self.graph_dir / "edges.json"
        meta_path = self.graph_dir / "meta.json"

        if not nodes_path.exists() or not edges_path.exists():
            raise FileNotFoundError(
                f"Graph not built. Expected {nodes_path} and {edges_path}. Run `uv run kg-ae build-graph` first."
            )

        raw_nodes = json.loads(nodes_path.read_text(encoding="utf-8"))
        for node_type, by_key in raw_nodes.items():
            self._nodes[node_type] = {int(k): v for k, v in by_key.items()}
            label_field = NODE_LABEL_FIELD.get(node_type)
            if label_field:
                for key, props in self._nodes[node_type].items():
                    label = props.get(label_field)
                    if isinstance(label, str) and label:
                        self._name_index[node_type][label.lower().strip()].append(key)

        raw_edges = json.loads(edges_path.read_text(encoding="utf-8"))
        for e in raw_edges:
            edge = GraphEdge(
                src_type=e["src_type"],
                src_key=int(e["src_key"]),
                dst_type=e["dst_type"],
                dst_key=int(e["dst_key"]),
                edge=e["edge"],
                claim_key=e.get("claim_key"),
                claim_type=e.get("claim_type"),
                strength_score=e.get("strength_score"),
                frequency=e.get("frequency"),
                relation=e.get("relation"),
                effect=e.get("effect"),
                polarity=e.get("polarity"),
                dataset=e.get("dataset"),
                meta=e.get("meta") or {},
                statement=e.get("statement") or {},
                evidence=e.get("evidence") or [],
            )
            self._out[(edge.src_type, edge.src_key)].append(edge)
            self._in[(edge.dst_type, edge.dst_key)].append(edge)
            if edge.claim_key is not None:
                self._claims[edge.claim_key] = edge

        if meta_path.exists():
            self.meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Node access
    # ------------------------------------------------------------------
    def get_node(self, node_type: str, key: int) -> dict[str, Any] | None:
        """Return the property dict for a node, or None if absent."""
        return self._nodes.get(node_type, {}).get(key)

    def node_label(self, node_type: str, key: int) -> str:
        """Return the human-facing label for a node (empty string if unknown)."""
        props = self.get_node(node_type, key) or {}
        field_name = NODE_LABEL_FIELD.get(node_type, "label")
        return str(props.get(field_name, "")) or ""

    def all_nodes(self, node_type: str) -> dict[int, dict[str, Any]]:
        """Return all nodes of a type as {key: properties}."""
        return self._nodes.get(node_type, {})

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def find_by_name(self, node_type: str, name: str) -> list[int]:
        """Exact (case-insensitive) name match. Returns matching keys."""
        return list(self._name_index.get(node_type, {}).get(name.lower().strip(), []))

    def find_by_partial_name(self, node_type: str, fragment: str, limit: int = 25) -> list[int]:
        """Substring (case-insensitive) name match. Returns matching keys."""
        frag = fragment.lower().strip()
        hits: list[int] = []
        for name, keys in self._name_index.get(node_type, {}).items():
            if frag in name:
                hits.extend(keys)
                if len(hits) >= limit:
                    break
        return hits[:limit]

    # ------------------------------------------------------------------
    # Edge traversal
    # ------------------------------------------------------------------
    def out_edges(
        self,
        src_type: str,
        src_key: int,
        dst_type: str | None = None,
        claim_type: str | None = None,
    ) -> list[GraphEdge]:
        """Outgoing edges from a node, optionally filtered by dst type / claim type."""
        edges = self._out.get((src_type, src_key), [])
        return self._filter(edges, dst_type, claim_type)

    def in_edges(
        self,
        dst_type: str,
        dst_key: int,
        src_type: str | None = None,
        claim_type: str | None = None,
    ) -> list[GraphEdge]:
        """Incoming edges to a node, optionally filtered by src type / claim type."""
        edges = self._in.get((dst_type, dst_key), [])
        out: list[GraphEdge] = []
        for e in edges:
            if src_type is not None and e.src_type != src_type:
                continue
            if claim_type is not None and e.claim_type != claim_type:
                continue
            out.append(e)
        return out

    @staticmethod
    def _filter(
        edges: list[GraphEdge],
        dst_type: str | None,
        claim_type: str | None,
    ) -> list[GraphEdge]:
        out: list[GraphEdge] = []
        for e in edges:
            if dst_type is not None and e.dst_type != dst_type:
                continue
            if claim_type is not None and e.claim_type != claim_type:
                continue
            out.append(e)
        return out

    def get_claim(self, claim_key: int) -> GraphEdge | None:
        """Return the edge (with claim payload + evidence) for a claim key."""
        return self._claims.get(claim_key)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    def counts(self) -> dict[str, int]:
        """Return node counts by type plus total edges."""
        out = {nt: len(by_key) for nt, by_key in self._nodes.items()}
        out["edges"] = sum(len(v) for v in self._out.values())
        return out


@lru_cache(maxsize=1)
def get_store() -> GraphStore:
    """Return the process-wide GraphStore, loading it on first use."""
    return GraphStore(settings.graph_dir)
