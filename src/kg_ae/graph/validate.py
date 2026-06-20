"""
Graph artifact validation.

Enforces the invariants documented in ``schemas/graph.schema.json`` without a
heavyweight JSON-Schema dependency, so it is fast over hundreds of thousands of
edges. Used by the builder (fail-fast at staging time) and by
``kg-ae stage verify``.

Checked invariants:
- node types are from the allowed set
- every node key is an integer (as stored)
- every edge has the required fields
- every edge endpoint references an existing node (no orphan edges)
"""

from __future__ import annotations

from typing import Any

ALLOWED_NODE_TYPES = {"Drug", "Gene", "Pathway", "Disease", "AdverseEvent", "DrugCombination"}
REQUIRED_EDGE_FIELDS = ("src_type", "src_key", "dst_type", "dst_key", "edge", "claim_type", "dataset")


def validate_graph(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    """Return a list of validation errors. Empty list means valid.

    Args:
        nodes: {node_type: {key(str): props}} as written to nodes.json
        edges: list of edge dicts as written to edges.json
    """
    errors: list[str] = []

    # 1. Node types valid; build a key index per type for orphan checks.
    index: dict[str, set[int]] = {}
    for node_type, by_key in nodes.items():
        if node_type not in ALLOWED_NODE_TYPES:
            errors.append(f"unknown node type: {node_type}")
            continue
        keys: set[int] = set()
        for k in by_key:
            try:
                keys.add(int(k))
            except (TypeError, ValueError):
                errors.append(f"non-integer node key in {node_type}: {k!r}")
        index[node_type] = keys

    # 2. Edges: required fields + endpoints resolve to existing nodes.
    orphan_src = 0
    orphan_dst = 0
    missing_fields = 0
    for e in edges:
        if any(f not in e for f in REQUIRED_EDGE_FIELDS):
            missing_fields += 1
            continue
        st, sk = e["src_type"], e["src_key"]
        dt, dk = e["dst_type"], e["dst_key"]
        if st not in index or int(sk) not in index[st]:
            orphan_src += 1
        if dt not in index or int(dk) not in index[dt]:
            orphan_dst += 1

    if missing_fields:
        errors.append(f"{missing_fields} edges missing required fields {REQUIRED_EDGE_FIELDS}")
    if orphan_src:
        errors.append(f"{orphan_src} edges reference a missing source node")
    if orphan_dst:
        errors.append(f"{orphan_dst} edges reference a missing destination node")

    return errors
