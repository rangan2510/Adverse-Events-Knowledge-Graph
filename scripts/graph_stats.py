"""Quick statistics for the file-based JSON knowledge graph."""

from collections import Counter

from rich.console import Console
from rich.table import Table

from kg_ae.graph import get_store

console = Console()
store = get_store()

# Node counts
counts = store.counts()
table = Table(title="Knowledge Graph Node Statistics")
table.add_column("Entity", style="cyan")
table.add_column("Count", justify="right", style="green")
for name in ("Drug", "Gene", "Disease", "Pathway", "AdverseEvent"):
    table.add_row(name, f"{counts.get(name, 0):,}")
table.add_row("Edges (claims)", f"{counts.get('edges', 0):,}")
console.print(table)

# Claim type + dataset breakdown (iterate edges once)
claim_types: Counter[str] = Counter()
datasets: Counter[str] = Counter()
for edges in store._out.values():  # noqa: SLF001 - script-level introspection
    for e in edges:
        claim_types[e.claim_type or "?"] += 1
        datasets[e.dataset or "?"] += 1

table2 = Table(title="Claim Type Breakdown")
table2.add_column("Claim Type", style="cyan")
table2.add_column("Count", justify="right", style="green")
for ct, cnt in claim_types.most_common():
    table2.add_row(ct, f"{cnt:,}")
console.print(table2)

table3 = Table(title="Dataset Coverage")
table3.add_column("Dataset", style="cyan")
table3.add_column("Claims", justify="right", style="green")
for ds, cnt in datasets.most_common():
    table3.add_row(ds, f"{cnt:,}")
console.print(table3)
