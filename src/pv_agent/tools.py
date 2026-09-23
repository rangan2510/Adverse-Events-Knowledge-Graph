"""Tools the model can call, plus the reference store that makes citations checkable.

Every piece of retrieved text is stored under an id like `ref:7`. Tool results carry those ids
instead of asking the model to cite URLs from memory. The verify step later confirms each cited
id exists and each quoted number appears in that reference's text.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Annotated, Any

from langchain_core.tools import tool
from pydantic import Field

from pv_agent.sources import aopwiki, chembl, dgidb, ema, europepmc, openfda, opentargets, pathways, rxnorm, web
from pv_agent.sources.http import SourceUnavailable

MAX_CHARS = 7_000
MAX_SECTION = 2_800


@dataclass
class Ref:
    id: str
    source: str
    title: str
    url: str
    text: str
    caution: str | None = None


@dataclass
class RefStore:
    refs: dict[str, Ref] = field(default_factory=dict)

    def add(self, source: str, title: str, url: str, text: str, caution: str | None = None) -> str:
        rid = f"ref:{len(self.refs) + 1}"
        self.refs[rid] = Ref(rid, source, title, url, " ".join(text.split()), caution)
        return rid

    def get(self, rid: str) -> Ref | None:
        return self.refs.get(rid)


# One store per question. graph.py resets it at the start of each turn.
STORE = RefStore()


def _clip(text: str, limit: int = MAX_SECTION) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " [truncated]"


def _fit(payload: dict[str, Any], key: str) -> dict[str, Any]:
    """Drop items from the main list until the payload fits the budget."""
    while len(json.dumps(payload, default=str)) > MAX_CHARS and len(payload.get(key) or []) > 1:
        payload[key] = payload[key][:-1]
        payload["truncated"] = True
    return payload


def _fit_sections(payload: dict[str, Any]) -> dict[str, Any]:
    """Shrink the longest section text until the payload fits. The full text stays in STORE."""
    secs = payload["sections"]
    while len(json.dumps(payload, default=str)) > MAX_CHARS:
        longest = max((k for k in secs if "text" in secs[k]), key=lambda k: len(secs[k]["text"]), default=None)
        if longest is None or len(secs[longest]["text"]) <= 400:
            break
        secs[longest]["text"] = _clip(secs[longest]["text"], len(secs[longest]["text"]) * 2 // 3)
        payload["truncated"] = True
    return payload


def _fail(source: str, exc: Exception) -> dict[str, Any]:
    return {"error": f"{source}: {exc}"}


@tool
def resolve_drug(
    name: Annotated[str, Field(description="Drug name as the user wrote it: generic, brand, any spelling.")],
) -> dict:
    """Resolve a drug name to its standard identity. Call this first for every drug mentioned.

    Handles British and INN spellings (ciclosporin), brand names (Neoral), combinations
    (co-trimoxazole) and typos. Returns the RxNorm generic name that every other tool expects,
    the ChEMBL id, the ATC class, and both US and EU product lists.
    """
    try:
        d = rxnorm.resolve(name)
    except SourceUnavailable as exc:
        return _fail("RxNorm", exc)
    if not d:
        return {"query": name, "resolved": False, "note": "No match in RxNorm. Ask the user to confirm the drug name."}

    out: dict[str, Any] = {
        "query": name,
        "resolved": True,
        "generic_name": d.name,
        "rxcui": d.rxcui,
        "match": d.match,
        "brands": d.brands[:10],
        "atc_classes": d.atc_classes[:5],
    }
    try:
        m = chembl.find_molecule(d.name.split(" / ")[0])
        out["chembl_id"] = m.chembl_id if m else None
    except SourceUnavailable:
        out["chembl_id"] = None
    try:
        out["eu_products"] = [{"name": p.name, "atc": p.atc, "generic": p.generic} for p in ema.find(d.name, name)[:6]]
    except SourceUnavailable as exc:
        out["eu_products_error"] = str(exc)
    return out


@tool
def get_us_label(
    generic_name: Annotated[str, Field(description="Generic name from resolve_drug.")],
    sections: Annotated[
        list[str],
        Field(
            description=(
                "From: boxed_warning, contraindications, warnings, adverse_reactions, "
                "drug_interactions, clinical_pharmacology, dosage."
            )
        ),
    ],
) -> dict:
    """Read sections of the current US FDA label (systemic product). Strongest US evidence."""
    try:
        labs = openfda.labels(generic_name)
    except SourceUnavailable as exc:
        return _fail("openFDA", exc)
    if not labs:
        return {"drug": generic_name, "found": False, "note": "No systemic US label under this generic name."}
    lab = labs[0]
    out: dict[str, Any] = {
        "drug": generic_name,
        "found": True,
        "product": lab.brand,
        "route": lab.route,
        "effective": lab.effective,
        "sections": {},
    }
    for sec in sections:
        text = lab.sections.get(sec)
        if text:
            rid = STORE.add("FDA label", f"{lab.brand} label, {sec}", lab.url, text)
            out["sections"][sec] = {"ref": rid, "text": _clip(text)}
        else:
            out["sections"][sec] = {"note": "section absent from this label"}
    return _fit_sections(out)


@tool
def get_eu_label(
    generic_name: Annotated[str, Field(description="Generic name from resolve_drug.")],
    sections: Annotated[
        list[str],
        Field(
            description=(
                "SmPC section numbers from: 4.2 posology, 4.3 contraindications, 4.4 warnings, "
                "4.5 interactions, 4.8 undesirable effects, 5.2 pharmacokinetics."
            )
        ),
    ],
) -> dict:
    """Read sections of the EU Summary of Product Characteristics (EMA). Strongest EU evidence.

    Only centrally authorised products are covered; older drugs approved nationally
    (cyclosporine, atorvastatin) have no EMA SmPC and return found=false.
    """
    try:
        prods = ema.find(generic_name)
    except SourceUnavailable as exc:
        return _fail("EMA", exc)
    if not prods:
        return {
            "drug": generic_name,
            "found": False,
            "note": "Not centrally authorised by EMA; no EU SmPC available here.",
        }
    prod = prods[0]
    try:
        s = ema.smpc(prod, tuple(sections))
    except SourceUnavailable as exc:
        return _fail("EMA SmPC", exc)
    out: dict[str, Any] = {"drug": generic_name, "found": True, "product": prod.name, "atc": prod.atc, "sections": {}}
    for num in sections:
        text = s.sections.get(num)
        if text:
            rid = STORE.add("EMA SmPC", f"{prod.name} SmPC section {num}", prod.smpc_url, text)
            out["sections"][num] = {"ref": rid, "text": _clip(text)}
        else:
            out["sections"][num] = {"note": "section not extracted"}
    return _fit_sections(out)


@tool
def get_reported_events(generic_name: Annotated[str, Field(description="Generic name from resolve_drug.")]) -> dict:
    """Adverse events reported with a drug: FAERS counts and Open Targets disproportionality.

    Counts are report volume, not incidence and not causation. The logLR signal marks events
    reported disproportionately for this drug against all of FAERS; above_threshold=true is
    a statistical signal worth mentioning, still not proof.
    """
    out: dict[str, Any] = {"drug": generic_name}
    try:
        counts = openfda.reaction_counts(generic_name, 15)
        rid = STORE.add(
            "FAERS",
            f"FAERS top reactions for {generic_name}",
            "https://open.fda.gov/apis/drug/event/",
            json.dumps(counts),
        )
        out["faers_top_reactions"] = {"ref": rid, "rows": [{"event": e, "reports": n} for e, n in counts]}
    except SourceUnavailable as exc:
        out["faers_error"] = str(exc)
    try:
        m = chembl.find_molecule(generic_name.split(" / ")[0])
        if m:
            sig = opentargets.signals(m.chembl_id, 12)
            rid = STORE.add(
                "Open Targets",
                f"FAERS disproportionality for {generic_name}",
                f"https://platform.opentargets.org/drug/{m.chembl_id}",
                json.dumps([s.__dict__ for s in sig]),
            )
            out["disproportionality"] = {
                "ref": rid,
                "rows": [
                    {"event": s.event, "reports": s.count, "logLR": round(s.log_lr), "signal": s.above_threshold}
                    for s in sig
                ],
            }
    except SourceUnavailable as exc:
        out["signals_error"] = str(exc)
    out["caveat"] = "Spontaneous reports. Not a rate, not causality."
    return out


@tool
def get_pair_reports(
    drug_a: Annotated[str, Field(description="Generic name.")],
    drug_b: Annotated[str, Field(description="Generic name.")],
    event: Annotated[str | None, Field(description="Optional MedDRA term to narrow to, e.g. Rhabdomyolysis.")] = None,
) -> dict:
    """FAERS reports naming two drugs together, with each drug's own total as denominators.

    Co-reporting shows the drugs are used together; it is not interaction evidence.
    """
    try:
        c = openfda.pair_counts(drug_a, drug_b, event)
    except SourceUnavailable as exc:
        return _fail("openFDA", exc)
    rid = STORE.add(
        "FAERS",
        f"FAERS co-reports {drug_a} + {drug_b}",
        "https://open.fda.gov/apis/drug/event/",
        json.dumps(c.__dict__),
    )
    return {"ref": rid, **c.__dict__, "caveat": "Co-reporting is not interaction evidence."}


@tool
def get_mechanism(generic_name: Annotated[str, Field(description="Generic name from resolve_drug.")]) -> dict:
    """Molecular targets, mechanism of action, and regulatory black-box warnings.

    Open Targets and ChEMBL rows are curated. DGIdb rows marked curated=false are statistical
    associations, not established pharmacology.
    """
    out: dict[str, Any] = {"drug": generic_name, "targets": [], "warnings": [], "dgidb": []}
    try:
        m = chembl.find_molecule(generic_name.split(" / ")[0])
    except SourceUnavailable as exc:
        return _fail("ChEMBL", exc)
    if m:
        out["chembl_id"] = m.chembl_id
        try:
            ts = opentargets.targets(m.chembl_id)
            if ts:
                rid = STORE.add(
                    "Open Targets",
                    f"Mechanism of {generic_name}",
                    f"https://platform.opentargets.org/drug/{m.chembl_id}",
                    json.dumps([t.__dict__ for t in ts]),
                )
                out["targets"] = {"ref": rid, "rows": [t.__dict__ for t in ts[:8]]}
        except SourceUnavailable as exc:
            out["targets_error"] = str(exc)
        try:
            ws = chembl.warnings(m.chembl_id)
            if ws:
                rid = STORE.add(
                    "ChEMBL",
                    f"Regulatory warnings for {generic_name}",
                    f"https://www.ebi.ac.uk/chembl/compound_report_card/{m.chembl_id}/",
                    json.dumps([w.__dict__ for w in ws]),
                )
                out["warnings"] = {"ref": rid, "rows": [w.__dict__ for w in ws[:8]]}
        except SourceUnavailable as exc:
            out["warnings_error"] = str(exc)
    try:
        rows = dgidb.drug_targets(generic_name.split(" / ")[0], 8)
        out["dgidb"] = [
            {"gene": r.gene, "types": r.types, "curated": r.curated, "sources": len(r.sources)} for r in rows
        ]
    except SourceUnavailable as exc:
        out["dgidb_error"] = str(exc)
    if not m and not out["dgidb"]:
        out["found"] = False
    return _fit(out, "dgidb")


@tool
def get_gene_info(symbol: Annotated[str, Field(description="HGNC gene symbol, e.g. CYP3A4, SLCO1B1.")]) -> dict:
    """Drugs acting on a gene (DGIdb) and the Reactome pathways it belongs to."""
    out: dict[str, Any] = {"gene": symbol.upper()}
    try:
        rows = dgidb.gene_drugs(symbol, 12)
        out["drugs"] = [{"drug": r.drug, "types": r.types, "curated": r.curated} for r in rows]
    except SourceUnavailable as exc:
        out["drugs_error"] = str(exc)
    try:
        acc, pw = pathways.pathways(symbol)
        out["uniprot"] = acc
        if pw:
            rid = STORE.add(
                "Reactome",
                f"Pathways for {symbol}",
                f"https://reactome.org/content/query?q={acc}",
                json.dumps([p.__dict__ for p in pw]),
            )
            out["pathways"] = {"ref": rid, "rows": [p.__dict__ for p in pw]}
    except SourceUnavailable as exc:
        out["pathways_error"] = str(exc)
    return _fit(out, "drugs")


@tool
def search_literature(
    query: Annotated[
        str, Field(description="Search terms using generic names, e.g. 'letermovir cyclosporine interaction'.")
    ],
) -> dict:
    """Search Europe PMC. Use US generic spellings; 'ciclosporin' returns nothing."""
    try:
        arts = europepmc.search(query, 6)
    except SourceUnavailable as exc:
        return _fail("Europe PMC", exc)
    if not arts:
        return {"query": query, "found": False, "note": "No articles. Do not cite from memory."}
    rows = []
    for a in arts:
        rid = STORE.add("Europe PMC", a.title, a.url, f"{a.title}. {a.abstract or ''}")
        rows.append(
            {
                "ref": rid,
                "pmid": a.pmid,
                "year": a.year,
                "journal": a.journal,
                "title": a.title,
                "abstract": _clip(a.abstract or "", 400),
            }
        )
    return _fit({"query": query, "found": True, "articles": rows}, "articles")


@tool
def search_regulators(
    terms: Annotated[list[str], Field(description="Search terms as a list of generic names and topic words.")],
    drugs: Annotated[list[str], Field(description="Generic names already resolved. Required.")],
) -> dict:
    """Search regulator websites (EMA, MHRA, FDA, ANSM, BfArM, WHO) for documents.

    Weaker than a label section. Use for what the label tools cannot reach: safety
    communications, referrals, nationally authorised products with no EMA SmPC. Check each hit's
    caution field; withdrawn and historical documents are flagged.
    """
    if not drugs:
        return {"error": "drugs is required; resolve names first."}
    try:
        hits = web.search(terms, drugs, limit=8)
    except web.UnsafeQuery as exc:
        return {"error": f"query rejected by scrubber: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return _fail("Tavily", exc)
    if not hits:
        return {"found": False, "note": "Nothing on allowlisted regulator domains."}
    rows = []
    for h in hits[:5]:
        rid = STORE.add("Regulator web", h.title, h.url, h.text, h.caution)
        row: dict[str, Any] = {"ref": rid, "domain": h.domain, "title": h.title[:120], "text": _clip(h.text, 1_200)}
        if h.caution:
            row["caution"] = h.caution
        rows.append(row)
    return _fit(
        {"found": True, "documents": rows, "evidence_tier": "web page text; cite by document name"}, "documents"
    )


def _gene_biology(gene: str) -> tuple[str, str | None, list[dict]]:
    """One gene's pathways with their parent processes. Safe to run in a thread."""
    try:
        acc, pws = pathways.pathways(gene, limit=4)
    except SourceUnavailable:
        return gene, None, []
    rows = []
    for pw in pws:
        with suppress(SourceUnavailable):
            pw.lineage = pathways.lineage(pw.id)
        rows.append({"pathway": pw.name, "process": pw.lineage})
    return gene, acc, rows


@tool
def get_pharmacology(generic_name: Annotated[str, Field(description="Generic name from resolve_drug.")]) -> dict:
    """Why a drug causes an adverse event: genetic variants, pathway biology, and causal chains.

    Three layers, each labelled with how strong it is:
    - pharmacogenomics: variant -> gene -> toxicity phenotype from PharmGKB, with evidence level
      1A (clinical guideline) down to 4 (single study). State the level with every claim.
    - pathway_biology: for each implicated gene, its Reactome pathways and the parent processes
      they belong to.
    - adverse_outcome_pathways: expert-curated causal chains from AOP-Wiki, molecular initiating
      event through key events to clinical outcome. The chain itself is curated; the genes
      listed on each step are text-mined and include false matches. A chain marked is_draft
      has key events but no links yet; do not present it as validated.

    Coverage varies. A drug with no rows here has no established mechanism in these databases;
    say that rather than reasoning one out.
    """
    out: dict[str, Any] = {"drug": generic_name}
    genes: set[str] = set()

    try:
        m = chembl.find_molecule(generic_name.split(" / ")[0])
    except SourceUnavailable as exc:
        return _fail("ChEMBL", exc)

    # 1. Pharmacogenomic toxicity rows.
    if m:
        try:
            pgx = opentargets.pharmacogenomics(m.chembl_id)
            if pgx:
                rid = STORE.add(
                    "PharmGKB via Open Targets",
                    f"Pharmacogenomic toxicity annotations for {generic_name}",
                    f"https://platform.opentargets.org/drug/{m.chembl_id}",
                    json.dumps([p.__dict__ for p in pgx]),
                )
                out["pharmacogenomics"] = {
                    "ref": rid,
                    "rows": [
                        {
                            "gene": p.gene,
                            "variant": p.variant,
                            "phenotype": p.phenotype,
                            "evidence_level": p.evidence_level,
                        }
                        for p in pgx
                    ],
                }
                genes.update(p.gene for p in pgx if p.gene)
        except SourceUnavailable as exc:
            out["pharmacogenomics_error"] = str(exc)
        with suppress(SourceUnavailable):
            genes.update(t.symbol for t in opentargets.targets(m.chembl_id) if t.symbol)

    # 2. Pathway biology for the genes that came up. Each gene needs one pathway call plus one
    # lineage call per pathway, about 1.5 s each; done serially that was 35 s of a 73 s tool
    # call, so the genes run in parallel.
    biology = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for gene, acc, rows in pool.map(_gene_biology, sorted(genes)[:4]):
            if rows:
                rid = STORE.add(
                    "Reactome", f"Pathways for {gene}", f"https://reactome.org/content/query?q={acc}", json.dumps(rows)
                )
                biology.append({"ref": rid, "gene": gene, "pathways": rows})
    if biology:
        out["pathway_biology"] = biology

    # 3. Adverse outcome pathways. The wiki uses British and stem spellings ("Cyclosporin"), so
    # a miss on the United States generic name is retried on the name minus its final letter.
    stem = generic_name.split(" / ")[0]
    try:
        aops = aopwiki.find_pathways(stem) or aopwiki.find_pathways(stem[:-1])
    except SourceUnavailable as exc:
        aops = []
        out["adverse_outcome_pathways_error"] = str(exc)
    chains = []
    for aop in aops[:3]:
        with suppress(SourceUnavailable):
            aop.links = aopwiki.chain(f"https://identifiers.org/aop/{aop.id}", genes)
        row: dict[str, Any] = {
            "title": aop.title,
            "initiating_event": aop.initiating_event,
            "adverse_outcome": aop.adverse_outcome,
            "is_draft": aop.is_draft,
        }
        if aop.links:
            row["chain"] = [{"from": ln.upstream, "to": ln.downstream, "genes": ln.genes} for ln in aop.links]
            row["gene_note"] = (
                "Genes on each step are text-mined from the pathway description and include false "
                "matches; treat them as leads to check, not as curated pathway members."
            )
        else:
            row["note"] = "Key events listed but not yet linked; under development, not a validated chain."
        rid = STORE.add("AOP-Wiki", aop.title, aop.url, json.dumps(row))
        chains.append({"ref": rid, **row})
    if chains:
        out["adverse_outcome_pathways"] = chains

    if not any(k in out for k in ("pharmacogenomics", "pathway_biology", "adverse_outcome_pathways")):
        out["found"] = False
        out["note"] = "No mechanistic data in PharmGKB, Reactome or AOP-Wiki for this drug."
    return _fit(out, "pathway_biology")


TOOLS = [
    resolve_drug,
    get_us_label,
    get_eu_label,
    get_reported_events,
    get_pair_reports,
    get_mechanism,
    get_pharmacology,
    get_gene_info,
    search_literature,
    search_regulators,
]
TOOL_MAP = {t.name: t for t in TOOLS}


def available_tools() -> list:
    """Tools the model is offered this turn. Web search is left out when there is no Tavily key."""
    from pv_agent.config import get_settings

    if get_settings().web_search_enabled():
        return TOOLS
    return [t for t in TOOLS if t.name != "search_regulators"]
