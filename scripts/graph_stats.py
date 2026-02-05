"""Quick graph statistics."""

from rich.console import Console
from rich.table import Table

from kg_ae.db import execute

console = Console()

# Node counts
nodes = [
    ("kg.Drug", "Drugs"),
    ("kg.Gene", "Genes"),
    ("kg.Disease", "Diseases"),
    ("kg.Pathway", "Pathways"),
    ("kg.AdverseEvent", "Adverse Events"),
    ("kg.Claim", "Claims"),
    ("kg.Evidence", "Evidence"),
]

table = Table(title="Knowledge Graph Node Statistics")
table.add_column("Entity", style="cyan")
table.add_column("Count", justify="right", style="green")

for tbl, name in nodes:
    count = execute(f"SELECT COUNT(*) FROM {tbl}")[0][0]
    table.add_row(name, f"{count:,}")

console.print(table)

# Claim type breakdown
claim_types = execute("""
    SELECT claim_type, COUNT(*) as cnt 
    FROM kg.Claim 
    GROUP BY claim_type 
    ORDER BY cnt DESC
""")

table2 = Table(title="Claim Type Breakdown")
table2.add_column("Claim Type", style="cyan")
table2.add_column("Count", justify="right", style="green")

for ct, cnt in claim_types:
    table2.add_row(ct, f"{cnt:,}")

console.print(table2)

# Dataset coverage
datasets = execute("""
    SELECT d.dataset_name, COUNT(c.claim_key) as claims
    FROM kg.Dataset d
    LEFT JOIN kg.Claim c ON d.dataset_id = c.dataset_id
    GROUP BY d.dataset_id, d.dataset_name
    ORDER BY claims DESC
""")

table3 = Table(title="Dataset Coverage")
table3.add_column("Dataset", style="cyan")
table3.add_column("Claims", justify="right", style="green")

for ds, cnt in datasets:
    table3.add_row(ds, f"{cnt:,}")

console.print(table3)
