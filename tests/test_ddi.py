"""Tests for the drug-drug interaction (TWOSIDES / DrugCombination) capability.

These build a tiny JSON graph in a temp dir and point a GraphStore at it, so
they validate the combination traversal deterministically without the full
built graph.
"""

import json
from pathlib import Path

import pytest

from kg_ae.graph.store import GraphStore


def _write_graph(tmp: Path, nodes: dict, edges: list) -> None:
    (tmp / "nodes.json").write_text(json.dumps(nodes), encoding="utf-8")
    (tmp / "edges.json").write_text(json.dumps(edges), encoding="utf-8")
    (tmp / "meta.json").write_text(json.dumps({"counts": {}}), encoding="utf-8")


@pytest.fixture
def ddi_store(tmp_path: Path, monkeypatch) -> GraphStore:
    """A tiny graph: drugs 1,2,3; combination 1 = {1,2} -> AE 10; AE 11 via combo 2={1,3}."""
    nodes = {
        "Drug": {
            "1": {"preferred_name": "atorvastatin"},
            "2": {"preferred_name": "metformin"},
            "3": {"preferred_name": "clopidogrel"},
        },
        "AdverseEvent": {"10": {"ae_label": "Myalgia"}, "11": {"ae_label": "Rhabdomyolysis"}},
        "DrugCombination": {
            "1": {"label": "atorvastatin + metformin", "drug_keys": [1, 2]},
            "2": {"label": "atorvastatin + clopidogrel", "drug_keys": [1, 3]},
        },
    }
    edges = [
        {
            "src_type": "Drug",
            "src_key": 1,
            "dst_type": "DrugCombination",
            "dst_key": 1,
            "edge": "DrugInCombination",
            "claim_type": "DRUG_IN_COMBINATION",
            "dataset": "twosides",
        },
        {
            "src_type": "Drug",
            "src_key": 2,
            "dst_type": "DrugCombination",
            "dst_key": 1,
            "edge": "DrugInCombination",
            "claim_type": "DRUG_IN_COMBINATION",
            "dataset": "twosides",
        },
        {
            "src_type": "Drug",
            "src_key": 1,
            "dst_type": "DrugCombination",
            "dst_key": 2,
            "edge": "DrugInCombination",
            "claim_type": "DRUG_IN_COMBINATION",
            "dataset": "twosides",
        },
        {
            "src_type": "Drug",
            "src_key": 3,
            "dst_type": "DrugCombination",
            "dst_key": 2,
            "edge": "DrugInCombination",
            "claim_type": "DRUG_IN_COMBINATION",
            "dataset": "twosides",
        },
        {
            "src_type": "DrugCombination",
            "src_key": 1,
            "dst_type": "AdverseEvent",
            "dst_key": 10,
            "edge": "ClaimAdverseEvent",
            "claim_type": "DDI_AE_TWOSIDES",
            "dataset": "twosides",
            "strength_score": 3.5,
            "meta": {"prr": 3.5, "report_count": 120},
        },
        {
            "src_type": "DrugCombination",
            "src_key": 2,
            "dst_type": "AdverseEvent",
            "dst_key": 11,
            "edge": "ClaimAdverseEvent",
            "claim_type": "DDI_AE_TWOSIDES",
            "dataset": "twosides",
            "strength_score": 8.1,
            "meta": {"prr": 8.1, "report_count": 45},
        },
    ]
    _write_graph(tmp_path, nodes, edges)
    store = GraphStore(tmp_path)
    # Point the tool's get_store() at this store.
    monkeypatch.setattr("kg_ae.tools.adverse_events.get_store", lambda: store)
    return store


def test_ddi_returns_combination_ae(ddi_store):
    from kg_ae.tools.adverse_events import get_drug_drug_interactions

    ddis = get_drug_drug_interactions(1, 2)
    assert len(ddis) == 1
    assert ddis[0].ae_label == "Myalgia"
    assert ddis[0].prr == 3.5
    assert ddis[0].report_count == 120


def test_ddi_only_shared_combination(ddi_store):
    from kg_ae.tools.adverse_events import get_drug_drug_interactions

    # Drugs 2 and 3 share no combination -> no DDIs.
    assert get_drug_drug_interactions(2, 3) == []


def test_ddi_symmetric(ddi_store):
    from kg_ae.tools.adverse_events import get_drug_drug_interactions

    assert {d.ae_label for d in get_drug_drug_interactions(1, 2)} == {
        d.ae_label for d in get_drug_drug_interactions(2, 1)
    }


def test_drugcombination_node_label(ddi_store):
    assert ddi_store.node_label("DrugCombination", 1) == "atorvastatin + metformin"
