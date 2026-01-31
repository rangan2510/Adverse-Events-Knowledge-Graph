"""
Entity resolution modules.

Resolves free-text entity names to canonical IDs:
- Drug names → drug_key (via DrugCentral, PubChem, synonyms)
- Gene symbols → gene_key (via HGNC, Ensembl, UniProt)
- Disease terms → disease_key (via MONDO, DOID, EFO)
- AE terms → ae_key (via embedding similarity, OAE mapping)

Each resolver returns:
- Canonical ID
- Confidence score (0-1)
- Match method (exact, synonym, fuzzy, embedding)
- Evidence trail for debugging
"""
