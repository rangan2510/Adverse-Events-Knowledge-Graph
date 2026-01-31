"""Verify the kg.* schema was created correctly."""

from kg_ae.db import execute

SQL = """
SELECT t.name, t.is_node, t.is_edge 
FROM sys.tables t 
JOIN sys.schemas s ON t.schema_id = s.schema_id 
WHERE s.name = 'kg' 
ORDER BY t.name
"""

rows = execute(SQL)
print("kg.* tables created:")
for r in rows:
    ttype = "NODE" if r[1] else ("EDGE" if r[2] else "TABLE")
    print(f"  {ttype:5} kg.{r[0]}")

print(f"\nTotal: {len(rows)} tables")
