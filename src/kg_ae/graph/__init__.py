"""
File-based knowledge graph layer.

Provides:
- GraphStore: in-memory graph loaded from data/graph/*.json
- GraphBuilder / build_graph: build the JSON graph from silver Parquet
"""

from kg_ae.graph.build import GraphBuilder, build_graph
from kg_ae.graph.store import GraphEdge, GraphStore, get_store

__all__ = ["GraphStore", "GraphEdge", "get_store", "GraphBuilder", "build_graph"]
