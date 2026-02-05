"""Test tools with biologically significant data."""

from kg_ae.tools import (
    get_disease_genes,
    get_drug_adverse_events,
    get_drug_targets,
    get_gene_diseases,
    get_gene_interactors,
    get_gene_pathways,
    resolve_adverse_events,
    resolve_diseases,
    resolve_drugs,
    resolve_genes,
)


def test_warfarin():
    """Test warfarin - anticoagulant targeting VKORC1."""
    print("=" * 70)
    print("TEST: Warfarin - Known targets (VKORC1) and bleeding risk")
    print("=" * 70)

    drugs = resolve_drugs(["warfarin"])
    if not drugs.get("warfarin"):
        print("Warfarin not found!")
        return

    drug_key = drugs["warfarin"].key
    print(f"Resolved: {drugs['warfarin'].name}")

    targets = get_drug_targets(drug_key)
    print(f"\nTargets ({len(targets)}):")
    seen = set()
    for t in targets[:20]:
        if t.gene_symbol not in seen:
            seen.add(t.gene_symbol)
            print(f"  - {t.gene_symbol} ({t.claim_type})")

    aes = get_drug_adverse_events(drug_key, limit=15)
    print(f"\nAdverse Events ({len(aes)}):")
    for ae in aes[:10]:
        print(f"  - {ae.ae_label}")


def test_metformin():
    """Test metformin - diabetes drug with AMPK pathway."""
    print("\n" + "=" * 70)
    print("TEST: Metformin - Diabetes drug, known AMPK pathway")
    print("=" * 70)

    drugs = resolve_drugs(["metformin"])
    if not drugs.get("metformin"):
        print("Metformin not found!")
        return

    drug_key = drugs["metformin"].key
    print(f"Resolved: {drugs['metformin'].name}")

    targets = get_drug_targets(drug_key)
    print(f"\nTargets ({len(targets)}):")
    seen = set()
    for t in targets[:25]:
        if t.gene_symbol not in seen:
            seen.add(t.gene_symbol)
            print(f"  - {t.gene_symbol} ({t.claim_type})")

    aes = get_drug_adverse_events(drug_key, limit=10)
    print(f"\nAdverse Events ({len(aes)}):")
    for ae in aes[:8]:
        print(f"  - {ae.ae_label}")


def test_imatinib():
    """Test imatinib (Gleevec) - BCR-ABL inhibitor for CML."""
    print("\n" + "=" * 70)
    print("TEST: Imatinib (Gleevec) - BCR-ABL tyrosine kinase inhibitor")
    print("=" * 70)

    drugs = resolve_drugs(["imatinib"])
    if not drugs.get("imatinib"):
        print("Imatinib not found!")
        return

    drug_key = drugs["imatinib"].key
    print(f"Resolved: {drugs['imatinib'].name}")

    targets = get_drug_targets(drug_key)
    print(f"\nTargets ({len(targets)}):")
    seen = set()
    for t in targets[:20]:
        if t.gene_symbol not in seen:
            seen.add(t.gene_symbol)
            print(f"  - {t.gene_symbol} ({t.claim_type})")

    aes = get_drug_adverse_events(drug_key, limit=10)
    print(f"\nAdverse Events ({len(aes)}):")
    for ae in aes[:8]:
        print(f"  - {ae.ae_label}")


def test_tp53_gene():
    """Test TP53 - tumor suppressor, most studied cancer gene."""
    print("\n" + "=" * 70)
    print("TEST: TP53 - Tumor suppressor gene")
    print("=" * 70)

    genes = resolve_genes(["TP53"])
    if not genes.get("TP53"):
        print("TP53 not found!")
        return

    gene_key = genes["TP53"].key
    print(f"Resolved: {genes['TP53'].name}")

    # Get diseases
    diseases = get_gene_diseases(gene_key, min_score=0.5)
    print(f"\nAssociated Diseases (score >= 0.5, {len(diseases)} total):")
    for d in diseases[:10]:
        print(f"  - {d.disease_label} (score={d.score})")

    # Get interactors
    interactors = get_gene_interactors(gene_key, min_score=0.95, limit=15)
    print(f"\nHigh-confidence STRING interactors ({len(interactors)}):")
    for i in interactors[:10]:
        print(f"  - {i.interactor_symbol} (score={i.score})")

    # Get pathways
    pathways = get_gene_pathways(gene_key)
    print(f"\nPathways ({len(pathways)}):")
    for p in pathways[:8]:
        print(f"  - {p.pathway_label}")


def test_brca1_gene():
    """Test BRCA1 - breast cancer susceptibility gene."""
    print("\n" + "=" * 70)
    print("TEST: BRCA1 - Breast cancer susceptibility gene")
    print("=" * 70)

    genes = resolve_genes(["BRCA1"])
    if not genes.get("BRCA1"):
        print("BRCA1 not found!")
        return

    gene_key = genes["BRCA1"].key
    print(f"Resolved: {genes['BRCA1'].name}")

    diseases = get_gene_diseases(gene_key, min_score=0.3)
    print(f"\nAssociated Diseases ({len(diseases)}):")
    for d in diseases[:10]:
        print(f"  - {d.disease_label} (score={d.score})")

    interactors = get_gene_interactors(gene_key, min_score=0.9, limit=10)
    print(f"\nHigh-confidence interactors ({len(interactors)}):")
    for i in interactors[:8]:
        print(f"  - {i.interactor_symbol} (score={i.score})")


def test_disease_genes():
    """Test reverse lookup: diseases to genes."""
    print("\n" + "=" * 70)
    print("TEST: Disease-to-Gene reverse lookups")
    print("=" * 70)

    test_diseases = ["breast cancer", "Alzheimer disease", "diabetes mellitus"]

    for disease_name in test_diseases:
        diseases = resolve_diseases([disease_name])
        if diseases.get(disease_name):
            disease_key = diseases[disease_name].key
            genes = get_disease_genes(disease_key, limit=8)
            print(f"\n{disease_name} -> {len(genes)} genes:")
            for g in genes[:5]:
                print(f"  - {g.gene_symbol} (score={g.score}, source={g.source})")


def test_adverse_events_resolution():
    """Test adverse event term resolution."""
    print("\n" + "=" * 70)
    print("TEST: Adverse Event Resolution")
    print("=" * 70)

    ae_terms = [
        "myopathy",
        "rhabdomyolysis",
        "hepatotoxicity",
        "QT prolongation",
        "thrombocytopenia",
        "nephrotoxicity",
        "Stevens-Johnson syndrome",
    ]

    results = resolve_adverse_events(ae_terms)
    for term, entity in results.items():
        if entity:
            print(f"  {term} -> {entity.name} (conf={entity.confidence})")
        else:
            print(f"  {term} -> NOT FOUND")


def test_cyp_enzymes():
    """Test CYP enzymes - drug metabolism genes."""
    print("\n" + "=" * 70)
    print("TEST: CYP450 Drug Metabolism Enzymes")
    print("=" * 70)

    cyp_genes = ["CYP3A4", "CYP2D6", "CYP2C9", "CYP2C19", "CYP1A2"]

    for gene_name in cyp_genes:
        genes = resolve_genes([gene_name])
        if genes.get(gene_name):
            gene_key = genes[gene_name].key
            interactors = get_gene_interactors(gene_key, min_score=0.7, limit=5)
            print(f"\n{gene_name} interactors ({len(interactors)}):")
            for i in interactors[:3]:
                print(f"  - {i.interactor_symbol} (score={i.score})")


if __name__ == "__main__":
    test_warfarin()
    test_metformin()
    test_imatinib()
    test_tp53_gene()
    test_brca1_gene()
    test_disease_genes()
    test_adverse_events_resolution()
    test_cyp_enzymes()
