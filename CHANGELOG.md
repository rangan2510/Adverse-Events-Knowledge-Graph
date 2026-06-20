# Changelog

All notable changes to the Drug-AE Knowledge Graph are documented here. The
project follows a simple dated-section format; the current version is `0.1.0`.

## [Unreleased]

### Agent: more insights + model evaluation
- **Exposed four high-value "insight" tools** to the LangChain agent (previously
  implemented but unwired): `explain_paths` (ranked, evidence-weighted drug->AE
  mechanistic paths), `get_disease_genes` (reverse disease->gene reasoning),
  `get_gene_interactors` (STRING PPI for indirect mechanism), and
  `get_drug_label_sections` (openFDA boxed warnings / contraindications). The
  agent toolset went from 16 to 20 tools.
- **Rewrote the agent system prompt** with per-question-type tool selection and
  insight reporting rules (rank by evidence strength, always cite the retrieved
  scores/PRR/frequency, distinguish direct vs indirect mechanism).
- **Fixed a mechanistic-correctness bug in `find_drug_to_ae_paths`**: when an
  `ae_key` was supplied it returned `Drug -> Gene -> Disease` paths that never
  reached the adverse event, letting the LLM invent a disease-to-AE leap (e.g.
  atorvastatin -> CD40 -> "hyper-IgM syndrome" -> myopathy). Paths now only
  count when they genuinely connect to the AE (direct edge, or a gene-disease
  whose label matches the AE), and the AE node is appended to the chain. The
  atorvastatin->myopathy answer now surfaces the correct SLCO1B1/HMGCR links.
- **Added a model override** (`build_chat_model(model=...)`, `run_agent(model=...)`)
  and `scripts/compare_models.py` to A/B test open-weight Mistral variants.
  Outcome: `mistral-small-3.2-24b-instruct` is the conservative default; once the
  OpenRouter data policy permits its providers, `mistral-small-2603` ("Mistral
  Small 4") gives the richest grounded answers (verified from the container).
  `ministral-8b` does not emit OpenAI-format tool calls reliably.

### ETL downloads: aria2c + parallelism + structured logging
- **aria2c-accelerated downloads** with multi-connection splits, resume, and
  retries, via a single input-file batch (`src/kg_ae/etl/aria2.py`). Falls back
  to httpx when aria2c is absent.
- **Resilient completeness check**: a file counts as downloaded only if it
  exists AND has no `.aria2` control sidecar; partial files are discarded and
  re-fetched via single-connection httpx (mop-up). This fixed corrupt
  `.gz`/`.zip` archives ("corrupt deflate stream" / "Bad CRC-32") that broke
  parsing on slow/flaky servers.
- **Parallel downloads**: declarative-spec datasets are pooled into one aria2c
  batch; API/listing-based datasets run concurrently on a thread pool
  (`KG_AE_DOWNLOAD_CONCURRENCY`).
- **Declarative downloaders**: simple file-URL datasets (hgnc, drugcentral,
  sider, gtop, twosides, reactome, string) now declare `download_specs()` and
  the base class handles batching, caching, and metadata uniformly.
- **Replaced the Rich live dashboard with structlog**: each ETL step logs one
  compact line (`[ok] sider download done 1.4s`). Removed the interactive ETL
  menu; `kg-ae etl` is now flag-driven (`--dataset`, `--tier`, `--force`).
- **Fixed downloader signature bug**: `clingen`, `hpo`, `chembl`, and `faers`
  downloaders did not accept the `force` argument the runner passes, causing
  instant clean-run failures. All downloaders now accept `force`.
- **Docker**: both `Dockerfile` and `Dockerfile.stage` install `aria2`.

### Data sources
- **BindingDB**: fixed the downloader to use the direct, resumable TSV URL
  (the JSP redirect endpoint was flaky); added to the graph as quantitative
  drug-target binding edges.
- **Fixed gtop registry flag**: `gtop` has a normalizer but was missing
  `has_normalize=True`, so its silver was never regenerated on a clean rebuild
  (silently dropping ~2,700 edges). Now correctly normalized.
- **gtop parser** tolerates malformed SMILES (`ignore_errors=True`).

### Architecture cleanup (SQL -> JSON graph)
- **Removed the dead SQL-era load layer**: deleted 13 dataset `load.py` files,
  the `kg_ae.db` package, the `BaseLoader` ABC, and the unreachable `load` ETL
  phase / dashboard column.
- The runtime is now purely file-based: `download -> parse (bronze) ->
  normalize (silver) -> build-graph (JSON) -> GraphStore -> tools -> agent`.
  No database server anywhere.
- Refreshed stale docstrings that referenced "SQL Server 2025".

### Graph
- Built from 16 curated public sources; current graph: **3,416,487 edges**
  across Drug (4,503), Gene (80,260), Pathway (2,870), Disease (36,585),
  AdverseEvent (7,837), DrugCombination (53,721).
- Verified reproducible from a clean clone via `kg-ae stage all` (download ->
  normalize -> build -> canary verify), all green.
