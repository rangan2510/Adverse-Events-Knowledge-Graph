# Copilot Instructions for Drug-AE Knowledge Graph Project

## Project Overview

This is a **pharmacovigilance knowledge graph** system that identifies potential drug-adverse event (AE) relationships through mechanistic pathways. Given a drug list and patient conditions, it returns evidence-backed networks:

```
Drug → Gene/Protein → Pathway → Disease/Condition → Adverse Event
```

### Core Constraints
- **Local-first, pure Python** — no live web retrieval at runtime
- **SQL Server 2025** backend using graph tables (`AS NODE`/`AS EDGE`), JSON columns, and `VECTOR(1536)` embeddings
- **LLM (llama.cpp) is the orchestrator, NOT the reasoner** — it can only call tools and summarize graph outputs; it never invents edges

## Architecture

### Data Flow (Bronze → Silver → Gold)
```
data/raw/       → Downloaded archives (JSON, TSV, dumps)
data/bronze/    → Parsed to Parquet/CSV (source-shaped)
data/silver/    → Normalized tables (canonical IDs applied)
data/gold/      → Graph-ready edge tables + evidence
```

### Planned Python Package Layout
```
src/kg_ae/
  datasets/     # One module per data source (download, parse, normalize)
  resolve/      # Entity resolution: drug/gene/disease/ae identity
  etl/          # Pipelines + checkpoints
  graph/        # SQL graph loaders + traversal queries
  evidence/     # Scoring + provenance
  tools/        # LLM tool functions (thin wrappers over graph/queries)
```

### Key Design Patterns

1. **Claim-Evidence Pattern**: Associations are first-class `Claim` nodes with edges to `Evidence` nodes for full provenance tracking

2. **Canonical ID Strategy** (see [docs/milestones.md](../docs/milestones.md#2-canonical-id-strategy-this-makes-or-breaks-the-project)):
   - Drug: `drug_key` (internal) + DrugCentral ID, ChEMBL ID, PubChem CID, InChIKey
   - Gene: `gene_key` + HGNC ID (canonical), Ensembl, UniProt
   - Disease: `disease_key` + MONDO ID (canonical), DOID, EFO
   - Pathway: `pathway_key` + Reactome ID, WikiPathways ID
   - Adverse Event: `ae_key` + label (strings from openFDA/SIDER), optional OAE mapping

3. **Every edge carries provenance**:
   - `source` (dataset + version)
   - `evidence_ids` (one-to-many link to Evidence nodes)
   - `score` (normalized 0–1)
   - `meta_json` (raw fields preserved)

## SQL Server 2025 Schema

The schema lives in the `kg` schema namespace. Key tables (see [docs/schema.md](../docs/schema.md)):

### Node Tables
| Table | Purpose | Key External IDs |
|-------|---------|------------------|
| `kg.Drug` | Drug entities | `drugcentral_id`, `chembl_id`, `pubchem_cid`, `inchikey` |
| `kg.Gene` | Gene/protein entities | `hgnc_id`, `ensembl_gene_id`, `uniprot_id` |
| `kg.Disease` | Disease/condition entities | `mondo_id`, `doid`, `efo_id` |
| `kg.Pathway` | Biological pathways | `reactome_id`, `wikipathways_id` |
| `kg.AdverseEvent` | Adverse event terms | `ae_label`, `ae_code`, `ae_ontology` |
| `kg.Claim` | Assertions linking entities | `claim_type`, `strength_score`, `dataset_id` |
| `kg.Evidence` | Provenance records | `evidence_type`, `source_record_id`, `payload_json` |

### Edge Tables
| Table | From → To | Purpose |
|-------|-----------|---------|
| `kg.HasClaim` | Drug/Gene/etc → Claim | Links entities to claims about them |
| `kg.ClaimGene` | Claim → Gene | Drug-target relationships |
| `kg.ClaimDisease` | Claim → Disease | Indication/contraindication |
| `kg.ClaimPathway` | Claim → Pathway | Pathway membership/perturbation |
| `kg.ClaimAdverseEvent` | Claim → AdverseEvent | Drug-AE associations |
| `kg.SupportedBy` | Claim → Evidence | Provenance links |

### Relational Metadata
- `kg.Dataset` — Registry of data sources (version, license, SHA256)
- `kg.IngestRun` — ETL run tracking (status, row counts, timestamps)

## Data Sources

### MVP Bundle (Milestone A)
| Layer | Source | License | Notes |
|-------|--------|---------|-------|
| Drug ↔ Target | ChEMBL, DrugCentral | CC BY-SA, Open | Primary mechanism data |
| Gene ↔ Disease | Open Targets, CTD | CC0, Open | Disease associations |
| Pathways | Reactome | CC BY 4.0 | Curated pathways |
| Adverse Events | SIDER, openFDA FAERS | CC BY-NC-SA*, Public | *SIDER is non-commercial |
| Identifiers | HGNC, MONDO, UniProt | CC0/CC BY 4.0 | Cross-reference mappings |

### API Endpoints (for subset testing)
- **DrugCentral**: `https://drugcentral.org/OpenAPI`
- **openFDA FAERS**: `https://api.fda.gov/drug/event.json`
- **Reactome Content Service**: `https://reactome.org/ContentService/`
- **Open Targets GraphQL**: `https://api.platform.opentargets.org/api/v4/graphql`

## LLM Tool Interface

The LLM calls these deterministic tools (see [docs/milestones.md](../docs/milestones.md#6-llm-orchestration-llamacpp--strict-tool-calling)):

```python
resolve_entities(drugs, conditions)      # → canonical IDs + confidence
get_drug_profile(drug_id)                # → targets, indications, known AEs
expand_gene_context(gene_ids)            # → pathways, diseases
find_paths(start_nodes, end_nodes, constraints)
rank_paths(paths, patient_context)
export_subgraph(nodes, edges, format)    # → JSON or GraphML
```

**Critical rule**: Tools execute synchronously. The LLM only gets results after tool completion — no streaming final answers until tools finish.

## Conventions

### JSON Columns
- All `*_json` columns store valid JSON (enforced by `ISJSON()` constraints)
- Common patterns: `synonyms_json`, `xrefs_json`, `meta_json`, `payload_json`

### Embeddings
- `VECTOR(1536)` columns for semantic similarity search
- Used for entity resolution fallback and AE term matching

### Scoring
- All scores normalized to 0–1 range
- Edge score formula: `w_source × w_field_quality × w_recency × w_frequency × resolver_conf`
- Evidence hierarchy: curated pharmacology > curated DB > label-listed AE > FAERS signal > SIDER

### ETL Patterns
- Use `BULK INSERT` / bcp for large files
- `pyodbc` with `fast_executemany=True` for batch inserts
- Stage data in temp tables, then MERGE into graph tables
- Always record dataset version and file hashes in `kg.Dataset`

## Development Milestones

| Milestone | Deliverable |
|-----------|-------------|
| **A** | KG skeleton: ChEMBL + Reactome + Open Targets + SIDER + SQL schema |
| **B** | Query engine: subgraph extraction + path ranking + JSON/Cytoscape export |
| **C** | LLM wrapper: tool schemas + dispatcher + guarded finalization |
| **D** | Hardening: caching, version pinning, eval suite, CI |

## Key Files

- [docs/milestones.md](../docs/milestones.md) — Full project plan with 10 sections
- [docs/schema.md](../docs/schema.md) — Complete SQL Server DDL for graph schema
- [docs/steps-1-2-3.md](../docs/steps-1-2-3.md) — Detailed ETL implementation plan

## Gotchas

1. **Licensing**: SIDER is non-commercial; DGIdb sources may be restrictive
2. **MedDRA**: Avoid dependency — use openFDA reaction terms + OAE mapping
3. **ID mapping churn**: Pin Open Targets releases; store version tags
4. **AE terminology mismatch**: Expect resolver/mapping layer between SIDER/FAERS and OAE

# Coding rules
- Powershell uses backticks to escape. Use backticks where needed.
- Mind this when executing commands in Powershell, SQL or Python scripts.
- DO NOT USE any emojis in code, comments, docstrings, or documentation.
- use `uv` for python package management
- use `sqlcmd` for running sql scripts
- Dev machine uses Windows 11 and Powershell 7. 
- use `rich` for colored terminal output in python scripts.
   - for loops or longer scripts, try to show verbose progress or completion percentages where possible.
   - use spinners and progress bars for long running tasks.
   - use panels and tables to summarize statistics or important information.
- use `mssql_python` for connecting to sql server from python.
   - more infroamtion here [https://github.com/microsoft/mssql-python]