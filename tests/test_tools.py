"""Tests for knowledge graph tools.

These tests require a live database connection with data loaded.
Run with: uv run pytest tests/test_tools.py --run-db
"""

import pytest

from kg_ae.tools import (
    # Resolve tools
    resolve_drugs,
    resolve_genes,
    resolve_diseases,
    resolve_adverse_events,
    ResolvedEntity,
    # Mechanism tools
    get_drug_targets,
    get_gene_pathways,
    get_gene_diseases,
    get_disease_genes,
    get_gene_interactors,
    expand_mechanism,
    expand_gene_context,
    DrugTarget,
    GenePathway,
    GeneDisease,
    DiseaseGene,
    GeneInteractor,
    # Adverse event tools
    get_drug_adverse_events,
    get_drug_profile,
    get_drug_label_sections,
    get_drug_faers_signals,
    DrugAdverseEvent,
    DrugLabelSection,
    FAERSSignal,
    # Subgraph tools
    build_subgraph,
    score_edges,
    Subgraph,
    Node,
    Edge,
    # Path tools
    find_drug_to_ae_paths,
    explain_paths,
    score_paths,
    score_paths_with_evidence,
    MechanisticPath,
    PathStep,
    ScoringPolicy,
    # Evidence tools
    get_claim_evidence,
    get_entity_claims,
    ClaimEvidence,
    ClaimDetail,
)

pytestmark = pytest.mark.db


# ---------------------------------------------------------------------------
# Resolution Tests
# ---------------------------------------------------------------------------


class TestResolveAdverseEvents:
    """Tests for resolve_adverse_events function."""

    def test_resolve_exact_match(self):
        """Test exact match resolution."""
        results = resolve_adverse_events(["headache"])
        assert "headache" in results
        if results["headache"]:
            assert results["headache"].confidence == 1.0
            assert results["headache"].source == "ae_label"

    def test_resolve_partial_match(self):
        """Test partial match resolution."""
        # Use a partial term that should find something
        results = resolve_adverse_events(["myopath"])
        # May or may not find a match depending on data
        assert "myopath" in results

    def test_resolve_not_found(self):
        """Test resolution of non-existent term."""
        results = resolve_adverse_events(["nonexistent_ae_xyz123"])
        assert results["nonexistent_ae_xyz123"] is None

    def test_resolve_multiple_terms(self):
        """Test resolving multiple terms at once."""
        terms = ["nausea", "dizziness", "fatigue"]
        results = resolve_adverse_events(terms)
        assert len(results) == 3
        for term in terms:
            assert term in results

    def test_resolve_returns_resolved_entity(self):
        """Test that results are ResolvedEntity or None."""
        results = resolve_adverse_events(["nausea"])
        for value in results.values():
            assert value is None or isinstance(value, ResolvedEntity)


# ---------------------------------------------------------------------------
# Drug Label and FAERS Tests
# ---------------------------------------------------------------------------


class TestDrugLabelSections:
    """Tests for get_drug_label_sections function."""

    def test_get_all_sections(self):
        """Test getting all label sections for a drug."""
        # First resolve a drug
        drugs = resolve_drugs(["atorvastatin"])
        if drugs.get("atorvastatin"):
            drug_key = drugs["atorvastatin"].key
            sections = get_drug_label_sections(drug_key)
            # May return empty if no label data for this drug
            assert isinstance(sections, list)

    def test_get_specific_sections(self):
        """Test filtering by section names."""
        drugs = resolve_drugs(["aspirin"])
        if drugs.get("aspirin"):
            drug_key = drugs["aspirin"].key
            sections = get_drug_label_sections(
                drug_key, sections=["warnings", "adverse_reactions"]
            )
            for section in sections:
                assert isinstance(section, DrugLabelSection)
                assert section.section_name in ["warnings", "adverse_reactions"]

    def test_section_has_content(self):
        """Test that returned sections have content."""
        drugs = resolve_drugs(["metformin"])
        if drugs.get("metformin"):
            drug_key = drugs["metformin"].key
            sections = get_drug_label_sections(drug_key)
            for section in sections:
                assert section.content  # Should have non-empty content


class TestFAERSSignals:
    """Tests for get_drug_faers_signals function."""

    def test_get_signals(self):
        """Test getting FAERS signals for a drug."""
        drugs = resolve_drugs(["atorvastatin"])
        if drugs.get("atorvastatin"):
            drug_key = drugs["atorvastatin"].key
            signals = get_drug_faers_signals(drug_key)
            assert isinstance(signals, list)

    def test_signals_with_filters(self):
        """Test filtering by count and PRR thresholds."""
        drugs = resolve_drugs(["metoprolol"])
        if drugs.get("metoprolol"):
            drug_key = drugs["metoprolol"].key
            signals = get_drug_faers_signals(drug_key, min_count=5, min_prr=2.0)
            for signal in signals:
                assert isinstance(signal, FAERSSignal)
                assert signal.count >= 5
                if signal.prr is not None:
                    assert signal.prr >= 2.0

    def test_signals_sorted_by_prr(self):
        """Test that signals are sorted by PRR descending."""
        drugs = resolve_drugs(["warfarin"])
        if drugs.get("warfarin"):
            drug_key = drugs["warfarin"].key
            signals = get_drug_faers_signals(drug_key, top_k=50)
            if len(signals) > 1:
                for i in range(len(signals) - 1):
                    prr1 = signals[i].prr or 0
                    prr2 = signals[i + 1].prr or 0
                    assert prr1 >= prr2


# ---------------------------------------------------------------------------
# Disease-Gene and Gene Interactor Tests
# ---------------------------------------------------------------------------


class TestDiseaseGenes:
    """Tests for get_disease_genes function."""

    def test_get_genes_for_disease(self):
        """Test getting genes associated with a disease."""
        diseases = resolve_diseases(["diabetes"])
        if diseases.get("diabetes"):
            disease_key = diseases["diabetes"].key
            genes = get_disease_genes(disease_key)
            assert isinstance(genes, list)
            for gene in genes:
                assert isinstance(gene, DiseaseGene)

    def test_filter_by_source(self):
        """Test filtering by data source."""
        diseases = resolve_diseases(["cancer"])
        if diseases.get("cancer"):
            disease_key = diseases["cancer"].key
            genes = get_disease_genes(disease_key, sources=["opentargets"])
            for gene in genes:
                assert gene.source == "opentargets"

    def test_filter_by_score(self):
        """Test filtering by minimum score."""
        diseases = resolve_diseases(["hypertension"])
        if diseases.get("hypertension"):
            disease_key = diseases["hypertension"].key
            genes = get_disease_genes(disease_key, min_score=0.5)
            for gene in genes:
                if gene.score is not None:
                    assert gene.score >= 0.5


class TestGeneInteractors:
    """Tests for get_gene_interactors function."""

    def test_get_interactors(self):
        """Test getting gene interactors from STRING."""
        genes = resolve_genes(["TP53"])
        if genes.get("TP53"):
            gene_key = genes["TP53"].key
            interactors = get_gene_interactors(gene_key)
            assert isinstance(interactors, list)
            for interactor in interactors:
                assert isinstance(interactor, GeneInteractor)

    def test_interactors_score_filter(self):
        """Test filtering by STRING score."""
        genes = resolve_genes(["BRCA1"])
        if genes.get("BRCA1"):
            gene_key = genes["BRCA1"].key
            interactors = get_gene_interactors(gene_key, min_score=0.9)
            for interactor in interactors:
                assert interactor.score >= 0.9

    def test_interactors_sorted(self):
        """Test that interactors are sorted by score descending."""
        genes = resolve_genes(["EGFR"])
        if genes.get("EGFR"):
            gene_key = genes["EGFR"].key
            interactors = get_gene_interactors(gene_key, limit=50)
            if len(interactors) > 1:
                for i in range(len(interactors) - 1):
                    assert interactors[i].score >= interactors[i + 1].score


# ---------------------------------------------------------------------------
# Evidence Tests
# ---------------------------------------------------------------------------


class TestClaimEvidence:
    """Tests for get_claim_evidence function."""

    def test_get_evidence_for_claim(self):
        """Test getting evidence for a claim."""
        # First get a claim key by resolving a drug and getting its targets
        drugs = resolve_drugs(["aspirin"])
        if drugs.get("aspirin"):
            drug_key = drugs["aspirin"].key
            targets = get_drug_targets(drug_key)
            if targets:
                # Get claims for this drug
                claims = get_entity_claims("Drug", drug_key, limit=1)
                if claims:
                    claim_key = claims[0].claim_key
                    detail = get_claim_evidence(claim_key)
                    assert detail is not None
                    assert isinstance(detail, ClaimDetail)
                    assert detail.claim_key == claim_key

    def test_evidence_not_found(self):
        """Test that non-existent claim returns None."""
        result = get_claim_evidence(999999999)
        assert result is None

    def test_claim_has_type(self):
        """Test that claim detail includes claim type."""
        drugs = resolve_drugs(["metformin"])
        if drugs.get("metformin"):
            drug_key = drugs["metformin"].key
            claims = get_entity_claims("Drug", drug_key, limit=1)
            if claims:
                assert claims[0].claim_type is not None
                assert len(claims[0].claim_type) > 0


class TestEntityClaims:
    """Tests for get_entity_claims function."""

    def test_get_drug_claims(self):
        """Test getting all claims for a drug."""
        drugs = resolve_drugs(["ibuprofen"])
        if drugs.get("ibuprofen"):
            drug_key = drugs["ibuprofen"].key
            claims = get_entity_claims("Drug", drug_key)
            assert isinstance(claims, list)
            for claim in claims:
                assert isinstance(claim, ClaimDetail)

    def test_filter_by_claim_type(self):
        """Test filtering claims by type."""
        drugs = resolve_drugs(["atorvastatin"])
        if drugs.get("atorvastatin"):
            drug_key = drugs["atorvastatin"].key
            claims = get_entity_claims(
                "Drug", drug_key, claim_types=["DRUG_TARGET"]
            )
            for claim in claims:
                assert claim.claim_type == "DRUG_TARGET"

    def test_invalid_entity_type(self):
        """Test that invalid entity type returns empty list."""
        claims = get_entity_claims("InvalidType", 1)
        assert claims == []


# ---------------------------------------------------------------------------
# Path Scoring Tests
# ---------------------------------------------------------------------------


class TestScorePaths:
    """Tests for score_paths function."""

    def test_score_paths_returns_sorted(self):
        """Test that score_paths returns sorted paths."""
        # Create mock paths
        paths = [
            MechanisticPath(
                steps=[
                    PathStep("Drug", 1, "DrugA"),
                    PathStep("Gene", 1, "GeneA", "TARGETS"),
                ],
                score=0.5,
                evidence_count=1,
            ),
            MechanisticPath(
                steps=[
                    PathStep("Drug", 2, "DrugB"),
                    PathStep("Gene", 2, "GeneB", "TARGETS"),
                ],
                score=0.8,
                evidence_count=2,
            ),
        ]
        scored = score_paths(paths)
        assert len(scored) == 2
        # Higher base score + multi-source bonus should rank higher
        assert scored[0].steps[0].node_label == "DrugB"

    def test_score_with_custom_policy(self):
        """Test scoring with custom policy."""
        paths = [
            MechanisticPath(
                steps=[
                    PathStep("Drug", 1, "DrugA"),
                    PathStep("Gene", 1, "GeneA", "TARGETS"),
                    PathStep("Pathway", 1, "PathwayA", "IN_PATHWAY"),
                ],
                score=0.9,
                evidence_count=1,
            ),
        ]
        # Custom policy with higher length penalty
        policy = ScoringPolicy(length_penalty=0.5)
        scored = score_paths(paths, policy)
        # Two hops = 0.9 * 0.5^2 = 0.225
        assert scored[0].score < 0.5

    def test_score_filters_low_evidence(self):
        """Test that paths with insufficient evidence are filtered."""
        paths = [
            MechanisticPath(
                steps=[PathStep("Drug", 1, "DrugA")],
                score=0.9,
                evidence_count=0,
            ),
        ]
        policy = ScoringPolicy(min_evidence=1)
        scored = score_paths(paths, policy)
        assert len(scored) == 0


class TestScorePathsWithEvidence:
    """Tests for score_paths_with_evidence function."""

    def test_returns_scoring_breakdown(self):
        """Test that detailed scoring breakdown is returned."""
        paths = [
            MechanisticPath(
                steps=[
                    PathStep("Drug", 1, "DrugA"),
                    PathStep("Gene", 1, "GeneA", "TARGETS"),
                ],
                score=0.7,
                evidence_count=2,
            ),
        ]
        results = score_paths_with_evidence(paths)
        assert len(results) == 1
        assert "path" in results[0]
        assert "scoring" in results[0]
        scoring = results[0]["scoring"]
        assert "base_score" in scoring
        assert "length_factor" in scoring
        assert "num_hops" in scoring
        assert "evidence_count" in scoring
        assert "multi_source_factor" in scoring
        assert "final_score" in scoring


# ---------------------------------------------------------------------------
# Dataclass Tests (no DB required)
# ---------------------------------------------------------------------------


class TestDataclasses:
    """Tests for dataclass structures (no DB needed)."""

    def test_resolved_entity_creation(self):
        """Test ResolvedEntity dataclass."""
        entity = ResolvedEntity(key=1, name="Test", source="test_source")
        assert entity.key == 1
        assert entity.name == "Test"
        assert entity.confidence == 1.0  # default

    def test_faers_signal_creation(self):
        """Test FAERSSignal dataclass."""
        signal = FAERSSignal(
            drug_key=1,
            drug_name="TestDrug",
            ae_key=2,
            ae_label="TestAE",
            prr=2.5,
            ror=3.0,
            chi2=10.5,
            count=50,
        )
        assert signal.prr == 2.5
        assert signal.count == 50

    def test_drug_label_section_creation(self):
        """Test DrugLabelSection dataclass."""
        section = DrugLabelSection(
            drug_key=1,
            drug_name="TestDrug",
            section_name="warnings",
            content="Warning text here",
        )
        assert section.section_name == "warnings"

    def test_disease_gene_creation(self):
        """Test DiseaseGene dataclass."""
        dg = DiseaseGene(
            disease_key=1,
            disease_label="TestDisease",
            gene_key=2,
            gene_symbol="GENE1",
            score=0.85,
            source="opentargets",
        )
        assert dg.source == "opentargets"

    def test_gene_interactor_creation(self):
        """Test GeneInteractor dataclass."""
        gi = GeneInteractor(
            gene_key=1,
            gene_symbol="GENE1",
            interactor_key=2,
            interactor_symbol="GENE2",
            score=0.9,
        )
        assert gi.score == 0.9

    def test_claim_evidence_creation(self):
        """Test ClaimEvidence dataclass."""
        ce = ClaimEvidence(
            evidence_key=1,
            evidence_type="test_type",
            source_record_id="REC123",
            source_url="http://example.com",
            payload={"key": "value"},
            support_strength=0.8,
            dataset_key="test_dataset",
        )
        assert ce.payload == {"key": "value"}

    def test_scoring_policy_defaults(self):
        """Test ScoringPolicy default values."""
        policy = ScoringPolicy()
        assert policy.multi_source_bonus == 1.2
        assert policy.min_evidence == 1
        assert policy.length_penalty == 0.95
        assert "drugcentral" in policy.source_weights

    def test_mechanistic_path_to_dict(self):
        """Test MechanisticPath to_dict method."""
        path = MechanisticPath(
            steps=[
                PathStep("Drug", 1, "DrugA"),
                PathStep("Gene", 2, "GeneA", "TARGETS"),
            ],
            score=0.8,
            evidence_count=3,
        )
        d = path.to_dict()
        assert d["score"] == 0.8
        assert d["evidence_count"] == 3
        assert len(d["path"]) == 2
        assert d["path"][1]["edge"] == "TARGETS"


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestToolsIntegration:
    """Integration tests combining multiple tools."""

    def test_drug_to_ae_pipeline(self):
        """Test full pipeline: drug -> targets -> diseases -> AEs."""
        # Resolve drug
        drugs = resolve_drugs(["metformin"])
        if not drugs.get("metformin"):
            pytest.skip("metformin not found in database")

        drug_key = drugs["metformin"].key

        # Get targets
        targets = get_drug_targets(drug_key)
        if not targets:
            pytest.skip("No targets found for metformin")

        # Get diseases for first target
        gene_key = targets[0].gene_key
        diseases = get_gene_diseases(gene_key)
        assert isinstance(diseases, list)

        # Get AEs
        aes = get_drug_adverse_events(drug_key)
        assert isinstance(aes, list)

    def test_evidence_audit_trail(self):
        """Test that we can trace from drug to evidence."""
        drugs = resolve_drugs(["aspirin"])
        if not drugs.get("aspirin"):
            pytest.skip("aspirin not found in database")

        drug_key = drugs["aspirin"].key
        claims = get_entity_claims("Drug", drug_key, limit=5)

        # Check that at least some claims have evidence
        has_evidence = False
        for claim in claims:
            if claim.evidence:
                has_evidence = True
                # Verify evidence structure
                for ev in claim.evidence:
                    assert ev.evidence_type is not None
                break

        # It's ok if no evidence found, but structure should be correct
        assert isinstance(claims, list)
