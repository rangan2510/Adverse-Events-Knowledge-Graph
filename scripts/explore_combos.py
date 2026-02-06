"""Focused exploration of specific drug combos for polypharmacy test cases."""
from explore_db import shared_targets, shared_aes, drug_targets, drug_aes, drug_pathways

# COMBO 3: Oncology
print("=" * 80)
print("  COMBO 3: ONCOLOGY - vorinostat + imatinib + methotrexate")
print("=" * 80)
onc_drugs = ["vorinostat", "imatinib", "methotrexate"]
shared_targets(onc_drugs)
shared_aes(onc_drugs)

# COMBO 4: Pain / Inflammation
print("\n" + "=" * 80)
print("  COMBO 4: PAIN - ibuprofen + acetylsalicylic acid + celecoxib")
print("=" * 80)
pain_drugs = ["ibuprofen", "acetylsalicylic acid", "celecoxib"]
for d in pain_drugs:
    drug_targets(d)
    drug_aes(d)
shared_targets(pain_drugs)
shared_aes(pain_drugs)

# PATHWAY EXPLORATION
print("\n" + "=" * 80)
print("  PATHWAY EXPLORATION")
print("=" * 80)
for d in ["verapamil", "imatinib", "methotrexate"]:
    drug_pathways(d)

print("\nDone.")
