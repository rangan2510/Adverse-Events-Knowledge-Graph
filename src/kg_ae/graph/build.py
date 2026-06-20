"""
Build the file-based JSON knowledge graph from silver Parquet.

Reads the normalized ``data/silver/*`` tables and emits three JSON files into
``data/graph/``:

    nodes.json   {node_type: {key: {properties}}}
    edges.json   flattened entity->entity edges carrying Claim payloads
    meta.json    build metadata + counts

This replaces the old SQL Server loaders. The graph contains only public
biomedical reference data, so the resulting JSON can be shipped as a build
artifact into an airgapped environment.

Entity keys are deterministic integers assigned by sorting each entity's
natural identifier, so rebuilds are stable. The gene node is the linchpin and
is keyed by ``symbol`` (the field common to DrugCentral/UniProt and Open
Targets/Ensembl); both ``uniprot_id`` and ``ensembl_gene_id`` are attached so
the spine joins cleanly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from rich.console import Console

from kg_ae.config import settings

console = Console()


def _safe_read(path: Path) -> pl.DataFrame | None:
    if not path.exists():
        console.print(f"[yellow][!][/yellow] missing {path}, skipping")
        return None
    return pl.read_parquet(path)


def _assign_keys(values: list[str]) -> dict[str, int]:
    """Assign deterministic 1-based integer keys to sorted unique values."""
    uniq = sorted({v for v in values if v is not None and str(v).strip()})
    return {v: i + 1 for i, v in enumerate(uniq)}


class GraphBuilder:
    """Builds the JSON graph from silver Parquet tables."""

    def __init__(self) -> None:
        self.silver = settings.silver_dir
        self.out_dir = settings.graph_dir
        # nodes[node_type][key] = {properties}
        self.nodes: dict[str, dict[int, dict[str, Any]]] = {
            "Drug": {},
            "Gene": {},
            "Pathway": {},
            "Disease": {},
            "AdverseEvent": {},
            "DrugCombination": {},
        }
        self.edges: list[dict[str, Any]] = []
        self._claim_seq = 0
        # natural-id -> key maps
        self.drug_key: dict[str, int] = {}  # drugcentral_id or stitch_id -> key
        self.gene_key: dict[str, int] = {}  # symbol -> key
        self.pathway_key: dict[str, int] = {}  # reactome_id -> key
        self.disease_key: dict[str, int] = {}  # efo_id -> key
        self.ae_key: dict[str, int] = {}  # ae_code -> key
        # helper lookups for joins
        self.uniprot_to_symbol: dict[str, str] = {}
        self.ensembl_to_symbol: dict[str, str] = {}
        self.drug_name_to_key: dict[str, int] = {}  # lowercased drug name -> key
        self.ae_label_to_key: dict[str, int] = {}  # lowercased AE label -> key
        self.disease_label_to_key: dict[str, int] = {}  # lowercased disease label -> key
        self._next_disease_key = 1  # cursor for diseases added by non-EFO sources
        self._next_gene_key = 1  # cursor for genes added by symbol-only sources
        self.datasets: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------------
    def _next_claim(self) -> int:
        self._claim_seq += 1
        return self._claim_seq

    def get_or_add_disease(self, label: str, native_id: str | None = None, source: str | None = None) -> int | None:
        """Return a disease key, merging by label to an existing node or creating one.

        Open Targets diseases are keyed by EFO; sources like CTD/ClinGen/HPO use
        MESH/OMIM/MONDO, so we merge by (lowercased) label and create a new node
        keyed off the running cursor when there is no match.
        """
        label = (label or "").strip()
        if not label:
            return None
        key = self.disease_label_to_key.get(label.lower())
        if key is not None:
            return key
        key = self._next_disease_key
        self._next_disease_key += 1
        self.nodes["Disease"][key] = {"label": label, "native_id": native_id, "source": source}
        self.disease_label_to_key[label.lower()] = key
        return key

    def get_or_add_gene(self, symbol: str) -> int | None:
        """Return a gene key by symbol, creating a minimal gene node if missing."""
        symbol = (symbol or "").strip()
        if not symbol:
            return None
        key = self.gene_key.get(symbol)
        if key is not None:
            return key
        key = self._next_gene_key
        self._next_gene_key += 1
        self.gene_key[symbol] = key
        self.nodes["Gene"][key] = {"symbol": symbol}
        return key

    def _add_edge(
        self,
        src_type: str,
        src_key: int,
        dst_type: str,
        dst_key: int,
        edge: str,
        claim_type: str,
        dataset: str,
        source_record_id: str | None,
        source_url: str | None = None,
        strength_score: float | None = None,
        frequency: float | None = None,
        relation: str | None = None,
        effect: str | None = None,
        polarity: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        claim_key = self._next_claim()
        self.edges.append(
            {
                "src_type": src_type,
                "src_key": src_key,
                "dst_type": dst_type,
                "dst_key": dst_key,
                "edge": edge,
                "claim_key": claim_key,
                "claim_type": claim_type,
                "strength_score": strength_score,
                "frequency": frequency,
                "relation": relation,
                "effect": effect,
                "polarity": polarity,
                "dataset": dataset,
                "meta": meta or {},
                "statement": {},
                "evidence": [
                    {
                        "evidence_type": claim_type,
                        "source_record_id": source_record_id,
                        "source_url": source_url,
                        "dataset": dataset,
                        "payload": meta or {},
                    }
                ],
            }
        )

    # ------------------------------------------------------------------
    # Node builders
    # ------------------------------------------------------------------
    def build_drugs(self) -> None:
        """Drugs from DrugCentral (rich) merged with SIDER (by name)."""
        dc = _safe_read(self.silver / "drugcentral" / "drugs.parquet")
        sider = _safe_read(self.silver / "sider" / "drugs.parquet")

        # Primary key space: drugcentral_id; SIDER drugs keyed by stitch_id but
        # merged onto DrugCentral when names match.
        dc_ids: list[str] = []
        name_to_key = self.drug_name_to_key  # lowercased name -> key (shared for later sources)
        if dc is not None:
            dc_ids = [str(x) for x in dc["drugcentral_id"].to_list()]
        self.drug_key = _assign_keys(dc_ids)

        if dc is not None:
            for row in dc.iter_rows(named=True):
                dcid = str(row["drugcentral_id"])
                key = self.drug_key.get(dcid)
                if key is None:
                    continue
                name = (row.get("preferred_name") or "").strip()
                self.nodes["Drug"][key] = {
                    "preferred_name": name,
                    "drugcentral_id": dcid,
                    "inchikey": row.get("inchikey"),
                    "smiles": row.get("smiles"),
                }
                if name:
                    name_to_key[name.lower()] = key

        # SIDER drugs: merge by name, else add new keyed by stitch_id.
        if sider is not None:
            next_key = (max(self.drug_key.values()) + 1) if self.drug_key else 1
            for row in sider.iter_rows(named=True):
                name = (row.get("preferred_name") or "").strip()
                stitch = str(row.get("stitch_id") or "")
                if not name:
                    continue
                key = name_to_key.get(name.lower())
                if key is None:
                    key = next_key
                    next_key += 1
                    self.nodes["Drug"][key] = {
                        "preferred_name": name,
                        "drugcentral_id": None,
                        "stitch_id": stitch,
                    }
                    name_to_key[name.lower()] = key
                else:
                    self.nodes["Drug"][key]["stitch_id"] = stitch
                # stitch_id -> key map for SIDER AE join
                if stitch:
                    self.drug_key[stitch] = key

    def build_genes(self) -> None:
        """Genes unified by symbol across DrugCentral (uniprot) and Open Targets (ensembl)."""
        dc = _safe_read(self.silver / "drugcentral" / "genes.parquet")
        ot = _safe_read(self.silver / "opentargets" / "genes.parquet")

        symbols: list[str] = []
        if dc is not None:
            symbols += [str(x) for x in dc["symbol"].to_list() if x]
        if ot is not None:
            symbols += [str(x) for x in ot["symbol"].to_list() if x]
        self.gene_key = _assign_keys(symbols)

        for key in self.gene_key.values():
            self.nodes["Gene"].setdefault(key, {})

        if dc is not None:
            for row in dc.iter_rows(named=True):
                sym = (row.get("symbol") or "").strip()
                key = self.gene_key.get(sym)
                if key is None:
                    continue
                node = self.nodes["Gene"][key]
                node["symbol"] = sym
                uni = row.get("uniprot_id")
                if uni:
                    node["uniprot_id"] = uni
                    self.uniprot_to_symbol[str(uni)] = sym

        if ot is not None:
            for row in ot.iter_rows(named=True):
                sym = (row.get("symbol") or "").strip()
                key = self.gene_key.get(sym)
                if key is None:
                    continue
                node = self.nodes["Gene"][key]
                node.setdefault("symbol", sym)
                ens = row.get("ensembl_gene_id")
                if ens:
                    node["ensembl_gene_id"] = ens
                    self.ensembl_to_symbol[str(ens)] = sym
                uni = row.get("uniprot_id")
                if uni and "uniprot_id" not in node:
                    node["uniprot_id"] = uni
                    self.uniprot_to_symbol.setdefault(str(uni), sym)

        # Genes added by symbol-only sources (STRING/HPO/CTD) start after these.
        self._next_gene_key = (max(self.gene_key.values()) + 1) if self.gene_key else 1

    def build_pathways(self) -> None:
        react = _safe_read(self.silver / "reactome" / "pathways.parquet")
        if react is None:
            return
        ids = [str(x) for x in react["reactome_id"].to_list() if x]
        self.pathway_key = _assign_keys(ids)
        for row in react.iter_rows(named=True):
            rid = str(row.get("reactome_id") or "")
            key = self.pathway_key.get(rid)
            if key is None:
                continue
            self.nodes["Pathway"][key] = {
                "label": (row.get("label") or "").strip(),
                "reactome_id": rid,
            }

    def build_diseases(self) -> None:
        ot = _safe_read(self.silver / "opentargets" / "diseases.parquet")
        if ot is None:
            return
        ids = [str(x) for x in ot["efo_id"].to_list() if x]
        self.disease_key = _assign_keys(ids)
        for row in ot.iter_rows(named=True):
            efo = str(row.get("efo_id") or "")
            key = self.disease_key.get(efo)
            if key is None:
                continue
            label = (row.get("label") or "").strip()
            self.nodes["Disease"][key] = {
                "label": label,
                "efo_id": efo,
                "mondo_id": row.get("mondo_id"),
            }
            if label:
                self.disease_label_to_key.setdefault(label.lower(), key)
        # Diseases added by non-EFO sources (CTD/ClinGen/HPO) start after EFO keys.
        self._next_disease_key = (max(self.disease_key.values()) + 1) if self.disease_key else 1

    def build_adverse_events(self) -> None:
        sider = _safe_read(self.silver / "sider" / "adverse_events.parquet")
        onsides = _safe_read(self.silver / "onsides" / "adverse_events.parquet")

        next_key = 1
        if sider is not None:
            codes = [str(x) for x in sider["ae_code"].to_list() if x]
            self.ae_key = _assign_keys(codes)
            next_key = (max(self.ae_key.values()) + 1) if self.ae_key else 1
            for row in sider.iter_rows(named=True):
                code = str(row.get("ae_code") or "")
                key = self.ae_key.get(code)
                if key is None:
                    continue
                label = (row.get("ae_label") or "").strip()
                self.nodes["AdverseEvent"][key] = {
                    "ae_label": label,
                    "ae_code": code,
                    "ae_ontology": row.get("ae_ontology"),
                }
                if label:
                    self.ae_label_to_key.setdefault(label.lower(), key)

        # OnSIDES AEs: merge by label, else add new (keyed by MedDRA term).
        if onsides is not None:
            for row in onsides.iter_rows(named=True):
                label = (row.get("ae_label") or "").strip()
                if not label:
                    continue
                key = self.ae_label_to_key.get(label.lower())
                if key is None:
                    key = next_key
                    next_key += 1
                    self.nodes["AdverseEvent"][key] = {
                        "ae_label": label,
                        "meddra_id": row.get("meddra_id"),
                        "ae_ontology": "MedDRA",
                    }
                    self.ae_label_to_key[label.lower()] = key

    # ------------------------------------------------------------------
    # Edge builders
    # ------------------------------------------------------------------
    def build_drug_gene_edges(self) -> None:
        """Drug -> Gene from DrugCentral interactions (mechanism of action)."""
        inter = _safe_read(self.silver / "drugcentral" / "interactions.parquet")
        if inter is None:
            return
        for row in inter.iter_rows(named=True):
            dcid = str(row.get("drugcentral_id") or "")
            sym = (row.get("gene_symbol") or "").strip()
            dkey = self.drug_key.get(dcid)
            gkey = self.gene_key.get(sym)
            if dkey is None or gkey is None:
                continue
            self._add_edge(
                src_type="Drug",
                src_key=dkey,
                dst_type="Gene",
                dst_key=gkey,
                edge="ClaimGene",
                claim_type="DRUG_TARGET",
                dataset="drugcentral",
                source_record_id=dcid,
                source_url=row.get("MOA_SOURCE_URL") or row.get("ACT_SOURCE_URL"),
                strength_score=1.0,
                relation=row.get("RELATION") or row.get("action_type"),
                effect=row.get("mechanism_of_action") or row.get("action_type"),
                meta={
                    "activity_type": row.get("activity_type"),
                    "activity_value": row.get("activity_value"),
                    "activity_unit": row.get("activity_unit"),
                    "target_class": row.get("target_class"),
                },
            )

    def build_bindingdb_edges(self) -> None:
        """Drug -> Gene from BindingDB (quantitative binding affinities).

        Joins ligand-by-name to existing drug nodes and target UniProt ID to a
        gene symbol via the uniprot->symbol map built from DrugCentral/OpenTargets.
        """
        inter = _safe_read(self.silver / "bindingdb" / "interactions.parquet")
        if inter is None:
            return
        for row in inter.iter_rows(named=True):
            name = (row.get("ligand_name") or "").strip().lower()
            uni = str(row.get("uniprot_id") or "")
            dkey = self.drug_name_to_key.get(name)
            sym = self.uniprot_to_symbol.get(uni)
            gkey = self.gene_key.get(sym) if sym else None
            if dkey is None or gkey is None:
                continue
            self._add_edge(
                src_type="Drug",
                src_key=dkey,
                dst_type="Gene",
                dst_key=gkey,
                edge="ClaimGene",
                claim_type="DRUG_TARGET_BINDINGDB",
                dataset="bindingdb",
                source_record_id=f"{name}:{uni}",
                strength_score=row.get("strength_score"),
                relation="binds",
                meta={
                    "affinity_nm": row.get("affinity_nm"),
                    "affinity_type": row.get("affinity_type"),
                    "uniprot_id": uni,
                },
            )

    def build_gtop_edges(self) -> None:
        """Drug -> Gene from Guide to Pharmacology (curated pharmacology)."""
        inter = _safe_read(self.silver / "gtop" / "interactions.parquet")
        if inter is None:
            return
        for row in inter.iter_rows(named=True):
            name = (row.get("drug_name") or "").strip().lower()
            sym = (row.get("gene_symbol") or "").strip()
            dkey = self.drug_name_to_key.get(name)
            gkey = self.get_or_add_gene(sym)
            if dkey is None or gkey is None:
                continue
            self._add_edge(
                src_type="Drug",
                src_key=dkey,
                dst_type="Gene",
                dst_key=gkey,
                edge="ClaimGene",
                claim_type="DRUG_TARGET_GTOP",
                dataset="gtop",
                source_record_id=f"{name}:{sym}",
                strength_score=0.85,
                relation=row.get("action") or row.get("interaction_type"),
                effect=row.get("action"),
                meta={"affinity_median": row.get("affinity_median")},
            )

    def build_ctd_edges(self) -> None:
        """Drug -> Gene and Gene -> Disease from CTD."""
        cg = _safe_read(self.silver / "ctd" / "chem_gene.parquet")
        if cg is not None:
            for row in cg.iter_rows(named=True):
                name = (row.get("drug_name") or "").strip().lower()
                sym = (row.get("gene_symbol") or "").strip()
                dkey = self.drug_name_to_key.get(name)
                gkey = self.get_or_add_gene(sym)
                if dkey is None or gkey is None:
                    continue
                self._add_edge(
                    src_type="Drug",
                    src_key=dkey,
                    dst_type="Gene",
                    dst_key=gkey,
                    edge="ClaimGene",
                    claim_type="DRUG_GENE_CTD",
                    dataset="ctd",
                    source_record_id=f"{name}:{sym}",
                    strength_score=0.7,
                    relation=row.get("interaction_actions"),
                )

        gd = _safe_read(self.silver / "ctd" / "gene_disease.parquet")
        if gd is not None:
            for row in gd.iter_rows(named=True):
                sym = (row.get("gene_symbol") or "").strip()
                label = (row.get("disease_label") or "").strip()
                gkey = self.get_or_add_gene(sym)
                dkey = self.get_or_add_disease(label, native_id=row.get("disease_id"), source="ctd")
                if gkey is None or dkey is None:
                    continue
                score = row.get("inference_score")
                self._add_edge(
                    src_type="Gene",
                    src_key=gkey,
                    dst_type="Disease",
                    dst_key=dkey,
                    edge="ClaimDisease",
                    claim_type="GENE_DISEASE_CTD",
                    dataset="ctd",
                    source_record_id=f"{sym}:{row.get('disease_id')}",
                    strength_score=(float(score) / 100.0 if score else None),
                    meta={"direct_evidence": row.get("direct_evidence")},
                )

    def build_clingen_edges(self) -> None:
        """Gene -> Disease from ClinGen curated validity."""
        gd = _safe_read(self.silver / "clingen" / "gene_disease.parquet")
        if gd is None:
            return
        for row in gd.iter_rows(named=True):
            sym = (row.get("gene_symbol") or "").strip()
            label = (row.get("disease_label") or "").strip()
            gkey = self.get_or_add_gene(sym)
            dkey = self.get_or_add_disease(label, native_id=row.get("mondo_id"), source="clingen")
            if gkey is None or dkey is None:
                continue
            self._add_edge(
                src_type="Gene",
                src_key=gkey,
                dst_type="Disease",
                dst_key=dkey,
                edge="ClaimDisease",
                claim_type="GENE_DISEASE_CLINGEN",
                dataset="clingen",
                source_record_id=f"{sym}:{row.get('mondo_id')}",
                strength_score=row.get("score"),
                meta={"classification": row.get("classification")},
            )

    def build_hpo_edges(self) -> None:
        """Gene -> Disease from HPO genes_to_phenotype."""
        gd = _safe_read(self.silver / "hpo" / "gene_disease.parquet")
        if gd is None:
            return
        for row in gd.iter_rows(named=True):
            sym = (row.get("gene_symbol") or "").strip()
            label = (row.get("disease_label") or "").strip()
            gkey = self.get_or_add_gene(sym)
            dkey = self.get_or_add_disease(label, native_id=row.get("disease_id"), source="hpo")
            if gkey is None or dkey is None:
                continue
            self._add_edge(
                src_type="Gene",
                src_key=gkey,
                dst_type="Disease",
                dst_key=dkey,
                edge="ClaimDisease",
                claim_type="GENE_PHENOTYPE_HPO",
                dataset="hpo",
                source_record_id=f"{sym}:{row.get('disease_id')}",
                strength_score=0.6,
            )

    def build_string_edges(self) -> None:
        """Gene -> Gene protein-protein interactions from STRING."""
        links = _safe_read(self.silver / "string" / "interactions.parquet")
        if links is None:
            return
        for row in links.iter_rows(named=True):
            g1 = (row.get("gene_1") or "").strip()
            g2 = (row.get("gene_2") or "").strip()
            k1 = self.gene_key.get(g1)
            k2 = self.gene_key.get(g2)
            # Only connect genes that already exist (avoid exploding the gene set).
            if k1 is None or k2 is None:
                continue
            self._add_edge(
                src_type="Gene",
                src_key=k1,
                dst_type="Gene",
                dst_key=k2,
                edge="ClaimGene",
                claim_type="GENE_GENE_STRING",
                dataset="string",
                source_record_id=f"{g1}:{g2}",
                strength_score=row.get("score"),
            )

    def build_faers_ae_edges(self) -> None:
        """Drug -> AdverseEvent disproportionality signals from FAERS."""
        sig = _safe_read(self.silver / "faers" / "signals.parquet")
        if sig is None:
            return
        for row in sig.iter_rows(named=True):
            name = (row.get("drug_name") or "").strip().lower()
            label = (row.get("ae_label") or "").strip()
            dkey = self.drug_name_to_key.get(name)
            akey = self.ae_label_to_key.get(label.lower()) if label else None
            if dkey is None or akey is None:
                continue
            self._add_edge(
                src_type="Drug",
                src_key=dkey,
                dst_type="AdverseEvent",
                dst_key=akey,
                edge="ClaimAdverseEvent",
                claim_type="DRUG_AE_FAERS",
                dataset="faers",
                source_record_id=f"{name}:{label}",
                strength_score=row.get("prr"),
                meta={
                    "prr": row.get("prr"),
                    "ror": row.get("ror"),
                    "chi2": row.get("chi2"),
                    "count": row.get("report_count"),
                },
            )

    def build_openfda_label_edges(self) -> None:
        """Drug -> AdverseEvent label-section claims from openFDA."""
        labels = _safe_read(self.silver / "openfda" / "labels.parquet")
        if labels is None:
            return
        sections = ["adverse_reactions", "warnings", "contraindications", "boxed_warning", "drug_interactions"]
        for row in labels.iter_rows(named=True):
            name = (row.get("drug_name") or "").strip().lower()
            dkey = self.drug_name_to_key.get(name)
            if dkey is None:
                continue
            payload = {s: row.get(s) for s in sections if row.get(s)}
            if not payload:
                continue
            # A DRUG_LABEL claim attaches the label sections as evidence payload.
            claim_key = self._next_claim()
            self.edges.append(
                {
                    "src_type": "Drug",
                    "src_key": dkey,
                    "dst_type": "Drug",
                    "dst_key": dkey,
                    "edge": "HasClaim",
                    "claim_key": claim_key,
                    "claim_type": "DRUG_LABEL",
                    "dataset": "openfda",
                    "strength_score": None,
                    "meta": {},
                    "statement": {
                        "brand_name": row.get("brand_name"),
                        "effective_date": row.get("effective_time"),
                    },
                    "evidence": [
                        {
                            "evidence_type": "DRUG_LABEL",
                            "source_record_id": name,
                            "dataset": "openfda",
                            "payload": payload,
                        }
                    ],
                }
            )

    def build_gene_pathway_edges(self) -> None:
        """Gene -> Pathway from Reactome (joined via uniprot_id)."""
        gp = _safe_read(self.silver / "reactome" / "gene_pathways.parquet")
        if gp is None:
            return
        for row in gp.iter_rows(named=True):
            uni = str(row.get("uniprot_id") or "")
            rid = str(row.get("reactome_id") or "")
            sym = self.uniprot_to_symbol.get(uni)
            gkey = self.gene_key.get(sym) if sym else None
            pkey = self.pathway_key.get(rid)
            if gkey is None or pkey is None:
                continue
            self._add_edge(
                src_type="Gene",
                src_key=gkey,
                dst_type="Pathway",
                dst_key=pkey,
                edge="ClaimPathway",
                claim_type="GENE_PATHWAY",
                dataset="reactome",
                source_record_id=f"{uni}:{rid}",
                strength_score=0.9,
                meta={"evidence_code": row.get("evidence_code")},
            )

    def build_gene_disease_edges(self) -> None:
        """Gene -> Disease from Open Targets (joined via ensembl_gene_id)."""
        assoc = _safe_read(self.silver / "opentargets" / "associations.parquet")
        if assoc is None:
            return
        for row in assoc.iter_rows(named=True):
            ens = str(row.get("ensembl_gene_id") or "")
            efo = str(row.get("efo_id") or "")
            sym = self.ensembl_to_symbol.get(ens)
            gkey = self.gene_key.get(sym) if sym else None
            dkey = self.disease_key.get(efo)
            if gkey is None or dkey is None:
                continue
            self._add_edge(
                src_type="Gene",
                src_key=gkey,
                dst_type="Disease",
                dst_key=dkey,
                edge="ClaimDisease",
                claim_type="GENE_DISEASE",
                dataset="opentargets",
                source_record_id=f"{ens}:{efo}",
                strength_score=row.get("score"),
                meta={},
            )

    def build_drug_ae_edges(self) -> None:
        """Drug -> AdverseEvent from SIDER (joined via stitch_id)."""
        pairs = _safe_read(self.silver / "sider" / "drug_ae_pairs.parquet")
        if pairs is None:
            return
        for row in pairs.iter_rows(named=True):
            stitch = str(row.get("stitch_id") or "")
            code = str(row.get("ae_code") or "")
            dkey = self.drug_key.get(stitch)
            akey = self.ae_key.get(code)
            if dkey is None or akey is None:
                continue
            self._add_edge(
                src_type="Drug",
                src_key=dkey,
                dst_type="AdverseEvent",
                dst_key=akey,
                edge="ClaimAdverseEvent",
                claim_type="DRUG_AE_SIDER",
                dataset="sider",
                source_record_id=f"{stitch}:{code}",
                frequency=row.get("frequency_score"),
                strength_score=row.get("frequency_score"),
                meta={"frequency_text": row.get("frequency_text")},
            )

    def build_onsides_ae_edges(self) -> None:
        """Drug -> AdverseEvent from OnSIDES (joined by drug name + AE label)."""
        pairs = _safe_read(self.silver / "onsides" / "drug_ae_pairs.parquet")
        if pairs is None:
            return
        for row in pairs.iter_rows(named=True):
            name = (row.get("drug_name") or "").strip().lower()
            label = (row.get("ae_label") or "").strip().lower()
            dkey = self.drug_name_to_key.get(name)
            akey = self.ae_label_to_key.get(label)
            if dkey is None or akey is None:
                continue
            self._add_edge(
                src_type="Drug",
                src_key=dkey,
                dst_type="AdverseEvent",
                dst_key=akey,
                edge="ClaimAdverseEvent",
                claim_type="DRUG_AE_ONSIDES",
                dataset="onsides",
                source_record_id=f"{name}:{row.get('meddra_id')}",
                strength_score=row.get("confidence"),
                meta={"sources": row.get("sources"), "meddra_id": row.get("meddra_id")},
            )

    def build_twosides_edges(self) -> None:
        """Drug+Drug -> AdverseEvent from TWOSIDES via a DrugCombination node.

        Models the ternary DDI relation as: Drug1 -> Combination, Drug2 ->
        Combination, Combination -> AdverseEvent. Combination nodes are keyed by
        the sorted pair of drug keys so the same pair reuses one node.
        """
        ddi = _safe_read(self.silver / "twosides" / "ddi_ae.parquet")
        if ddi is None:
            return

        combo_key: dict[tuple[int, int], int] = {}
        next_combo = 1

        for row in ddi.iter_rows(named=True):
            n1 = (row.get("drug_1") or "").strip().lower()
            n2 = (row.get("drug_2") or "").strip().lower()
            label = (row.get("ae_label") or "").strip()
            d1 = self.drug_name_to_key.get(n1)
            d2 = self.drug_name_to_key.get(n2)
            akey = self.ae_label_to_key.get(label.lower()) if label else None
            if d1 is None or d2 is None or akey is None:
                continue

            pair = (min(d1, d2), max(d1, d2))
            ckey = combo_key.get(pair)
            if ckey is None:
                ckey = next_combo
                next_combo += 1
                combo_key[pair] = ckey
                self.nodes["DrugCombination"][ckey] = {
                    "label": f"{self.node_label_for('Drug', d1)} + {self.node_label_for('Drug', d2)}",
                    "drug_keys": [pair[0], pair[1]],
                }
                # Drug -> Combination membership edges (once per pair).
                for dk in pair:
                    self._add_edge(
                        src_type="Drug",
                        src_key=dk,
                        dst_type="DrugCombination",
                        dst_key=ckey,
                        edge="DrugInCombination",
                        claim_type="DRUG_IN_COMBINATION",
                        dataset="twosides",
                        source_record_id=f"{pair[0]}+{pair[1]}",
                    )

            prr = row.get("prr")
            self._add_edge(
                src_type="DrugCombination",
                src_key=ckey,
                dst_type="AdverseEvent",
                dst_key=akey,
                edge="ClaimAdverseEvent",
                claim_type="DDI_AE_TWOSIDES",
                dataset="twosides",
                source_record_id=f"{pair[0]}+{pair[1]}:{row.get('condition_meddra_id')}",
                strength_score=prr,
                meta={"prr": prr, "report_count": row.get("report_count")},
            )

    def node_label_for(self, node_type: str, key: int) -> str:
        """Return a node's label during build (for composing combination labels)."""
        props = self.nodes.get(node_type, {}).get(key, {})
        if node_type == "Drug":
            return str(props.get("preferred_name", "") or "")
        return str(props.get("label", "") or "")

    # ------------------------------------------------------------------
    def build(self) -> dict[str, int]:
        console.print("[cyan][>][/cyan] Building nodes...")
        self.build_drugs()
        self.build_genes()
        self.build_pathways()
        self.build_diseases()
        self.build_adverse_events()

        console.print("[cyan][>][/cyan] Building edges...")
        self.build_drug_gene_edges()
        self.build_bindingdb_edges()
        self.build_gtop_edges()
        self.build_ctd_edges()
        self.build_gene_pathway_edges()
        self.build_gene_disease_edges()
        self.build_clingen_edges()
        self.build_hpo_edges()
        self.build_string_edges()
        self.build_drug_ae_edges()
        self.build_onsides_ae_edges()
        self.build_faers_ae_edges()
        self.build_openfda_label_edges()
        self.build_twosides_edges()

        return self.write()

    def write(self) -> dict[str, int]:
        self.out_dir.mkdir(parents=True, exist_ok=True)

        # Drop empty gene nodes (symbols that never got properties)
        self.nodes["Gene"] = {k: v for k, v in self.nodes["Gene"].items() if v.get("symbol")}

        nodes_serialized = {nt: {str(k): v for k, v in by_key.items()} for nt, by_key in self.nodes.items()}

        # Validate the artifact before writing (fail fast at staging time).
        from kg_ae.graph.validate import validate_graph

        errors = validate_graph(nodes_serialized, self.edges)
        if errors:
            raise ValueError("Graph validation failed:\n  - " + "\n  - ".join(errors))

        (self.out_dir / "nodes.json").write_text(json.dumps(nodes_serialized, ensure_ascii=False), encoding="utf-8")
        (self.out_dir / "edges.json").write_text(json.dumps(self.edges, ensure_ascii=False), encoding="utf-8")

        counts = {nt: len(by_key) for nt, by_key in self.nodes.items()}
        counts["edges"] = len(self.edges)

        # Per-dataset edge counts for provenance + the license posture of the build.
        edges_by_dataset: dict[str, int] = {}
        for e in self.edges:
            ds = e.get("dataset") or "?"
            edges_by_dataset[ds] = edges_by_dataset.get(ds, 0) + 1

        meta = {
            "built_at": datetime.now(UTC).isoformat(),
            "counts": counts,
            "datasets": sorted(edges_by_dataset.keys()),
            "edges_by_dataset": edges_by_dataset,
        }
        (self.out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return counts


def build_graph() -> dict[str, int]:
    """Build the JSON graph and return node/edge counts."""
    counts = GraphBuilder().build()
    console.print(f"[green][ok][/green] Graph written to {settings.graph_dir}")
    for k, v in counts.items():
        console.print(f"    {k}: {v:,}")
    return counts
