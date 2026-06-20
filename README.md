# Drug-AE Knowledge Graph

A pharmacovigilance knowledge graph with **agentic reasoning** for mechanistic adverse event analysis.

## Overview

This system addresses a core limitation in LLM-based biomedical question answering: the tendency to hallucinate plausible-sounding but ungrounded causal relationships. We constrain the LLM to operate as a **reasoning controller** over deterministic graph traversal tools, ensuring every claim is traceable to curated evidence.

### Architecture

The system is **file-based and local-first**. The knowledge graph is a set of
JSON files (no database server), and the agent reaches the LLM over a single
OpenAI-compatible endpoint, so the airgapped hospital build is the same code as
the dev build minus any online capability. See [docs/compliance.md](docs/compliance.md).

```
User Query
    |
    v
[LangChain ReAct agent]  reasons about information needs
    |  emits tool calls
    v
[Deterministic graph tools]  query the in-memory JSON graph (no LLM, no DB)
    |  structured results
    v
[Agent narration]  summarizes ONLY what the tools returned
```

**Key constraint**: The LLM can only access the knowledge graph through typed
tool functions. It cannot fabricate edges, invent gene targets, or cite
non-existent studies. All associations derive from curated sources:

- **DrugCentral / ChEMBL**: Drug-target binding evidence
- **Reactome**: Curated pathway membership
- **Open Targets**: Gene-disease association scores
- **SIDER / FAERS**: Adverse event frequencies and signals

Multiple agents can answer the same query and reconcile (self-consistency
ensemble, `KG_AE_AGENT_ENSEMBLE_SIZE`) for robustness.

### Graph Schema

The graph is a set of JSON files loaded in memory by `GraphStore`. Each edge is
a flattened entity-to-entity link that carries its claim payload and evidence,
so mechanistic chains read directly off the edges:

```
Drug --(targets)--> Gene --(in pathway)--> Pathway
  |                   |
  |                   +--(associated with)--> Disease
  +--(adverse event)--> AdverseEvent
```

Every edge carries: `dataset` (source + version), `claim_type`,
`strength_score` (0-1 normalized), `relation`/`effect`, an `evidence` list
(provenance), and `meta` (raw fields preserved). The old SQL claim-evidence
node pattern was flattened into these edges; provenance is preserved end to end.

![LLM Query Demo](docs/screenshot.png)

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- An OpenAI-compatible LLM endpoint:
  - dev: an [OpenRouter](https://openrouter.ai/) API key, or
  - deployment: a local server (Ollama / LM Studio / vLLM) serving an
    open-source model (Mistral Small recommended)

No database server is required.

## Setup

```bash
uv sync                       # Install dependencies
cp .env.example .env          # or edit .env directly; set OPENROUTER_API_KEY
uv run kg-ae build-graph      # Build the JSON knowledge graph from silver data
uv run kg-ae doctor           # Show the active LLM / compliance configuration
```

## Run with Docker (recommended for your colleague)

The image bakes the knowledge graph in (built from the silver Parquet during
the build), so the only thing to provide is an OpenRouter key.

```powershell
copy .env.example .env        # then set OPENROUTER_API_KEY in .env
docker compose build          # first build is slow; later runs are instant

# One-shot query (streams the answer to the console)
docker compose run --rm kg-ae query "Why might atorvastatin cause myopathy?"

# Interactive prompt loop
docker compose run --rm kg-ae

# Check the active LLM / compliance posture
docker compose run --rm kg-ae doctor
```

Equivalent with plain `docker`:

```powershell
docker build -t kg-ae:latest .
docker run --rm -it --env-file .env kg-ae:latest query "What does atorvastatin target?"
```

The airgapped local-model path is not included yet; switching to it later is an
env-var change (`KG_AE_LLM_BASE_URL` + `KG_AE_AIRGAPPED=true`). See
[docs/compliance.md](docs/compliance.md).

## ETL Pipeline

The ETL pipeline downloads (aria2c, parallel), parses, and normalizes the 16
sources, logging each step as a single structured line. See
[docs/etl-guide.md](docs/etl-guide.md) for full details.

```bash
# Full pipeline (download -> parse -> normalize)
uv run python -m kg_ae.cli etl

# Run a specific dataset (with dependencies)
uv run python -m kg_ae.cli etl --dataset sider

# Run by tier (1=foundational, 2=extensions, 3=associations, 4=advanced)
uv run python -m kg_ae.cli etl --tier 1 --force

# Full staging artifact (download -> normalize -> build graph -> verify)
uv run kg-ae stage all
```

## Data Directories

```
data/
  raw/         # Downloaded archives
  bronze/      # Parsed to Parquet (source-shaped)
  silver/      # Normalized (canonical IDs)
  graph/       # Built JSON knowledge graph (nodes.json, edges.json, meta.json)
```

## Graph Statistics

| Entity | Count | Source |
|--------|-------|--------|
| Drugs | 5,528 | SIDER, DrugCentral |
| Genes | 1,970 | DrugCentral |
| Pathways | 2,848 | Reactome |
| Diseases | 28,392 | Open Targets |
| Adverse Events | 4,251 | SIDER |
| Claims | 253,137 | All sources |

## Example Query (tools)

```python
from kg_ae.tools import resolve_drugs, get_drug_targets, get_gene_pathways

drug = resolve_drugs(["atorvastatin"])["atorvastatin"]
targets = get_drug_targets(drug.key)            # Drug -> Gene
pathways = get_gene_pathways(targets[0].gene_key)  # Gene -> Pathway
```

Each result is a dataclass carrying the source dataset and a normalized score,
so every fact is traceable to curated evidence.

## Agentic Query Interface

Natural language queries answered by a LangChain/LangGraph ReAct agent over the
JSON graph. The LLM is a single OpenAI-compatible endpoint:

| Mode | `KG_AE_LLM_BASE_URL` | Models |
|------|----------------------|--------|
| **Dev (OpenRouter)** | `https://openrouter.ai/api/v1` | `mistralai/mistral-small-3.2-24b-instruct`, `google/gemma-3-27b-it` |
| **Deployment (local)** | `http://localhost:11434/v1` | any local open-source model (Ollama / LM Studio / vLLM) |

```bash
# Configure provider in .env (OPENROUTER_API_KEY, KG_AE_LLM_*)
uv run python scripts/query_react.py "What gene does atorvastatin target?"

# Self-consistency ensemble (run N agents, reconcile)
uv run python scripts/query_react.py --ensemble 3 "AEs shared by statins?"

# Interactive mode
uv run python scripts/query_react.py --interactive

# Or via the CLI
uv run kg-ae query "What adverse events does metformin cause?"
```

For EU airgapped deployment (local model, no web search), see
[docs/compliance.md](docs/compliance.md).

### ReAct Loop

```
Query -> [reason] -> [tool calls] -> [execute on JSON graph] -> [observe] -> loop or answer
```

The agent reasons about information needs, calls deterministic graph tools, and
narrates only what they return. Tool outputs are truncated
(`MAX_ITEMS_PER_TOOL`) to keep the context window bounded.

### Available Tools

| Tool | Purpose |
|------|---------|
| `resolve_drugs` | Entity resolution: name -> canonical drug_key |
| `resolve_genes` | Entity resolution: symbol/name -> gene_key |
| `get_drug_targets` | Drug -> Gene edges (mechanism of action) |
| `get_drug_adverse_events` | Drug -> AE edges (SIDER frequencies) |
| `get_drug_faers_signals` | Drug -> AE edges (FAERS disproportionality) |
| `get_gene_pathways` | Gene -> Pathway membership (Reactome) |
| `get_gene_diseases` | Gene -> Disease associations (Open Targets) |
| `get_drug_profile` | Comprehensive drug summary |

## Documentation

| Document | Description |
|----------|-------------|
| [CHANGELOG.md](CHANGELOG.md) | Notable changes (agent, ETL, architecture) |
| [docs/compliance.md](docs/compliance.md) | EU airgapped deployment + compliance switch |
| [docs/data-sources.md](docs/data-sources.md) | Complete reference for all 16 data sources |
| [docs/etl-guide.md](docs/etl-guide.md) | ETL pipeline usage and commands |
| [docs/setup.md](docs/setup.md) | Environment setup |
| [docs/llm-setup.md](docs/llm-setup.md) | LLM endpoint setup (OpenRouter / local) + model evaluation |
| [docs/tools-api.md](docs/tools-api.md) | Tool functions API reference |
