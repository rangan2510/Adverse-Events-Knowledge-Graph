"""
Example: Query the knowledge graph using tools.

Usage: uv run python scripts/test_tools.py
"""

from kg_ae.tools import (
    build_subgraph,
    expand_mechanism,
    explain_paths,
    get_drug_profile,
    resolve_drugs,
)

# Resolve drug names to IDs
drugs = resolve_drugs(["atorvastatin", "metformin"])
atorvastatin = drugs["atorvastatin"]

print(f"Resolved: atorvastatin -> drug_key={atorvastatin.key}")

# Get drug profile (targets + AEs)
profile = get_drug_profile(atorvastatin.key)
print(f"\nTargets: {[t['symbol'] for t in profile['targets']]}")

# Expand mechanism (targets + pathways)
mechanism = expand_mechanism(atorvastatin.key)
print(f"Pathways: {[p.pathway_label[:30] for p in mechanism['pathways'][:5]]}")

# Build subgraph for visualization
graph = build_subgraph([atorvastatin.key], max_pathways_per_gene=3)
print(f"\nSubgraph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

# Export to Cytoscape format
cytoscape_data = graph.to_cytoscape()
print(f"Cytoscape elements: {len(cytoscape_data['elements'])}")

# Find mechanistic paths
paths = explain_paths(atorvastatin.key, top_k=3)
print("\nTop mechanistic paths:")
for p in paths:
    chain = " → ".join(f"{s['label'][:15]}" for s in p["path"])
    print(f"  {chain} (score: {p['score']:.2f})")
