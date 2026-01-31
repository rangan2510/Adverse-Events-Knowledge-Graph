Below is a concrete, low-level **local-first, pure-Python** plan for building your **drug → gene → disease → pathway → adverse event** evidence graph **without relying on open-internet literature at runtime** (no papers/preprints scraping). The LLM is just the orchestrator; the value is the dataset plumbing + graph tooling.

---

## Step 1 — Pick datasets + exact acquisition strategy (API-first, bulk-ready)

### 1) Drug identity + cross-refs (critical for entity resolution)

You need a “drug master record” layer that normalizes names → identifiers across sources.

**A. DrugCentral (primary drug hub)**

* Why: drug synonyms, structures, indications, MoA/targets, and other clinical annotations; supports local install via DB dump and has an OpenAPI. ([Drug Central][1])
* Acquire:

  * **API (subset testing):** via DrugCentral OpenAPI. ([Drug Central][2])
  * **Bulk (scale):** download PostgreSQL dump. ([Drug Central][1])

**B. PubChem PUG-REST (name → structure → identifiers)**

* Why: fast normalization from free-text drug names to CID / InChIKey / SMILES for cross-dataset joins. ([Chemistry LibreTexts][3])
* Acquire: API only (good for constrained tests).

**C. UniChem (structure-based cross-reference router)**

* Why: maps *Standard InChI* across EMBL-EBI chemistry resources (useful to connect DrugCentral/ChEMBL/PubChem). ([ChEMBL Documentation][4])
* Acquire: API + (optional) bulk dumps if you want full local mapping later.

**D. MyChem.info (optional accelerator)**

* Why: aggregated chemical annotations / cross-refs (handy for fast prototyping). ([GitHub][5])
* Acquire: API for subsets.

---

### 2) Drug → target / gene (mechanism layer)

This is where you’ll derive mechanistic paths that can “explain” AEs.

**A. ChEMBL (bioactivity + targets + mechanisms)**

* Why: open, broad coverage of compounds, targets, bioactivities; standard workhorse for drug-target edges. ([PMC][6])
* Acquire:

  * **Bulk:** release files via EMBL-EBI FTP are standard for full ingestion. ([PMC][7])
  * **API:** for subset expansion/testing (you’ll still want bulk later).

**B. IUPHAR/BPS Guide to PHARMACOLOGY (GtoPdb) (curated, “CIViC-like” but general)**

* Why: expert-curated ligand-target interactions with quantitative pharmacology; strong evidence tier for mechanisms. Has REST services + downloads; clear licensing. ([IUPHAR/BPS Guide to Pharmacology][8])
* Acquire:

  * **API (subset):** base URL documented. ([IUPHAR/BPS Guide to Pharmacology][8])
  * **Bulk:** downloadable TSV/CSV + full DB options. ([IUPHAR/BPS Guide to Pharmacology][9])

**C. Open Targets Platform (disease–target–drug evidence)**

* Why: curated/integrated evidence connecting targets ↔ diseases ↔ drugs; complements ChEMBL/GtoPdb with disease context. ([OpenTargets][10])
* Acquire:

  * **API (subset):** GraphQL for constrained queries (perfect for “given drug list, pull neighborhood”). ([EBI][11])
  * **Bulk (scale):** platform data downloads when you move beyond prototyping. ([OpenTargets][10])

---

### 3) Gene ↔ pathway / biology context (pathway layer)

**Reactome (pathways + reactions + participants)**

* Why: curated, peer-reviewed pathway KB; Content Service API gives direct access, and Reactome exposes graph DB artifacts too. ([Reactome][12])
* Acquire:

  * **API (subset):** Content Service. ([Reactome][13])
  * **Bulk:** later via downloads / graph database exports. ([PMC][14])

---

### 4) Adverse event evidence (safety layer)

This is your “observational + label” evidence layer (no literature scraping).

**A. openFDA Drug Adverse Event (FAERS)**

* Why: AE reports from FAERS; available via API and bulk zipped JSON; openFDA project is CC0. ([OpenFDA][15])
* Acquire:

  * **API (subset):** quick signal checks per drug/AEs. ([OpenFDA][15])
  * **Bulk (real work):** download all partitions and compute local disproportionality (PRR/ROR/IC). ([OpenFDA][16])

**B. openFDA Drug Labeling**

* Why: structured labeling (warnings/adverse reactions sections) — “stronger than FAERS” for listed AEs. openFDA supports labeling endpoints. ([OpenFDA][17])

**C. SIDER (label-derived drug–ADR pairs)**

* Why: easy bootstrap for drug–AE edges + frequencies; but dataset is old (SIDER 4.1 released 2015). ([Side Effects][18])
* Acquire: bulk download. ([Side Effects][18])

---

### 5) Clinical trial context (optional but high value, still “dataset not literature”)

**ClinicalTrials.gov API v2**

* Why: trial registry evidence; useful for “AE observed in trials” and condition context; official API spec available. ([ClinicalTrials.gov][19])
* Acquire: API for subset; bulk later if needed.

---

### Minimal “v1 dataset bundle” (enough to build the graph end-to-end)

1. DrugCentral + PubChem (+ UniChem) for drug identity
2. ChEMBL + GtoPdb for drug→target
3. Reactome for target→pathway
4. openFDA FAERS + openFDA labels + SIDER for drug→AE
5. Open Targets for disease context (especially given patient conditions)

---

## Step 2 — Implement local ingestion into SQL Server 2025 (raw → normalized → graph)

### 2.1 Repository layout (keep it boring and reproducible)

```
kg_ae/
  data/
    raw/            # downloaded archives, json zips, tsv.gz, dumps
    bronze/         # parsed-to-parquet/csv, still source-shaped
    silver/         # normalized tables (canonical IDs)
    gold/           # graph-ready edge tables + evidence tables
  src/kg_ae/
    datasets/       # one module per source (download, parse, normalize)
    resolve/        # drug/gene/disease/ae identity resolution
    etl/            # pipelines + checkpoints
    graph/          # SQL graph loaders + traversal queries
    evidence/       # scoring + provenance
    tools/          # LLM tool functions (thin wrappers over graph/queries)
```

### 2.2 Canonical IDs (non-negotiable)

Create your own internal keys so joins don’t depend on any one dataset:

* `drug_key` (internal UUID/int) + external IDs as attributes:

  * DrugCentral ID, ChEMBL ID, PubChem CID, InChIKey, ATC (if available), etc.
* `gene_key`: HGNC symbol + Ensembl + UniProt where possible
* `disease_key`: align to Open Targets disease IDs (often EFO-based), store synonyms
* `ae_key`: **do not depend on MedDRA** (license friction). Use openFDA reaction terms as strings + map to UMLS/SNOMED only if you have a permitted source.

### 2.3 SQL Server physical model (3 layers)

**A) Relational “source-of-truth” tables (silver)**

* `drug`, `gene`, `disease`, `pathway`, `adverse_event`
* crosswalk tables: `drug_xref`, `gene_xref`, …

**B) Evidence table (gold)**
Every claim becomes a row in `evidence`:

* `evidence_id`, `source` (drugcentral/chembl/gtopdb/openfda/sider/opentargets/reactome/ctgov)
* `source_record_id` (e.g., FAERS safetyreportid, label set_id, etc.)
* `evidence_type` (curated_interaction | label_listed_ae | faers_signal | trial_registry | curated_pathway …)
* `payload_json` (store the original record slice you need; keep it compact)
* `timestamp/version` (dataset versioning matters)

**C) Graph tables (gold)**
Use SQL Server graph tables for fast traversal:

* Nodes: `Drug`, `Gene`, `Disease`, `Pathway`, `AdverseEvent`, `Evidence`
* Edges (examples):

  * `Drug_TARGET_Gene` (from ChEMBL/GtoPdb/DrugCentral)
  * `Gene_IN_Pathway` (Reactome)
  * `Drug_ASSOC_Disease` (DrugCentral/OpenTargets)
  * `Drug_ASSOC_AdverseEvent` (SIDER/openFDA labels + FAERS signal)
  * `CLAIM_SUPPORTED_BY` (edge from association edge → Evidence node, or association row → evidence rows)

**Key trick:** treat “associations” as first-class objects (either nodes or rows), so you can attach multiple evidence items cleanly.

### 2.4 ETL mechanics (Python-only)

* Downloaders:

  * `httpx` + `tenacity` retries + checksum/version stamping
* Parsers:

  * JSON (openFDA), TSV/CSV (SIDER/GtoPdb), dumps (DrugCentral PG dump)
* Load strategy into SQL Server:

  * For big files: write to CSV and use `BULK INSERT` / bcp (fastest)
  * For small subsets: `pyodbc` batch inserts
* Store dataset “build manifest” table (`dataset_builds`) with:

  * source name, version/date, file hashes, row counts, build time

---

## Step 3 — Build the graph-construction + traversal tooling (what the LLM will call)

### 3.1 Core tool functions (these are your “product”)

All tools are deterministic and run locally on SQL Server.

1. `resolve_drugs(drug_names) -> [drug_key...]`

* Use DrugCentral first, fall back to PubChem; use UniChem for crosswalk. ([Drug Central][2])

2. `get_ae_signals(drug_key, constraints) -> edges`

* From openFDA FAERS: counts, co-reported reactions, demographics if needed. ([OpenFDA][15])
* Compute local disproportionality from bulk (recommended for anything serious).

3. `get_label_aes(drug_key) -> edges`

* From openFDA labeling endpoint (listed AEs / warnings). ([OpenFDA][17])

4. `expand_mechanism(drug_key) -> drug→gene edges`

* Pull targets from GtoPdb + ChEMBL + DrugCentral; store with provenance. ([IUPHAR/BPS Guide to Pharmacology][8])

5. `expand_pathways(gene_keys) -> gene→pathway edges`

* Reactome Content Service → load pathway memberships and hierarchical expansion. ([Reactome][13])

6. `condition_context(condition_terms) -> disease_keys`

* Prefer Open Targets disease objects (so downstream joins work). ([EBI][11])

7. `build_subgraph(drug_keys, disease_keys, ae_focus=None, hops=3) -> graph`

* Return nodes/edges + evidence pointers (not prose)

8. `score_edges(graph) -> weighted_graph`

* Evidence-weighting policy (example):

  * curated pharmacology (GtoPdb) > curated DB (DrugCentral) > labeling-listed AE > FAERS signal > SIDER (old)
  * Penalize weak/confounded FAERS signals unless strong ROR/PRR and consistent across time slices

9. `explain_paths(drug_key, ae_key, condition=None) -> top_k_paths`

* Output: ranked mechanistic chains like

  * Drug → Target gene → Pathway → Biological process → AE term
  * Drug → Disease context → Pathway overlap → AE enrichment

### 3.2 LLM integration (keep it minimal)

* LLM (llama.cpp) only:

  1. picks which tools to call,
  2. requests subgraphs,
  3. asks for path explanations,
  4. summarizes *what the graph already contains*.

No literature. No browsing. No “LLM says so” edges.

### 3.3 Output contract (what your system returns)

For each query (drug list + patient conditions), output:

* `graph_json`: nodes + edges, each edge has `weight`, `evidence_ids[]`, `source_breakdown`
* `top_paths`: ranked mechanistic chains
* `evidence_bundle`: compact evidence payloads (FAERS counts, label sections, curated interaction references)

---

## Practical API-first subset workflow (how you test quickly)

Use APIs to build a tiny graph for 5–20 drugs, then lock the schema and scale with bulk downloads.

Example calls you’ll implement (illustrative only):

```python
# openFDA FAERS subset (drug name -> reports)
# https://open.fda.gov/apis/drug/event/  (docs)
# https://api.fda.gov/drug/event.json?... (endpoint)
```

(openFDA drug/event + bulk downloads are documented here. ([OpenFDA][15]))

```python
# Reactome pathway expansion via Content Service
# https://reactome.org/dev/content-service (docs)
```

(Reactome Content Service docs. ([Reactome][13]))

```python
# GtoPdb interactions
# base_url https://www.guidetopharmacology.org/services/ (docs)
```

(GtoPdb web services + downloads/licensing. ([IUPHAR/BPS Guide to Pharmacology][8]))

```python
# DrugCentral OpenAPI for drug lookup + xrefs
```

(DrugCentral OpenAPI + downloads. ([Drug Central][2]))

---

## What you’ll have after Steps 1–3 (v1 deliverable)

* A locally ingested SQL Server 2025 knowledge graph with:

  * drug↔gene targets (curated + bioactivity)
  * gene↔pathway memberships
  * drug↔AE edges (labels + FAERS signals + SIDER bootstrap)
  * disease/condition context (Open Targets)
  * every edge backed by auditable evidence rows
* A pure-Python tool layer that:

  * constructs subgraphs for a drug list,
  * traverses and ranks mechanistic paths to AEs,
  * returns graph JSON + evidence bundles
* LLM orchestration that **never invents edges** (it only queries/combines what’s in your DB)

---

If you want the next concrete artifact, I can write the **exact SQL schema (NODE/EDGE + evidence tables)** and the **Python ETL skeleton** (download/parse/load) for the **v1 bundle**: DrugCentral + GtoPdb + Reactome + openFDA + SIDER + Open Targets.

[1]: https://drugcentral.org/download?utm_source=chatgpt.com "DrugCentral Download"
[2]: https://drugcentral.org/OpenAPI?utm_source=chatgpt.com "Smart API"
[3]: https://chem.libretexts.org/Courses/Intercollegiate_Courses/Cheminformatics/01%3A_Introduction/1.07%3A_Accessing_PubChem_through_a_Web_Interface?utm_source=chatgpt.com "1.7: Accessing PubChem through a Web Interface"
[4]: https://chembl.gitbook.io/unichem?utm_source=chatgpt.com "Introduction | UniChem 2.0"
[5]: https://github.com/biothings/mygene.info?utm_source=chatgpt.com "MyGene.info: A BioThings API for gene annotations"
[6]: https://pmc.ncbi.nlm.nih.gov/articles/PMC6323927/?utm_source=chatgpt.com "ChEMBL: towards direct deposition of bioassay data - PMC"
[7]: https://pmc.ncbi.nlm.nih.gov/articles/PMC11480483/?utm_source=chatgpt.com "Expanding drug targets for 112 chronic diseases using a ..."
[8]: https://www.guidetopharmacology.org/webServices.jsp?utm_source=chatgpt.com "Web services | IUPHAR/BPS Guide to PHARMACOLOGY"
[9]: https://www.guidetopharmacology.org/download.jsp?utm_source=chatgpt.com "Download"
[10]: https://api.platform.opentargets.org/api/v4/graphql/schema?utm_source=chatgpt.com "GraphQL API schema"
[11]: https://www.ebi.ac.uk/training/online/courses/embl-ebi-programmatically/open-targets-programmatically/?utm_source=chatgpt.com "Open Targets, programmatically"
[12]: https://reactome.org/?utm_source=chatgpt.com "Reactome Pathway Database: Home"
[13]: https://reactome.org/dev/content-service?utm_source=chatgpt.com "Content Service - Reactome Pathway Database"
[14]: https://pmc.ncbi.nlm.nih.gov/articles/PMC5753187/?utm_source=chatgpt.com "The Reactome Pathway Knowledgebase - PMC"
[15]: https://open.fda.gov/apis/drug/event/?utm_source=chatgpt.com "Drug Adverse Event Overview"
[16]: https://open.fda.gov/data/downloads/?utm_source=chatgpt.com "Downloads"
[17]: https://open.fda.gov/apis/drug/?utm_source=chatgpt.com "Drug API Endpoints"
[18]: https://sideeffects.embl.de/download/?utm_source=chatgpt.com "Downloading data - SIDER Side Effect"
[19]: https://clinicaltrials.gov/data-api/api?utm_source=chatgpt.com "ClinicalTrials.gov API"
