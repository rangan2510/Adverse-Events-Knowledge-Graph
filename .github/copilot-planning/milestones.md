## 0) What you’re building (tight scope)

**Goal:** given **(a) drug list** + **(b) patient conditions**, return a **local, provenance-backed network** of **drug → (gene/protein) → pathway → disease/condition → adverse event** associations, with **ranked evidence** and **traceable sources**.

**Hard constraints you gave:**

* **Local-first, pure Python**, no dependency on live web retrieval of papers/preprints at runtime.
* Use **open(-ish) datasets** that can be **downloaded and ingested locally** into **SQL Server 2025** with **JSON + graph tables + vectors**. (SQL Server supports **graph node/edge tables** ([Microsoft Learn][1]) and the **VECTOR** data type in **SQL Server 2025 preview** ([Microsoft Learn][2]).)

---

## 1) Dataset stack (open + locally ingestible)

You’ll need coverage across **(1) drug ↔ target**, **(2) gene ↔ disease**, **(3) pathways**, **(4) adverse events**, plus **(5) ontologies/IDs**.

### Core sources (recommended MVP set)

1. **Drug ↔ target / mechanism**

* **ChEMBL** (bioactivity, targets), **CC BY-SA** ([chembl.gitbook.io][3])
* **DrugCentral** (approved drugs, indications, targets; downloadable dumps) ([PMC][4])

2. **Gene ↔ disease associations**

* **Open Targets Platform** datasets are **CC0** (public domain) and downloadable as release Parquet ([platform-docs.opentargets.org][5])
* **CTD** (chemical–gene–disease networks curated from literature; downloadable) ([PMC][6])

3. **Pathways**

* **Reactome** (pathways; **CC BY 4.0**) ([Reactome][7])
* Optional: **WikiPathways** (open science; widely used, CC0 highlighted on site) ([wikipathways.org][8])

4. **Adverse events (signals / known label effects)**

* **SIDER** (drug–ADR from labels; SciCrunch notes **CC BY-NC-SA** and “commercial use requires permission”) ([scicrunch.org][9])
* Optional add-on: **FAERS** quarterly files (public FDA post-marketing reports; bulk downloads) ([U.S. Food and Drug Administration][10])

5. **Identifiers / ontologies**

* **HGNC** gene IDs/synonyms (**CC0**) ([genenames.org][11])
* **Disease Ontology (DOID)** (**CC0**) ([disease-ontology.org][12])
* **MONDO** (**CC BY 4.0**) ([mondo.monarchinitiative.org][13])
* **UniProt** protein mapping (**CC BY 4.0**) ([UniProt][14])
* **OAE (Ontology of Adverse Events)** (open ontology; CC BY 3.0 per OBO Foundry) ([obofoundry.org][15])

> Note on DGIdb: app/code is open, and dumps exist, but **some imported sources have restrictions**—treat DGIdb as optional unless you explicitly curate permissible sub-sources. ([dgidb.org][16])

---

## 2) Canonical ID strategy (this makes or breaks the project)

Pick **one canonical ID** per entity type and keep everything else as cross-refs.

* **Drug**: prefer **DrugCentral ID** + **ChEMBL ID** + InChIKey (when available).
* **Gene**: **HGNC ID** (canonical) + Ensembl + UniProt cross-refs.
* **Disease/Condition**: **MONDO ID** as canonical, with DOID mappings.
* **Pathway**: **Reactome stable ID**.
* **Adverse event**: canonicalize to **OAE** where possible; store SIDER terms as “source AE labels” and map → OAE via synonym/embedding matching.

You’ll implement a **resolver service**:

* `resolve_drug(name) -> {drug_id, synonyms, xrefs, confidence}`
* `resolve_condition(text) -> {mondo/doid, confidence}`
* `resolve_ae(term) -> {oae_id or raw_term, confidence}`

Store **resolver decisions + confidence + evidence** (so you can debug every wrong match).

---

## 3) SQL Server 2025 data model (graph + JSON + vectors)

SQL Server graph is **node tables + edge tables** ([Microsoft Learn][1]). VECTOR stores embeddings for similarity search ([Microsoft Learn][2]).

### Node tables (examples)

* `DrugNode(drug_id, preferred_name, xrefs_json, embedding VECTOR, meta_json)`
* `GeneNode(hgnc_id, symbol, xrefs_json, embedding VECTOR, meta_json)`
* `DiseaseNode(mondo_id, label, synonyms_json, embedding VECTOR, meta_json)`
* `PathwayNode(reactome_id, label, embedding VECTOR, meta_json)`
* `AENode(ae_id, label, ontology, embedding VECTOR, meta_json)`
* `EvidenceNode(evidence_id, source, record_key, payload_json, embedding VECTOR, meta_json)`

### Edge tables (examples)

* `DrugTargetsGeneEdge($from_id, $to_id, source, action, strength, evidence_ids_json, meta_json)`
* `GeneInPathwayEdge(...)`
* `GeneAssociatedDiseaseEdge(..., score, datasource, evidence_ids_json)`
* `DrugAssociatedAEEdge(..., freq_or_signal, datasource, evidence_ids_json)`
* `DiseasePredisposesAEEdge(...)` (optional—often weak; keep it explicit and low-confidence unless sourced)

**Rule:** every edge carries:

* `source` (dataset + version)
* `evidence_ids` (one-to-many)
* `score` (normalized 0–1)
* `meta_json` (raw fields preserved)

---

## 4) Python architecture (pure Python, local tooling)

### Repo layout (clean + modular)

* `ingest/`

  * `download/` (fetch + checksum + version pinning)
  * `parsers/` (each datasource → normalized parquet)
  * `loaders/` (bulk load into SQL Server)
* `normalize/`

  * entity resolvers, synonym dictionaries, ontology mappings
* `graph/`

  * schema creation, node/edge upserts, provenance, embedding writers
* `reasoning/`

  * path search + scoring, subgraph extraction, explanation assembly (non-LLM)
* `llm/`

  * llama.cpp client, tool schemas, strict dispatcher
* `cli/`

  * `build-kg`, `query`, `explain`, `export-subgraph`
* `eval/`

  * gold sets + regression tests + metrics

### DB access

Use `sqlalchemy` or direct `pyodbc` with:

* bulk inserts (`executemany`, fast_executemany)
* staging tables → merge into graph tables (keeps it fast)

---

## 5) Reasoning engine (LLM is NOT the reasoner)

You want **deterministic graph reasoning** + **LLM narration/orchestration**.

### Deterministic core: “evidence paths”

Given `(drugs, conditions)`:

1. **Resolve inputs** (IDs + confidence)
2. For each drug:

   * fetch **known AEs** (SIDER / FAERS if used)
   * fetch **targets** (DrugCentral/ChEMBL)
3. For each condition (mapped to MONDO):

   * fetch **condition-associated genes** (Open Targets / CTD)
4. Compute **mechanistic overlap**:

   * intersection / proximity between **drug target genes** and **condition genes**
   * expand to pathways (Reactome/WikiPathways)
5. Generate candidate explanations as **paths**:

   * `Drug → Gene → Pathway → (Condition disease context) → AE`
   * `Drug → AE` (direct, label-based)
6. Rank paths by:

   * dataset reliability (curated > mined)
   * edge scores (Open Targets provides strong scoring; CTD curated relations)
   * resolver confidence
   * path length penalty
7. Output:

   * a **subgraph** (nodes + edges + evidence)
   * a **ranked list of paths** with **evidence pointers**

### Evidence scoring (practical, works locally)

Define a score per edge:

* `score = w_source * w_field_quality * w_recency * w_frequency_or_strength * resolver_conf`
  Keep weights as config; log every component.

---

## 6) LLM orchestration (llama.cpp + strict tool calling)

Use llama.cpp as the **controller**:

* It proposes: *which AEs to focus on*, *which expansions to run*, *how to summarize*.
* It **never invents edges**; it can only speak from tool outputs.

llama.cpp provides an HTTP server and OpenAI-compatible endpoints in many deployments ([GitHub][17]), and embeddings are supported in common wrappers (or via compatible endpoints) ([Llama CPP Python][18]).

### Minimal tool surface (keep it small)

* `resolve_entities(drugs, conditions)`
* `get_drug_profile(drug_id)` (targets, indications, known AEs)
* `expand_gene_context(gene_ids)` (pathways, diseases)
* `find_paths(start_nodes, end_nodes, constraints)`
* `rank_paths(paths, patient_context)`
* `export_subgraph(nodes, edges, format="json|graphml")`

### Prevent “LLM answers before tools finish”

This is an orchestrator bug class, not a “framework trait”.
Implement a **hard gate**:

* your dispatcher executes tools synchronously
* the model only gets the next prompt after tool results are appended
* optionally disable streaming for “final answer” until tool phase completes

---

## 7) Outputs (what “network” means in practice)

Deliver **three artifacts** per query:

1. **Graph subnetwork JSON** (nodes/edges + evidence IDs + scores)
2. **Ranked mechanistic paths** (top-K) with provenance
3. **Narrative summary** (LLM) that *only references (1) and (2)*

Optionally export:

* GraphML for Cytoscape
* Neo4j-style CSVs (even if you store in SQL Server)

---

## 8) Evaluation plan (don’t skip this)

You’re doing an exploratory study, but you still need regression tests.

1. **Entity resolution accuracy**

* curated set: 200 drug names + 200 conditions + 200 AEs → expected IDs

2. **Graph sanity checks**

* degree distributions, orphan nodes, duplicated IDs, source coverage

3. **Query-level benchmarks**

* choose 30–50 drug+condition scenarios with known label AEs (from SIDER) ([PMC][19])
* measure:

  * recall@K for known AEs
  * path plausibility: % paths with ≥2 independent sources (e.g., DrugCentral target + Reactome pathway + Open Targets disease gene)

4. **Ablation**

* run with/without Open Targets, with/without CTD, etc., to quantify contribution

---

## 9) Build plan (concrete milestones)

### Milestone A — “KG skeleton + 1 datasource per layer”

* ChEMBL targets ([chembl.gitbook.io][3])
* Reactome pathways ([Reactome][7])
* Open Targets gene–disease ([platform-docs.opentargets.org][5])
* SIDER drug–AE ([scicrunch.org][9])
* SQL Server graph schema + vector columns ([Microsoft Learn][1])

### Milestone B — “Query engine + deterministic reasoning”

* subgraph extraction + path ranking
* JSON export + Cytoscape export

### Milestone C — “LLM orchestration wrapper”

* tool schemas + dispatcher + guarded finalization
* “explain this adverse event” interface

### Milestone D — “Hardening”

* caching, version pinning, reproducible builds
* evaluation suite + CI

---

## 10) The sharp edges you should plan for

* **Licensing:** SIDER is non-commercial per SciCrunch; DGIdb data sources can be restrictive. Decide early if this is strictly academic/non-commercial. ([scicrunch.org][9])
* **Terminology mismatch:** AE terms across SIDER/FAERS won’t cleanly map to an open ontology—expect a resolver/mapping layer (use OAE as the “open spine”). ([obofoundry.org][15])
* **ID mapping churn:** Open Targets releases are versioned; pin a specific release and store dataset version tags. ([platform-docs.opentargets.org][20])

---

If you want the “next step” to be maximally executable: I can draft (1) the **exact SQL graph DDL**, (2) the **Python package skeleton**, and (3) the **tool schemas + dispatcher contract** in a way that matches SQL Server graph/vectors and your llama.cpp tool-calling flow.

[1]: https://learn.microsoft.com/en-us/sql/relational-databases/graphs/sql-graph-architecture?view=sql-server-ver17&utm_source=chatgpt.com "SQL Graph Architecture - SQL Server"
[2]: https://learn.microsoft.com/en-us/sql/t-sql/data-types/vector-data-type?view=sql-server-ver17&utm_source=chatgpt.com "Vector Data Type - SQL Server"
[3]: https://chembl.gitbook.io/chembl-interface-documentation/frequently-asked-questions/general-questions?utm_source=chatgpt.com "General Questions - ChEMBL Interface Documentation - GitBook"
[4]: https://pmc.ncbi.nlm.nih.gov/articles/PMC5210665/?utm_source=chatgpt.com "DrugCentral: online drug compendium - PMC - PubMed Central"
[5]: https://platform-docs.opentargets.org/licence?utm_source=chatgpt.com "Licence | Open Targets Platform Documentation"
[6]: https://pmc.ncbi.nlm.nih.gov/articles/PMC2686584/?utm_source=chatgpt.com "Comparative Toxicogenomics Database - PubMed Central - NIH"
[7]: https://reactome.org/license?utm_source=chatgpt.com "License Agreement"
[8]: https://www.wikipathways.org/?utm_source=chatgpt.com "WikiPathways: Home"
[9]: https://scicrunch.org/resolver/SCR_004321?utm_source=chatgpt.com "SciCrunch | Research Resource Resolver"
[10]: https://www.fda.gov/drugs/fdas-adverse-event-reporting-system-faers/fda-adverse-event-reporting-system-faers-latest-quarterly-data-files?utm_source=chatgpt.com "FAERS: Latest Quarterly Data Files"
[11]: https://www.genenames.org/about/license/?utm_source=chatgpt.com "HGNC License Agreement"
[12]: https://disease-ontology.org/resources/citing-do?utm_source=chatgpt.com "Disease Ontology - Citing DO"
[13]: https://mondo.monarchinitiative.org/pages/download/?utm_source=chatgpt.com "Download - - Mondo Disease Ontology - Monarch Initiative"
[14]: https://www.uniprot.org/help/license?utm_source=chatgpt.com "License & disclaimer | UniProt help"
[15]: https://obofoundry.org/ontology/oae.html?utm_source=chatgpt.com "Ontology of Adverse Events (OAE)"
[16]: https://dgidb.org/downloads?utm_source=chatgpt.com "Downloads"
[17]: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md?utm_source=chatgpt.com "llama.cpp/tools/server/README.md at master · ggml-org ..."
[18]: https://llama-cpp-python.readthedocs.io/en/latest/api-reference/?utm_source=chatgpt.com "API Reference"
[19]: https://pmc.ncbi.nlm.nih.gov/articles/PMC4702794/?utm_source=chatgpt.com "The SIDER database of drugs and side effects - PMC"
[20]: https://platform-docs.opentargets.org/data-access/datasets?utm_source=chatgpt.com "Download datasets | Open Targets Platform Documentation"
