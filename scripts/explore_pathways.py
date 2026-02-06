"""Explore pathway data for polypharmacy combos."""
import sys
import os
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
from scripts.explore_db import drug_pathways, run_query, TARGET_TYPES

# Pathway exploration for key drugs from each combo
drugs = ["verapamil", "imatinib", "methotrexate", "warfarin", "celecoxib", "ibuprofen"]

for d in drugs:
    drug_pathways(d)

# Shared pathways between combo drugs
def shared_pathways(drug_names: list[str]):
    placeholders = ", ".join(["?" for _ in drug_names])
    sql = f"""
        SELECT p.label, p.reactome_id, COUNT(DISTINCT d.preferred_name) AS n_drugs
        FROM kg.Drug d, kg.HasClaim hc, kg.Claim c, kg.ClaimGene cg, kg.Gene g,
             kg.HasClaim hc2, kg.Claim c2, kg.ClaimPathway cp, kg.Pathway p
        WHERE MATCH(d-(hc)->c-(cg)->g)
          AND MATCH(g-(hc2)->c2-(cp)->p)
          AND c.claim_type IN {TARGET_TYPES}
          AND d.preferred_name IN ({placeholders})
        GROUP BY p.label, p.reactome_id
        HAVING COUNT(DISTINCT d.preferred_name) >= 2
        ORDER BY COUNT(DISTINCT d.preferred_name) DESC, p.label
    """
    cols, rows = run_query(sql, drug_names)
    print(f"\n=== SHARED PATHWAYS: {' + '.join(drug_names)} ({len(rows)} shared) ===")
    for r in rows[:30]:
        print(f"  {r[0]:65s}  {r[1] or 'N/A':20s}  {r[2]} drugs")
    if len(rows) > 30:
        print(f"  ... and {len(rows) - 30} more")
    return rows

print("\n" + "=" * 80)
print("  SHARED PATHWAY ANALYSIS")
print("=" * 80)

# Combo 1: Cardiovascular
shared_pathways(["warfarin", "verapamil", "metoprolol"])

# Combo 2: Psychiatric
shared_pathways(["ziprasidone", "venlafaxine", "lithium"])

# Combo 3: Oncology
shared_pathways(["vorinostat", "imatinib", "methotrexate"])

# Combo 4: Pain
shared_pathways(["ibuprofen", "acetylsalicylic acid", "celecoxib"])
