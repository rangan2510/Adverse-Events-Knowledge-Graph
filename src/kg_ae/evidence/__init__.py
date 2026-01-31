"""
Evidence scoring and provenance.

Implements the evidence hierarchy:
1. Curated pharmacology (GtoPdb) - highest weight
2. Curated DB (DrugCentral)
3. Label-listed AE (openFDA labels)
4. FAERS signal (disproportionality)
5. SIDER (older, label-derived)

Edge score formula:
    score = w_source × w_field_quality × w_recency × w_frequency × resolver_conf
"""
