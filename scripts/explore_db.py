"""Explore database to find drugs with rich data for polypharmacy test cases."""
from kg_ae.db.connection import get_connection

# Actual claim types in the DB
TARGET_TYPES = "('DRUG_TARGET', 'DRUG_TARGET_GTOPDB', 'DRUG_TARGET_CHEMBL', 'DRUG_GENE_CTD')"
AE_TYPES = "('DRUG_AE_LABEL', 'DRUG_AE_FAERS')"
DISEASE_TYPES = "('DRUG_DISEASE_CTD', 'DRUG_LABEL', 'GENE_DISEASE', 'GENE_DISEASE_CTD', 'GENE_DISEASE_CLINGEN')"


def run_query(sql: str, params=None):
    """Run a query and return all rows."""
    with get_connection() as conn:
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return cols, rows


def top_drugs_with_data():
    """Find drugs with the most claims across all edge types."""
    sql = f"""
        SELECT TOP 40
            d.preferred_name,
            d.drug_key,
            SUM(CASE WHEN c.claim_type IN {TARGET_TYPES} THEN 1 ELSE 0 END) AS target_claims,
            SUM(CASE WHEN c.claim_type IN {DISEASE_TYPES} THEN 1 ELSE 0 END) AS disease_claims,
            SUM(CASE WHEN c.claim_type IN {AE_TYPES} THEN 1 ELSE 0 END) AS ae_claims,
            COUNT(*) AS total_claims
        FROM kg.Drug d, kg.HasClaim hc, kg.Claim c
        WHERE MATCH(d-(hc)->c)
        GROUP BY d.preferred_name, d.drug_key
        HAVING SUM(CASE WHEN c.claim_type IN {TARGET_TYPES} THEN 1 ELSE 0 END) > 5
           AND SUM(CASE WHEN c.claim_type IN {AE_TYPES} THEN 1 ELSE 0 END) > 5
        ORDER BY COUNT(*) DESC
    """
    cols, rows = run_query(sql)
    print("=== TOP 40 DRUGS with BOTH target AND AE data ===")
    print(f"{'Drug':35s} {'key':>5s} {'Targets':>8s} {'Diseases':>9s} {'AEs':>6s} {'Total':>6s}")
    print("-" * 75)
    for r in rows:
        print(f"{r[0]:35s} {r[1]:5d} {r[2]:8d} {r[3]:9d} {r[4]:6d} {r[5]:6d}")
    return rows


def shared_targets(drug_names: list[str]):
    """Find shared gene targets between drugs."""
    placeholders = ", ".join(["?" for _ in drug_names])
    sql = f"""
        SELECT g.symbol, g.gene_key, COUNT(DISTINCT d.drug_key) AS drug_count
        FROM kg.Drug d, kg.HasClaim hc, kg.Claim c, kg.ClaimGene cg, kg.Gene g
        WHERE MATCH(d-(hc)->c-(cg)->g)
          AND c.claim_type IN {TARGET_TYPES}
          AND d.preferred_name IN ({placeholders})
        GROUP BY g.symbol, g.gene_key
        HAVING COUNT(DISTINCT d.drug_key) > 1
        ORDER BY COUNT(DISTINCT d.drug_key) DESC, g.symbol
    """
    cols, rows = run_query(sql, drug_names)
    drugs_str = " + ".join(drug_names)
    print(f"\n=== SHARED TARGETS: {drugs_str} ===")
    if rows:
        print(f"{'Gene':15s} {'key':>6s} {'#Drugs':>6s}")
        print("-" * 35)
        for r in rows:
            print(f"{r[0]:15s} {r[1]:6d} {r[2]:6d}")
    else:
        print("  No shared targets found.")
    return rows


def shared_aes(drug_names: list[str]):
    """Find shared adverse events between drugs."""
    placeholders = ", ".join(["?" for _ in drug_names])
    sql = f"""
        SELECT TOP 40 ae.ae_label, ae.ae_key, COUNT(DISTINCT d.drug_key) AS drug_count
        FROM kg.Drug d, kg.HasClaim hc, kg.Claim c, kg.ClaimAdverseEvent ca, kg.AdverseEvent ae
        WHERE MATCH(d-(hc)->c-(ca)->ae)
          AND c.claim_type IN {AE_TYPES}
          AND d.preferred_name IN ({placeholders})
        GROUP BY ae.ae_label, ae.ae_key
        HAVING COUNT(DISTINCT d.drug_key) > 1
        ORDER BY COUNT(DISTINCT d.drug_key) DESC, ae.ae_label
    """
    cols, rows = run_query(sql, drug_names)
    drugs_str = " + ".join(drug_names)
    print(f"\n=== SHARED AEs: {drugs_str} (top 40) ===")
    if rows:
        print(f"{'Adverse Event':45s} {'key':>6s} {'#Drugs':>6s}")
        print("-" * 65)
        for r in rows:
            print(f"{r[0]:45s} {r[1]:6d} {r[2]:6d}")
    else:
        print("  No shared AEs found.")
    return rows


def drug_targets(drug_name: str):
    """Get all gene targets for a drug."""
    sql = f"""
        SELECT DISTINCT g.symbol, g.gene_key, c.strength_score, c.claim_type
        FROM kg.Drug d, kg.HasClaim hc, kg.Claim c, kg.ClaimGene cg, kg.Gene g
        WHERE MATCH(d-(hc)->c-(cg)->g)
          AND c.claim_type IN {TARGET_TYPES}
          AND d.preferred_name = ?
        ORDER BY g.symbol
    """
    cols, rows = run_query(sql, [drug_name])
    print(f"\n=== TARGETS of {drug_name} ({len(rows)} total) ===")
    for r in rows[:25]:
        score = f"{r[2]:.2f}" if r[2] else "N/A"
        print(f"  {r[0]:15s}  score={score:>5s}  type={r[3]}")
    if len(rows) > 25:
        print(f"  ... and {len(rows) - 25} more")
    return rows


def drug_aes(drug_name: str):
    """Get all adverse events for a drug."""
    sql = f"""
        SELECT ae.ae_label, ae.ae_key, c.strength_score, c.claim_type
        FROM kg.Drug d, kg.HasClaim hc, kg.Claim c, kg.ClaimAdverseEvent ca, kg.AdverseEvent ae
        WHERE MATCH(d-(hc)->c-(ca)->ae)
          AND c.claim_type IN {AE_TYPES}
          AND d.preferred_name = ?
        ORDER BY c.strength_score DESC
    """
    cols, rows = run_query(sql, [drug_name])
    print(f"\n=== AEs of {drug_name} ({len(rows)} total) ===")
    for r in rows[:25]:
        score = f"{r[2]:.2f}" if r[2] else "N/A"
        print(f"  {r[0]:45s}  score={score:>5s}  {r[3]}")
    if len(rows) > 25:
        print(f"  ... and {len(rows) - 25} more")
    return rows


def drug_pathways(drug_name: str):
    """Get pathways linked to a drug's targets."""
    sql = f"""
        SELECT DISTINCT p.label, p.pathway_key, p.reactome_id
        FROM kg.Drug d, kg.HasClaim hc, kg.Claim c, kg.ClaimGene cg, kg.Gene g,
             kg.HasClaim hc2, kg.Claim c2, kg.ClaimPathway cp, kg.Pathway p
        WHERE MATCH(d-(hc)->c-(cg)->g)
          AND MATCH(g-(hc2)->c2-(cp)->p)
          AND c.claim_type IN {TARGET_TYPES}
          AND d.preferred_name = ?
        ORDER BY p.label
    """
    cols, rows = run_query(sql, [drug_name])
    print(f"\n=== PATHWAYS linked to {drug_name} targets ({len(rows)} total) ===")
    for r in rows[:25]:
        print(f"  {r[0]:65s}  {r[2] or 'N/A'}")
    if len(rows) > 25:
        print(f"  ... and {len(rows) - 25} more")
    return rows


def claim_types_summary():
    """Show distribution of claim types."""
    sql = """
        SELECT claim_type, COUNT(*) AS cnt
        FROM kg.Claim
        GROUP BY claim_type
        ORDER BY COUNT(*) DESC
    """
    cols, rows = run_query(sql)
    print("\n=== CLAIM TYPE DISTRIBUTION ===")
    for r in rows:
        print(f"  {r[0]:35s}  {r[1]:>10,}")
    return rows


def dataset_summary():
    """Show loaded datasets."""
    sql = "SELECT dataset_id, dataset_name, dataset_version, source_url FROM kg.Dataset ORDER BY dataset_id"
    cols, rows = run_query(sql)
    print("\n=== LOADED DATASETS ===")
    for r in rows:
        print(f"  [{r[0]:2d}] {r[1]:40s}  v={str(r[2] or 'N/A'):10s}")
    return rows


if __name__ == "__main__":
    print("=" * 80)
    print("  DATABASE EXPLORATION FOR POLYPHARMACY TEST CASES")
    print("=" * 80)

    # Overview
    dataset_summary()
    claim_types_summary()

    # Top drugs with both targets and AEs
    top = top_drugs_with_data()

    # Get the names for further exploration
    top_names = [r[0] for r in top[:15]]
    print(f"\n--- Top 15 drugs for polypharmacy: {top_names}")

    # ====================================================================
    # COMBO 1: Cardiovascular - warfarin, verapamil, metoprolol
    # ====================================================================
    print("\n" + "=" * 80)
    print("  COMBO 1: CARDIOVASCULAR")
    print("=" * 80)
    cv_drugs = ["warfarin", "verapamil", "metoprolol"]
    for d in cv_drugs:
        drug_targets(d)
        drug_aes(d)
    shared_targets(cv_drugs)
    shared_aes(cv_drugs)

    # ====================================================================
    # COMBO 2: Psychiatric - ziprasidone, venlafaxine, lithium
    # ====================================================================
    print("\n" + "=" * 80)
    print("  COMBO 2: PSYCHIATRIC")
    print("=" * 80)
    psych_drugs = ["ziprasidone", "venlafaxine", "lithium"]
    for d in psych_drugs:
        drug_targets(d)
        drug_aes(d)
    shared_targets(psych_drugs)
    shared_aes(psych_drugs)

    # ====================================================================
    # COMBO 3: Cancer/onc - vorinostat, imatinib, methotrexate
    # ====================================================================
    print("\n" + "=" * 80)
    print("  COMBO 3: ONCOLOGY")
    print("=" * 80)
    onc_drugs = ["vorinostat", "imatinib", "methotrexate"]
    for d in onc_drugs:
        drug_targets(d)
        drug_aes(d)
    shared_targets(onc_drugs)
    shared_aes(onc_drugs)

    # ====================================================================
    # COMBO 4: Pain/inflammation - ibuprofen, acetylsalicylic acid, celecoxib
    # ====================================================================
    print("\n" + "=" * 80)
    print("  COMBO 4: PAIN / INFLAMMATION")
    print("=" * 80)
    pain_drugs = ["ibuprofen", "acetylsalicylic acid", "celecoxib"]
    for d in pain_drugs:
        drug_targets(d)
        drug_aes(d)
    shared_targets(pain_drugs)
    shared_aes(pain_drugs)

    # ====================================================================
    # PATHWAY CHECK: Pick a rich drug and check pathway connectivity
    # ====================================================================
    print("\n" + "=" * 80)
    print("  PATHWAY EXPLORATION")
    print("=" * 80)
    for d in ["verapamil", "imatinib", "methotrexate"]:
        drug_pathways(d)

    print("\n" + "=" * 80)
    print("  EXPLORATION COMPLETE")
    print("=" * 80)
