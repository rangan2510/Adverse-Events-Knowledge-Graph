# Drug-AE Knowledge Graph

A pharmacovigilance knowledge graph with **agentic reasoning** for mechanistic adverse event analysis.

## Overview

This system addresses a core limitation in LLM-based biomedical question answering: the tendency to hallucinate plausible-sounding but ungrounded causal relationships. We constrain the LLM to operate as a **reasoning controller** over deterministic graph traversal tools, ensuring every claim is traceable to curated evidence.

### Architecture

The system implements a **ReAct-style agentic loop** with strict separation of concerns:

```
User Query
    |
    v
[Thought]  Planner LLM reasons about information needs     (Phi-4-mini, fast)
[Action]   Planner emits tool calls as structured JSON
[Execute]  Deterministic tools query SQL Server graph       (no LLM involvement)
[Observe]  Narrator LLM evaluates result sufficiency        (Phi-4, high capacity)
    |
    +---> Loop if insufficient | Generate final response
```

**Key constraint**: The LLM can only access the knowledge graph through typed tool functions. It cannot fabricate edges, invent gene targets, or cite non-existent studies. All associations in the response derive from:

- **DrugCentral / ChEMBL**: Drug-target binding evidence
- **Reactome**: Curated pathway membership
- **Open Targets**: Gene-disease association scores
- **SIDER / FAERS**: Adverse event frequencies and signals

### Graph Schema

Mechanistic paths follow the provenance-tracked claim-evidence pattern:

```
Drug -[HasClaim]-> Claim -[ClaimGene]-> Gene -[HasClaim]-> Claim -[ClaimPathway]-> Pathway
                     |                                        |
              [SupportedBy]                            [SupportedBy]
                     v                                        v
                 Evidence                                 Evidence
```

Every edge carries: `source` (dataset + version), `evidence_ids` (provenance links), `score` (0-1 normalized), and `meta_json` (raw fields preserved).

![LLM Query Demo](docs/screenshot.png)

## Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager
- SQL Server 2025 (localhost, sa/password1$, database: `kg_ae`)

## Setup

```bash
uv sync                    # Install dependencies
uv run kg-ae init-db       # Create database schema
```

## ETL Pipeline

Interactive pipeline with live status dashboard. See [docs/etl-guide.md](docs/etl-guide.md) for full details.

```bash
# Interactive mode with live dashboard
uv run python -m kg_ae.cli etl

# Run specific dataset
uv run python -m kg_ae.cli etl --dataset sider

# Run by tier (1=foundational, 2=extensions, 3=associations, 4=advanced)
uv run python -m kg_ae.cli etl --tier 1

# Batch mode (no prompts)
uv run python -m kg_ae.cli etl --batch --force
```

## Data Directories

```
data/
  raw/         # Downloaded archives
  bronze/      # Parsed to Parquet (source-shaped)
  silver/      # Normalized (canonical IDs)
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

## Example Query

```sql
-- Trace mechanistic path: Drug → Gene → Disease
SELECT d.preferred_name, g.symbol, dis.label, c2.strength_score
FROM kg.Drug d, kg.HasClaim hc1, kg.Claim c1, kg.ClaimGene cg, kg.Gene g,
     kg.HasClaim hc2, kg.Claim c2, kg.ClaimDisease cd, kg.Disease dis
WHERE MATCH(d-(hc1)->c1-(cg)->g)
  AND MATCH(g-(hc2)->c2-(cd)->dis)
  AND d.preferred_name = 'atorvastatin'
ORDER BY c2.strength_score DESC
```

## Agentic Query Interface

Natural language queries with ReAct-style iterative reasoning. The planner decomposes complex questions into tool sequences; the narrator synthesizes graph evidence into grounded responses.

```bash
# Setup LLM servers (first time)
.\scripts\setup_llm.ps1
.\scripts\start_llm_servers.ps1

# Single-pass query (plan once, execute, narrate)
uv run python scripts/query_kg.py "What adverse events does metformin cause?"

# Multi-iteration reasoning (ReAct loop with observation-driven refinement)
uv run python scripts/query_iterative.py "What genes does metformin target and what pathways are they involved in?"

# Interactive mode
uv run python scripts/query_iterative.py --interactive
```

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
| [docs/data-sources.md](docs/data-sources.md) | Complete reference for all 13 data sources |
| [docs/etl-guide.md](docs/etl-guide.md) | ETL pipeline usage and commands |
| [docs/setup.md](docs/setup.md) | Database and environment setup |
| [docs/llm-setup.md](docs/llm-setup.md) | LLM server setup and configuration |
| [docs/tools-api.md](docs/tools-api.md) | Tool functions API reference |
| [docs/iterative_reasoning.md](docs/iterative_reasoning.md) | Iterative query refinement system |
