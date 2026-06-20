# Drug-AE Knowledge Graph — Agent Instructions

Pharmacovigilance KG that traces `Drug -> Gene -> Pathway -> Disease -> Adverse Event` using deterministic graph tools. The LLM is the **controller**; it never invents edges. Every association comes from a curated source with full provenance.

For project background, architecture diagrams, and graph stats, read [README.md](../README.md) first.

## What this codebase does

The goal is mechanistic, hallucination-resistant answers to pharmacovigilance questions (e.g. "why might drug X cause adverse event Y?", "what AEs do these drugs share?"). It works in two halves:

1. **ETL builds the graph** (offline, may use the internet on a staging machine). Curated biomedical sources (DrugCentral, ChEMBL, Reactome, Open Targets, SIDER, FAERS, HGNC, etc.) are downloaded, parsed to Parquet (bronze), and normalized to canonical IDs (silver). Then `kg-ae build-graph` reads the silver Parquet and emits a **file-based JSON graph** under `data/graph/` (`nodes.json`, `edges.json`, `meta.json`). Associations are flattened entity-to-entity edges that still carry their claim payload (`dataset`, `source_record_id`, normalized `strength_score`, raw `meta`, and an `evidence` list), so every edge keeps full provenance.
2. **The agent answers questions** (online or airgapped). A LangChain/LangGraph ReAct agent reasons about what it needs, calls a fixed set of deterministic graph tools (`src/kg_ae/tools/`), the tools query an in-memory `GraphStore` loaded from the JSON files, and the LLM narrates only what the tools returned. Because the LLM reaches the graph *only* through these tools, it cannot fabricate drug targets, pathways, or citations.

Think of the LLM as a router over a trusted local graph, not a knowledge source. There is **no database server**: the runtime is pure files plus one OpenAI-compatible LLM endpoint.

## Deployment context (read this)

This is built for an EU hospital and is designed to run **airgapped**. The graph contains only public reference data (no patient data); the only patient-adjacent input is the query text. Two capabilities touch the network and are gated by one flag:

- **LLM**: a single OpenAI-compatible endpoint. Dev uses OpenRouter (a stand-in for the local model); deployment uses a local server (Ollama / LM Studio / vLLM) on localhost. Switch by changing `KG_AE_LLM_BASE_URL` + `KG_AE_LLM_MODEL` only.
- **Web search (Tavily)**: an *optional, scoped* tool for entity resolution/verification only. It is never load-bearing and never a citation source.

When `KG_AE_AIRGAPPED=true`, `build_chat_model()` refuses any non-localhost LLM URL and the Tavily tool is not registered. See [docs/compliance.md](../docs/compliance.md). Only open-source models are allowed (Mistral Small recommended for France; Gemma also fine).

## Hard rules (read before writing code)

- **Local-first, pure Python.** No live web retrieval at runtime except the optional, airgap-gated Tavily tool. ETL downloads are the only other network use.
- **Never have the LLM reason over data it didn't get from a tool.** Tools return structured dataclasses, not prose. The agent only summarizes tool outputs.
- **Every edge must carry provenance**: `dataset`, `source_record_id`, normalized `strength_score`, and `meta`/`evidence` for raw fields. The graph builder (`src/kg_ae/graph/build.py`) attaches these to every edge it emits.
- **Do not use emojis** anywhere — code, comments, docstrings, docs, or terminal output. (Existing scripts use plain text status markers like `[ok]`, `[!]`, `[>]`.)
- **PowerShell escapes with backticks (`` ` ``), not backslashes.** All commands and scripts assume Windows 11 + PowerShell 7.
- **Only open-source LLMs.** No proprietary models in any config or default.

## Toolchain (non-negotiable choices)

| Concern | Tool | Why it matters |
|---------|------|----------------|
| Package management | `uv` | All commands prefixed with `uv run ...`. Never use `pip` or `python -m pip`. |
| Linting | `ruff` (configured in [pyproject.toml](../pyproject.toml)) | Line length 120, target py312, rules `E,F,I,UP,B,SIM`. |
| Knowledge graph | file-based JSON (`data/graph/`) loaded by `GraphStore` | **No database server.** See [src/kg_ae/graph/store.py](../src/kg_ae/graph/store.py). |
| Terminal output | `rich` | Use `Console`, `Panel`, `Table`, `Progress` — see [src/kg_ae/etl/runner.py](../src/kg_ae/etl/runner.py) for the canonical pattern. |
| Data frames | `polars` | Not pandas. All bronze/silver files are Parquet. |
| LLM / agent | `langchain` + `langgraph` + `langchain-openai` | One OpenAI-compatible `ChatOpenAI` client; `create_react_agent`. See [src/kg_ae/llm/agent.py](../src/kg_ae/llm/agent.py). |
| Web search (optional) | `langchain-tavily` | Scoped, airgap-gated entity-resolution tool only. |

## Repository layout (actual, not aspirational)

```
src/kg_ae/
  cli.py              Typer CLI entry point (kg-ae command)
  config.py           Pydantic-settings, KG_AE_* env vars, .env loading, airgap/compliance helpers
  datasets/<name>/    download.py + parse.py + (normalize.py) per source
    base.py           BaseDownloader / BaseParser / BaseNormalizer ABCs (BaseLoader is legacy)
  graph/store.py      GraphStore: in-memory JSON graph + get_store()
  graph/build.py      build_graph(): silver Parquet -> data/graph/*.json
  etl/runner.py       Live-dashboard ETL runner (download/parse/normalize; no SQL load)
  llm/llm_client.py   Single OpenAI-compatible ChatOpenAI factory + airgap guard
  llm/lc_tools.py     LangChain @tool wrappers (graph tools + optional Tavily)
  llm/agent.py        LangGraph create_react_agent + self-consistency ensemble
  tools/              Deterministic graph query tools (GraphStore-backed)
  db/                 DEPRECATED shim: imports succeed, calls raise (legacy load.py only)

scripts/              query_react.py (agent), graph_stats.py, peek_openfda.py
tests/                Pytest suite. Tool tests run against the built JSON graph (see conftest.py)
data/{raw,bronze,silver}/<source>/   Bronze->Parquet, Silver->canonical IDs applied
data/graph/           Built JSON graph (nodes.json, edges.json, meta.json)
docs/                 Linked from README; docs/compliance.md is the airgap source of truth
```

## Data flow: Bronze -> Silver -> JSON graph

1. `BaseDownloader.download()` -> `data/raw/<source>/` with SHA256 + retry logic.
2. `BaseParser.parse()` -> `data/bronze/<source>/*.parquet` (source-shaped).
3. `BaseNormalizer.normalize()` (optional) -> `data/silver/<source>/*.parquet` with canonical IDs joined.
4. `kg-ae build-graph` (`src/kg_ae/graph/build.py`) reads silver Parquet and emits `data/graph/{nodes,edges,meta}.json`. There is **no SQL load step** anymore.

When adding a new dataset: add `download.py`/`parse.py`/`normalize.py` like [src/kg_ae/datasets/sider/](../src/kg_ae/datasets/sider/), register it in `DATASETS` + `EXECUTION_ORDER` in [src/kg_ae/etl/runner.py](../src/kg_ae/etl/runner.py), then teach `GraphBuilder` (in `graph/build.py`) how to turn its silver tables into nodes/edges.

## Graph model essentials

- The graph is JSON, loaded by `GraphStore` ([src/kg_ae/graph/store.py](../src/kg_ae/graph/store.py)). Node types: `Drug`, `Gene`, `Pathway`, `Disease`, `AdverseEvent`.
- **Flattened claim-evidence**: each edge is an entity->entity link carrying its claim payload (`claim_type`, `strength_score`, `frequency`, `relation`, `effect`, `polarity`, `dataset`, `meta`) plus an `evidence` list. This preserves the old SQL claim-evidence provenance without a `Claim` node table.
- Entity keys are deterministic integers assigned at build time (stable across rebuilds). Genes are keyed by `symbol` and carry both `uniprot_id` and `ensembl_gene_id` so DrugCentral/Reactome (uniprot) and Open Targets (ensembl) join cleanly.
- Tools query the store via `get_store().out_edges(...)` / `in_edges(...)` / `find_by_name(...)`; they never touch a database.

## LLM orchestration

- One LangChain/LangGraph ReAct agent ([src/kg_ae/llm/agent.py](../src/kg_ae/llm/agent.py)) via `create_react_agent`. Entry point: `run_agent(query, ensemble_size, max_iterations)`. "Multiple agents" = a self-consistency ensemble (`KG_AE_AGENT_ENSEMBLE_SIZE`) whose answers are reconciled by a final pass.
- One OpenAI-compatible client ([src/kg_ae/llm/llm_client.py](../src/kg_ae/llm/llm_client.py)): `build_chat_model()`. Provider is `KG_AE_LLM_PROVIDER=openrouter|local`; only `KG_AE_LLM_BASE_URL` + `KG_AE_LLM_MODEL` differ between dev and deployment.
- Tools are registered in [src/kg_ae/llm/lc_tools.py](../src/kg_ae/llm/lc_tools.py) (`GRAPH_TOOLS` + `build_tools()`). When you add a tool to `src/kg_ae/tools/`, wrap it with `@tool` there and document it in [docs/tools-api.md](../docs/tools-api.md). Outputs are truncated to `MAX_ITEMS_PER_TOOL = 30`.
- **Tavily** (`tool_web_verify`) is registered only when `settings.web_search_enabled()` is true (online, key set). It is scoped to entity resolution/verification and must never be treated as evidence.
- **Airgap guard**: `build_chat_model()` calls `enforce_compliance()`, which raises `ComplianceError` if `KG_AE_AIRGAPPED=true` and the LLM URL is non-local or web search is on. See [docs/compliance.md](../docs/compliance.md).

## Common commands

```powershell
uv sync                                      # install deps
uv run kg-ae build-graph                     # build data/graph/*.json from silver Parquet
uv run kg-ae doctor                          # show LLM + compliance posture
uv run python -m kg_ae.cli etl               # interactive ETL dashboard (download/parse/normalize)
uv run python -m kg_ae.cli etl --tier 1      # only foundational sources
uv run python -m kg_ae.cli etl --dataset sider --force   # one source + deps, force re-process

uv run kg-ae query "What AEs do statins share?"
uv run python scripts/query_react.py --ensemble 3 "Why might atorvastatin cause myopathy?"
uv run python scripts/graph_stats.py         # node/edge/claim-type stats

uv run pytest                                # full suite (tool tests run against the JSON graph)
uv run ruff check . && uv run ruff format .  # lint + format
```

## Pitfalls and prior lessons

- **Python 3.12+** (`requires-python` in [pyproject.toml](../pyproject.toml)). `uv` manages the interpreter.
- **Build the graph before querying.** `GraphStore` raises if `data/graph/nodes.json` is missing; run `uv run kg-ae build-graph` first. The store is `lru_cache`d per process.
- **`kg_ae.db` is a deprecated shim.** Imports succeed (so legacy dataset `load.py` files still import) but any call raises. Do not add new SQL; build graph edges in `graph/build.py` instead.
- **Non-prefixed secrets.** `OPENROUTER_API_KEY` and `TAVILY_API_KEY` are read via `os.getenv` fallbacks; `config.py` calls `load_dotenv()` at import so they land in the environment. `KG_AE_*` vars are handled by pydantic-settings.
- **Airgap is enforced, not advisory.** With `KG_AE_AIRGAPPED=true`, a remote `KG_AE_LLM_BASE_URL` makes `build_chat_model()` raise `ComplianceError`. Point it at `http://localhost:11434/v1` (Ollama) etc.
- **Only open-source models.** Defaults are Mistral Small (recommended) / Gemma. No proprietary models in any config.
- **Licensing surface.** SIDER is CC BY-NC-SA (non-commercial). Don't enable it in a product-track build without a license note.
- **AE terminology.** Source AE strings (SIDER MedDRA, openFDA reaction text) lack a shared ontology; the resolver is string-based. Treat AE labels cautiously as identifiers.
- **Aspirational vs current code.** [.github/copilot-planning/](copilot-planning/) notes predate this re-architecture (they describe SQL Server). Trust the source.

## Documentation map

| Topic | File |
|-------|------|
| Project overview, graph stats, example queries | [README.md](../README.md) |
| EU airgapped deployment + compliance switch | [docs/compliance.md](../docs/compliance.md) |
| Query workflow walkthrough | [workflow.md](../workflow.md) |
| Setup (env) | [docs/setup.md](../docs/setup.md) |
| ETL pipeline runner | [docs/etl-guide.md](../docs/etl-guide.md) |
| All 13 data sources (URLs, licenses, fields) | [docs/data-sources.md](../docs/data-sources.md) |
| LLM endpoint setup (OpenRouter / local) | [docs/llm-setup.md](../docs/llm-setup.md) |
| Tool function reference for the LLM | [docs/tools-api.md](../docs/tools-api.md) |
| Scoring math + provenance hierarchy | [docs/scoring-policy.md](../docs/scoring-policy.md) |
