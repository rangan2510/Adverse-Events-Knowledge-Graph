"""Verify SIDER data was loaded correctly into SQL Server."""

from kg_ae.db import execute

# Count rows in each table
print("Row counts:")
tables = [
    ("kg.Dataset", "dataset_id"),
    ("kg.Drug", "drug_key"),
    ("kg.AdverseEvent", "ae_key"),
    ("kg.Claim", "claim_key"),
    ("kg.Evidence", "evidence_key"),
]

for table, _pk in tables:
    rows = execute(f"SELECT COUNT(*) FROM {table}")
    print(f"  {table}: {rows[0][0]:,}")

# Count edges
print("\nEdge counts:")
edges = ["kg.HasClaim", "kg.ClaimAdverseEvent", "kg.SupportedBy"]
for edge in edges:
    rows = execute(f"SELECT COUNT(*) FROM {edge}")
    print(f"  {edge}: {rows[0][0]:,}")

# Sample graph query: Find AEs for a specific drug
print("\n--- Sample Query: Side effects of 'aspirin' ---")
query = """
SELECT TOP 10 
    d.preferred_name AS drug,
    ae.ae_label AS adverse_event,
    c.strength_score AS frequency
FROM kg.Drug d,
     kg.HasClaim hc,
     kg.Claim c,
     kg.ClaimAdverseEvent cae,
     kg.AdverseEvent ae
WHERE MATCH(d-(hc)->c-(cae)->ae)
  AND d.preferred_name LIKE '%aspirin%'
ORDER BY c.strength_score DESC
"""
rows = execute(query)
if rows:
    for row in rows:
        freq = f"{row[2]:.1%}" if row[2] else "N/A"
        print(f"  {row[0]} → {row[1]} ({freq})")
else:
    print("  No results (aspirin may not be in SIDER)")

# Try another drug
print("\n--- Sample Query: Side effects of 'carnitine' ---")
query2 = """
SELECT TOP 10 
    d.preferred_name AS drug,
    ae.ae_label AS adverse_event,
    c.strength_score AS frequency
FROM kg.Drug d,
     kg.HasClaim hc,
     kg.Claim c,
     kg.ClaimAdverseEvent cae,
     kg.AdverseEvent ae
WHERE MATCH(d-(hc)->c-(cae)->ae)
  AND d.preferred_name = 'carnitine'
ORDER BY c.strength_score DESC
"""
rows = execute(query2)
for row in rows:
    freq = f"{row[2]:.1%}" if row[2] else "N/A"
    print(f"  {row[0]} → {row[1]} ({freq})")
