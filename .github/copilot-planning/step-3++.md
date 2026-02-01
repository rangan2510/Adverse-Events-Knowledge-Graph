# KG-AE Data + Tools Enhancement Plan (Local-first, No Manual Downloads)

## Scope and constraints

* **Goal:** USE THIS AS AN INSPIRATION. Enhance your existing SQL Server 2025 graph KG (nodes/edges/claim/evidence) with additional **script-downloadable** datasets and expose robust **Python tools** for traversal + mechanistic ranking.
* **Constraint:** **No schema disturbance** to existing `kg.*` graph tables. Additions must be **data-only** (new rows in `kg.Dataset`, `kg.IngestRun`, `kg.Claim*`, `kg.Evidence`, `kg.SupportedBy`) and optionally **new ETL/staging tables in a separate schema** (e.g., `etl.*`) if needed for performance.
* **No manual clicking:** all acquisition via **curl/wget** or APIs callable from ETL pipelines.

---

## Current KG baseline (assumed)

Graph tables already exist under `kg`:

* Nodes: `Drug`, `Gene`, `Disease`, `Pathway`, `AdverseEvent`, `Claim`, `Evidence`
* Edges: `HasClaim`, `ClaimGene`, `ClaimDisease`, `ClaimPathway`, `ClaimAdverseEvent`, `SupportedBy`
* Metadata: `Dataset`, `IngestRun`

---

# Phase 0 — Repo + ETL foundation

## 0.1 Directory layout (deterministic)

```
kg_ae/
  data/
   ...
# retain the current project status, just add whatever is possible
```

## 0.2 Download wrapper (standardize)

* Use `curl.exe` explicitly on Windows (PowerShell `curl` alias is problematic).
* Standard flags (use everywhere):

  * `-fL` fail + follow redirects
  * `--retry 5 --retry-all-errors` robust transient handling
  * optional: `--continue-at -` for resumable downloads

---

# Phase 1 — Data enhancements (download + parse + load)

**Deliverable:** New datasets ingested with provenance into existing `kg.*` tables, no schema changes.

## 1A) openFDA — FAERS (drug/event) + Labels (drug/label) + NDC (drug/ndc)

### 1A.1 Download manifests (bulk, pipeline-driven)

```powershell
# openFDA download manifest (contains endpoint bulk file URLs)
curl.exe -fL --retry 5 --retry-all-errors `
  "https://api.fda.gov/download.json" `
  -o ".\data\raw\openfda\download.json"
```

### 1A.2 API subset calls (for early testing / constrained runs)

**FAERS: top AEs for a drug (counts by MedDRA PT)**

```powershell
curl.exe -fL --retry 5 --retry-all-errors `
  "https://api.fda.gov/drug/event.json?search=patient.drug.medicinalproduct:%22atorvastatin%22&count=patient.reaction.reactionmeddrapt.exact&limit=50" `
  -o ".\data\raw\openfda\faers_counts_atorvastatin_top50.json"
```

**FAERS with date window**

```powershell
curl.exe -fL --retry 5 --retry-all-errors `
  "https://api.fda.gov/drug/event.json?search=patient.drug.medicinalproduct:%22atorvastatin%22+AND+receivedate:[20200101+TO+20251231]&count=patient.reaction.reactionmeddrapt.exact&limit=50" `
  -o ".\data\raw\openfda\faers_counts_atorvastatin_2020_2025.json"
```

**Drug Labels: fetch one label by generic name**

```powershell
curl.exe -fL --retry 5 --retry-all-errors `
  "https://api.fda.gov/drug/label.json?search=openfda.generic_name.exact:%22ATORVASTATIN%22&limit=1" `
  -o ".\data\raw\openfda\label_atorvastatin.json"
```

**NDC: example lookup by generic name**

```powershell
curl.exe -fL --retry 5 --retry-all-errors `
  "https://api.fda.gov/drug/ndc.json?search=generic_name.exact:%22ATORVASTATIN%22&limit=5" `
  -o ".\data\raw\openfda\ndc_atorvastatin_sample.json"
```

### 1A.3 Mapping into your schema (no schema changes)

* **FAERS (counts or local computed signals)**

  * `Claim.claim_type = 'DRUG_AE_SIGNAL_FAERS'`
  * `ClaimAdverseEvent.signal_score` = computed ROR/PRR/IC (or keep null if only counts)
  * `Evidence.evidence_type = 'openfda_faers_query'` (API) or `'openfda_faers_bulk_partition'` (bulk)
  * `SupportedBy.support_strength` = normalized confidence (e.g., scaled log(ROR), or count-based proxy)
* **Labels**

  * `Claim.claim_type = 'DRUG_LABEL_SECTION'` and derived claims:

    * `DRUG_AE_LABEL_LISTED` (Drug→AE)
    * `DRUG_CONTRAINDICATION` / `DRUG_WARNING` (Drug→Disease) if you extract them
  * Evidence payload: `set_id`, `spl_id`, and extracted sections
* **NDC**

  * enrichment only: update `Drug.synonyms_json` / `Drug.xrefs_json` (no new edges required)
  * optionally store NDC records as `Evidence.evidence_type='openfda_ndc_record'` linked to a `Claim` type `DRUG_IDENTITY_ASSERTION`

---

## 1B) CTD — curated chemical–gene / chemical–disease / gene–disease

### 1B.1 Downloads (TSV.gz, scriptable)

```powershell
mkdir .\data\raw\ctd -Force | Out-Null

curl.exe -fL --retry 5 --retry-all-errors `
  "http://ctdbase.org/reports/CTD_chem_gene_ixns.tsv.gz" `
  -o ".\data\raw\ctd\CTD_chem_gene_ixns.tsv.gz"

curl.exe -fL --retry 5 --retry-all-errors `
  "http://ctdbase.org/reports/CTD_chemicals_diseases.tsv.gz" `
  -o ".\data\raw\ctd\CTD_chemicals_diseases.tsv.gz"

curl.exe -fL --retry 5 --retry-all-errors `
  "http://ctdbase.org/reports/CTD_genes_diseases.tsv.gz" `
  -o ".\data\raw\ctd\CTD_genes_diseases.tsv.gz"
```

### 1B.2 Mapping strategy (no new node types)

* CTD “chemical” must map to your `Drug` using **InChIKey / PubChem CID / synonyms**:

  * Store CTD chemical identifiers into `Drug.xrefs_json` when resolved.
* Insert claims:

  * `Claim.claim_type = 'DRUG_GENE_CTD'` + `ClaimGene(relation/effect)`
  * `Claim.claim_type = 'DRUG_DISEASE_CTD'` + `ClaimDisease(relation)`
  * `Claim.claim_type = 'GENE_DISEASE_CTD'` + `ClaimGene + ClaimDisease`
* Evidence:

  * `Evidence.evidence_type='ctd_record'` with curated interaction fields and reference IDs
  * link via `SupportedBy`

---

## 1C) Guide to PHARMACOLOGY (GtoPdb) — curated ligand–target interactions

### 1C.1 Downloads (DATA URLs)

```powershell
mkdir .\data\raw\gtop -Force | Out-Null

curl.exe -fL --retry 5 --retry-all-errors `
  "https://www.guidetopharmacology.org/DATA/interactions.tsv" `
  -o ".\data\raw\gtop\interactions.tsv"

curl.exe -fL --retry 5 --retry-all-errors `
  "https://www.guidetopharmacology.org/DATA/GtP_to_HGNC_mapping.csv" `
  -o ".\data\raw\gtop\GtP_to_HGNC_mapping.csv"

curl.exe -fL --retry 5 --retry-all-errors `
  "https://www.guidetopharmacology.org/DATA/GtP_to_UniProt_mapping.tsv" `
  -o ".\data\raw\gtop\GtP_to_UniProt_mapping.tsv"
```

### 1C.2 Mapping into schema

* `Claim.claim_type = 'DRUG_TARGET_GTOPDB'`
* `ClaimGene.relation='binds'` and `effect` when provided (agonist/antagonist/inhibitor/etc.)
* store affinity/units in `Claim.meta_json` or `Evidence.payload_json`
* link each claim to evidence rows via `SupportedBy`

---

## 1D) DISEASES (JensenLab) — scored gene–disease associations

### 1D.1 Downloads (TSV, bulk)

```powershell
mkdir .\data\raw\diseases_jensenlab -Force | Out-Null

curl.exe -fL --retry 5 --retry-all-errors `
  "https://download.jensenlab.org/human_disease_integrated_full.tsv" `
  -o ".\data\raw\diseases_jensenlab\human_disease_integrated_full.tsv"

curl.exe -fL --retry 5 --retry-all-errors `
  "https://download.jensenlab.org/human_disease_knowledge_full.tsv" `
  -o ".\data\raw\diseases_jensenlab\human_disease_knowledge_full.tsv"

curl.exe -fL --retry 5 --retry-all-errors `
  "https://download.jensenlab.org/human_disease_experiments_full.tsv" `
  -o ".\data\raw\diseases_jensenlab\human_disease_experiments_full.tsv"

curl.exe -fL --retry 5 --retry-all-errors `
  "https://download.jensenlab.org/human_disease_textmining_full.tsv" `
  -o ".\data\raw\diseases_jensenlab\human_disease_textmining_full.tsv"
```

### 1D.2 Mapping

* `Claim.claim_type = 'GENE_DISEASE_JENSENLAB'`
* `Claim.strength_score` = integrated/confidence score (normalize to 0..1)
* `Evidence.evidence_type = 'diseases_tsv_row'`

---

## 1E) ClinGen — Gene–Disease Validity (curated)

### 1E.1 Download

```powershell
mkdir .\data\raw\clingen -Force | Out-Null

curl.exe -fL --retry 5 --retry-all-errors `
  "https://search.clinicalgenome.org/kb/gene-validity/download" `
  -o ".\data\raw\clingen\gene_disease_validity.csv"
```

### 1E.2 Mapping

* `Claim.claim_type = 'GENE_DISEASE_VALIDITY_CLINGEN'`
* Encode validity class (Definitive/Strong/Moderate/Limited/Disputed/Refuted/No Known) in:

  * `Claim.strength_score` (mapped numeric)
  * `Evidence.payload_json` (original classification + mode of inheritance + curation identifiers)

---

## 1F) HGNC complete set (resolver quality upgrade)

```powershell
mkdir .\data\raw\hgnc -Force | Out-Null

curl.exe -fL --retry 5 --retry-all-errors `
  "https://storage.googleapis.com/public-download-files/hgnc/json/json/hgnc_complete_set.json" `
  -o ".\data\raw\hgnc\hgnc_complete_set.json"
```

Mapping:

* Update `Gene.symbol`, `Gene.synonyms_json`, `Gene.xrefs_json` (idempotent upsert)
* Optionally store raw HGNC entries as `Evidence` (`evidence_type='hgnc_record'`), linked to `Claim` type `GENE_IDENTITY_ASSERTION` if you want provenance.

---

## 1G) HPO (phenotype vocabulary; improves condition resolution)

```powershell
mkdir .\data\raw\hpo -Force | Out-Null

curl.exe -fL --retry 5 --retry-all-errors `
  "http://purl.obolibrary.org/obo/hp.obo" `
  -o ".\data\raw\hpo\hp.obo"
```

Mapping (no schema change):

* Use HPO as a **terminology overlay**:

  * feed into `resolve_diseases()` (conditions → Disease nodes) via synonyms/lexicon
  * optionally store HPO IDs into `Disease.xrefs_json` where mapped

---

## 1H) STRING API (subset gene–gene interactions; no bulk download required)

```powershell
mkdir .\data\raw\string -Force | Out-Null

# Map symbols -> STRING IDs (TSV)
curl.exe -fL --retry 5 --retry-all-errors `
  -d "identifiers=TP53%0DBRCA1&species=9606" `
  "https://string-db.org/api/tsv/get_string_ids" `
  -o ".\data\raw\string\string_ids.tsv"

# Network edges (TSV)
curl.exe -fL --retry 5 --retry-all-errors `
  -d "identifiers=TP53%0DBRCA1&species=9606&required_score=700" `
  "https://string-db.org/api/tsv/network" `
  -o ".\data\raw\string\network.tsv"
```

Mapping (no schema change):

* Represent one gene–gene interaction as:

  * `Claim.claim_type = 'GENE_GENE_STRING'`
  * **two rows** in `ClaimGene` for the same claim (one per gene); store combined score in `Claim.strength_score`
  * `Evidence.evidence_type='string_edge'`

---

## 1I) WikiPathways GPML (optional pathway expansion)

```powershell
mkdir .\data\raw\wikipathways -Force | Out-Null

# Fetch directory listing; Python ETL parses latest Homo_sapiens GPML zip
curl.exe -fL --retry 5 --retry-all-errors `
  "https://data.wikipathways.org/current/gpml/" `
  -o ".\data\raw\wikipathways\index.html"
```

ETL then:

1. parse `index.html`
2. pick newest `*-gpml-Homo_sapiens.zip`
3. `curl.exe` download that zip
4. parse GPML → create `GENE_PATHWAY_WP` claims via `ClaimPathway`

---

## 1J) Optional: UniProt REST (subset enrichment only)

```powershell
mkdir .\data\raw\uniprot -Force | Out-Null

curl.exe -fL --retry 5 --retry-all-errors `
  "https://rest.uniprot.org/uniprotkb/search?query=gene_exact:CYP3A4+AND+organism_id:9606&format=json&size=1" `
  -o ".\data\raw\uniprot\CYP3A4.json"
```

Mapping:

* Do **not** create new nodes; enrich `Gene.meta_json` / `xrefs_json`, store raw payload as `Evidence`.

---

# Phase 2 — ETL implementation tasks (dataset by dataset)

## 2.1 Registry + run tracking

* [ ] Insert one row into `kg.Dataset` per source:

  * `dataset_key`, `dataset_version`, `source_url`, `license_name`, `sha256` (if you compute)
* [ ] Each ETL run creates `kg.IngestRun` row:

  * status = running/success/failed, row counts, notes_json

## 2.2 Parsing & normalization rules (core)

* [ ] **Drug resolver enrichment**

  * openFDA NDC + labels → synonyms/xrefs
  * CTD chemical mapping → xrefs (PubChem CID, InChIKey)
* [ ] **Gene normalization**

  * HGNC complete set → canonical symbols + aliases + xrefs
* [ ] **Disease normalization**

  * maintain MONDO/DOID/EFO in `Disease` and store external IDs in `xrefs_json`
* [ ] **AE normalization**

  * Maintain AE label strings (FAERS PT / label terms); dedupe using:

    * casefold + trim + punctuation normalization
    * optional embedding or synonym overlay later

## 2.3 Claim/evidence emission (standard pattern)

For each source row:

* [ ] Upsert needed nodes (`Drug/Gene/Disease/Pathway/AdverseEvent`)
* [ ] Insert `Claim`:

  * `claim_type` is source-specific
  * store raw row summary in `statement_json`
  * store computed strength in `strength_score`
* [ ] Insert relationship edge(s) from Claim to entity nodes (`ClaimGene`, `ClaimDisease`, etc.)
* [ ] Insert `Evidence` row with `payload_json`
* [ ] Insert `SupportedBy` edge from Claim → Evidence with `support_strength`

---

# Phase 3 — Tools (Python) to build after data is in

## 3.1 Keep your existing tool list; add only what’s missing

### Existing (keep)

* `resolve_drugs(names)`
* `resolve_genes(symbols)`
* `resolve_diseases(terms)`
* `get_drug_targets(drug_key)`
* `get_gene_pathways(gene_key)`
* `get_gene_diseases(gene_key)`
* `expand_mechanism(drug_key)`
* `get_drug_adverse_events(drug_key)`
* `get_drug_profile(drug_key)`
* `build_subgraph(drug_keys)`
* `explain_paths(drug_key)`

### Additions (needed to exploit the new evidence cleanly)

* [ ] `resolve_adverse_events(terms)`
  (required once FAERS/labels are in)
* [ ] `get_drug_label_sections(drug_key, sections=['adverse_reactions','warnings',...])`
* [ ] `get_drug_faers_signals(drug_key, top_k=200, date_range=None)`
* [ ] `get_disease_genes(disease_key, sources=['opentargets','ctd','diseases','clingen'])`
* [ ] `get_gene_interactors(gene_key, required_score=700, limit=200)` (STRING-backed)
* [ ] `get_claim_evidence(claim_key)`
  returns all linked evidence payload pointers (auditability backbone)
* [ ] `score_paths(paths, policy)`
  deterministic ranking (source weights + strength_score + multi-source support)

## 3.2 Tighten signatures to prevent graph blow-up

* [ ] `build_subgraph(drug_keys, disease_keys=None, ae_keys=None, hops=3, max_nodes=2000, max_edges=20000, edge_filters={...})`
* [ ] `explain_paths(drug_key, disease_key=None, ae_key=None, k=20, constraints={min_support:..., allowed_sources:...})`

---

# Phase 4 — Acceptance checks (make it measurable)

## 4.1 ETL correctness

* [ ] Every inserted `Claim*` edge has ≥1 `SupportedBy` link
* [ ] Every dataset ingestion run recorded in `kg.IngestRun` with row counts
* [ ] Dedup rate: no uncontrolled duplication of Drug/Gene/Disease/AE nodes

## 4.2 Query sanity

* [ ] `get_drug_adverse_events()` returns separate buckets by evidence_type:

  * label-listed vs FAERS signal vs existing SIDER
* [ ] `explain_paths()` returns paths where each hop is supported by evidence ids (no orphan reasoning)

---

# Phase 5 — Operational runbook (how you run it)

## 5.1 One-command dataset refresh (example)

* `etl_openfda_refresh`:

  * download manifest → download deltas → parse → load → update Dataset version
* `etl_ctd_refresh`, `etl_gtop_refresh`, `etl_diseases_refresh`, `etl_clingen_refresh`, `etl_hgnc_refresh`, `etl_hpo_refresh`

## 5.2 Reproducibility

* Store every raw file SHA256 in `kg.Dataset.sha256` or `IngestRun.notes_json`
* Keep a `build_manifest.json` in repo tagged with dataset versions + URLs used