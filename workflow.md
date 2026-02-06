# KG-AE Query Workflow

This document describes the iterative query workflow for the Drug-AE Knowledge Graph system.

## Configuration

### Current Setup (Groq Cloud with gpt-oss-20b)

```dotenv
# .env settings
KG_AE_LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-20b
GROQ_PLANNER_MAX_TOKENS=4096
GROQ_NARRATOR_MAX_TOKENS=8192
```

### Alternative Models

| Model | Provider | Notes |
|-------|----------|-------|
| `openai/gpt-oss-20b` | Groq | Reasoning model, uses more tokens but better planning |
| `llama-3.3-70b-versatile` | Groq | Faster, lower token usage |
| `phi4mini` + `phi4` | Local | No rate limits, requires llama.cpp servers |

---

## Query Script

```powershell
uv run python scripts/query_iterative.py --max-iterations <N> "<query>"
```

Options:
- `--max-iterations N` : Maximum ReAct loop iterations (default: 3)
- `--quiet` : Suppress verbose output

---

## Use Cases

### 1. Single Drug Adverse Events

**Goal**: Get known adverse events for a specific drug.

```powershell
uv run python scripts/query_iterative.py --max-iterations 3 "What are the known adverse events of metformin?"
```

**Expected Flow**:
1. `resolve_drugs(["metformin"])` - Get drug_key
2. `get_drug_adverse_events(drug_key)` - Get AE list

**Result**: Returns count of AEs (84 for metformin in test DB).

---

### 2. Drug Targets and Pathways

**Goal**: Explore mechanistic pathways for a drug.

```powershell
uv run python scripts/query_iterative.py --max-iterations 4 "What gene targets does aspirin have and what pathways are they involved in?"
```

**Expected Flow**:
1. `resolve_drugs(["aspirin"])` - Get drug_key
2. `expand_mechanism(drug_key)` - Get targets + pathways

**Result**: Returns target genes and associated biological pathways.

---

### 3. Drug Comparison (Shared AEs)

**Goal**: Find overlapping adverse events between two or more drugs.

```powershell
uv run python scripts/query_iterative.py --max-iterations 4 "Compare the adverse event profiles of warfarin and aspirin - what AEs do they share?"
```

**Expected Flow**:
1. `resolve_drugs(["warfarin", "aspirin"])` - Get drug_keys
2. `get_drug_adverse_events(drug_key_0)` - Get warfarin AEs
3. `get_drug_adverse_events(drug_key_1)` - Get aspirin AEs
4. `get_drug_profile(drug_key_0)` - Get full profile if needed
5. `get_drug_profile(drug_key_1)` - Get full profile if needed

**Note**: May require multiple iterations if AE data needs resolution to readable names.

---

### 4. Drug Target Query

**Goal**: Find what genes a drug targets.

```powershell
uv run python scripts/query_iterative.py --max-iterations 3 "What genes does ibuprofen target?"
```

**Expected Flow**:
1. `resolve_drugs(["ibuprofen"])` - Get drug_key
2. `get_drug_targets(drug_key)` - Get gene targets

---

### 5. Immunosuppressant Comparison

**Goal**: Compare safety profiles of related drugs.

```powershell
uv run python scripts/query_iterative.py --max-iterations 5 "What are the shared adverse events between cyclosporine, tacrolimus, and sirolimus? What safety concerns should be monitored when using these immunosuppressants?"
```

**Expected Flow**:
1. `resolve_drugs(["cyclosporine", "tacrolimus", "sirolimus"])` - Get drug_keys
2. `get_drug_adverse_events(drug_key_N)` - For each drug
3. Compare AE lists for overlap

---

### 6. Polypharmacy Safety Check

**Goal**: Identify overlapping safety concerns for commonly co-prescribed drugs.

```powershell
uv run python scripts/query_iterative.py --max-iterations 5 "What are the shared adverse events between metformin, lisinopril, atorvastatin, and omeprazole? Are there any overlapping safety concerns when these drugs are used together?"
```

**Expected Flow**:
1. Resolve all 4 drugs
2. Get AEs for each
3. Identify shared AEs across the drug set

---

## ReAct Loop Architecture

```
User Query
    |
    v
[Planner LLM] --> ToolPlan (JSON)
    |                |
    |                v
    |         [Tool Executor]
    |                |
    v                v
[Narrator LLM] <-- Tool Results
    |
    v
[Observation: SUFFICIENT/INSUFFICIENT/PARTIAL]
    |
    +-- INSUFFICIENT --> Loop back to Planner
    |
    +-- SUFFICIENT --> Generate Final Response
```

### Output Components

Each iteration displays:

1. **Planner Thought** (magenta panel)
   - Reasoning about what information is needed
   - Observations from prior iterations (iter 2+)
   - Action trace summary (iter 2+)

2. **Action Table** (blue)
   - Tool calls with arguments and reasons

3. **Tool Results** (green table)
   - Status (OK/ERR)
   - Result summary
   - Key details

4. **Narrator Observation** (cyan panel)
   - Status: SUFFICIENT / INSUFFICIENT / PARTIAL
   - Confidence: high / medium / low
   - Information gaps (if any)

---

## Available Tools

### Entity Resolution (call first)
- `resolve_drugs(names)` - Drug names to keys
- `resolve_genes(symbols)` - Gene symbols to keys
- `resolve_diseases(terms)` - Disease terms to keys
- `resolve_adverse_events(terms)` - AE terms to keys

### Mechanism Exploration
- `get_drug_targets(drug_key)` - Gene targets for a drug
- `get_gene_pathways(gene_key)` - Pathways containing a gene
- `get_gene_diseases(gene_key)` - Disease associations
- `expand_mechanism(drug_key)` - Full mechanism (targets + pathways)
- `expand_gene_context(gene_keys)` - Context for multiple genes

### Adverse Events
- `get_drug_adverse_events(drug_key)` - Known AEs for a drug
- `get_drug_profile(drug_key)` - Complete drug profile

### Evidence
- `get_claim_evidence(claim_key)` - Evidence trail for a claim
- `get_entity_claims(entity_type, entity_key)` - Claims for an entity

### Path Finding
- `find_drug_to_ae_paths(drug_key, ae_key)` - Mechanistic paths
- `explain_paths(drug_key, ae_key)` - Explained paths with context

### Subgraph
- `build_subgraph(drug_keys)` - Build visualization subgraph

---

## Troubleshooting

### Rate Limits (Groq)

```
Error code: 429 - Rate limit reached for model
```

**Solutions**:
1. Wait for reset (shown in error message)
2. Switch to `llama-3.3-70b-versatile` (lower token usage)
3. Use local llama.cpp servers (no limits)

### Drug Not Found

If `resolve_drugs` returns 0 items, the drug may not be in the database. Check available drugs:

```powershell
uv run python -c "from kg_ae.tools.resolve import resolve_drugs; print(resolve_drugs(['your_drug']))"
```

### Tool Not Found

Some tools in the prompt may not be implemented yet. Check error message for "Unknown tool" and use alternative tools.

---

## Rate Limit Reference (Groq Free Tier)

| Model | Daily Token Limit |
|-------|-------------------|
| `llama-3.3-70b-versatile` | 100,000 TPD |
| `openai/gpt-oss-20b` | 200,000 TPD |

The gpt-oss model uses ~2-3x more tokens per query due to internal reasoning.

---

## Polypharmacy Validation Results

Tested 4 polypharmacy combos against ground truth extracted directly from the database.
All tests used `openai/gpt-oss-20b` via Groq, max 5 iterations.

### Combo 1: Cardiovascular (warfarin + verapamil + metoprolol)

```powershell
uv run python scripts/query_iterative.py --max-iterations 5 "A patient is on warfarin, verapamil, and metoprolol. What shared molecular targets and adverse events should we watch for?"
```

| Metric | Ground Truth (DB) | Agent Found | Verdict |
|--------|-------------------|-------------|---------|
| Shared targets (3-drug) | CYP3A4 | CYP3A4, CASP3 | PASS |
| Shared AEs (3-drug) | Oedema, Dizziness, Headache | Oedema, Blood creatinine increased, Oedema peripheral | PARTIAL |
| Iterations / Tools | - | 2 iter, 4 tools | Efficient |

**Notes**: Agent correctly identified CYP3A4 as the key shared metabolic target. Found Oedema but missed Dizziness and Headache from the AE overlap. Found an additional shared target (CASP3) not in the 3-drug ground truth intersection query.

---

### Combo 2: Psychiatric (ziprasidone + venlafaxine + lithium)

```powershell
uv run python scripts/query_iterative.py --max-iterations 5 "A patient takes ziprasidone, venlafaxine, and lithium. Identify shared molecular targets and any adverse event concerns."
```

| Metric | Ground Truth (DB) | Agent Found | Verdict |
|--------|-------------------|-------------|---------|
| Shared targets (pairwise zip+ven) | SLC6A4, HTR2A | HTR2A, HTR2C, HTR6, SLC6A2, SLC6A3, SLC6A4 | PASS |
| Serotonin syndrome risk | Expected | Flagged in response | PASS |
| Lithium targets in DB | 0 | 0 (correctly noted empty) | PASS |
| Iterations / Tools | - | 2 iter, 4 tools | Efficient |

**Notes**: Agent found all pairwise shared serotonin targets and correctly flagged serotonin syndrome risk. Lithium having zero targets in the DB was correctly reported. AE data was sparse (only venlafaxine had AEs), which the agent acknowledged.

---

### Combo 3: Oncology (vorinostat + imatinib + methotrexate)

```powershell
uv run python scripts/query_iterative.py --max-iterations 5 "A cancer patient is taking vorinostat, imatinib, and methotrexate. What shared molecular targets and adverse events should we be concerned about?"
```

| Metric | Ground Truth (DB) | Agent Found | Verdict |
|--------|-------------------|-------------|---------|
| Shared targets (pairwise) | ABCB1, ABL1, HDAC1, SRC (+ many more) | Claimed "empty intersection" | FAIL |
| Shared AEs | Pancytopenia, Neutropenia (from methotrexate) | Only methotrexate AEs found | FAIL (data gap) |
| Iterations / Tools | - | 5 iter, 14 tools (hit max) | Exhausted |

**Notes**: This was the weakest result. The agent received the full target lists (140+ for vorinostat, 100+ for imatinib, 200+ for methotrexate) but the LLM incorrectly claimed the 3-way intersection was empty. In reality, ABL1, BRAF, and MAPK10 appear in both vorinostat and imatinib target lists. The AE data gap is real: vorinostat and imatinib have no AE records in the DB. The agent correctly tried multiple AE retrieval strategies (get_drug_adverse_events, get_drug_faers_signals, get_drug_label_sections, get_entity_claims) but all returned empty.

**Root cause of target overlap failure**: The target lists were very large and truncated at 6000 chars in the context window. The LLM could not cross-reference 400+ gene symbols across 3 drugs within the context. This is a fundamental limitation of having the LLM do set intersection on large lists rather than having a dedicated tool for it.

**Improvement needed**: Add a `find_shared_targets(drug_keys: list[int])` tool that performs the set intersection in SQL/Python and returns the overlap directly.

---

### Combo 4: Pain/NSAID (ibuprofen + aspirin + celecoxib)

```powershell
uv run python scripts/query_iterative.py --max-iterations 5 "A patient is taking ibuprofen, aspirin, and celecoxib together. What shared molecular targets and adverse events should we be concerned about?"
```

| Metric | Ground Truth (DB) | Agent Found | Verdict |
|--------|-------------------|-------------|---------|
| Shared targets (3-drug) | PTGS1, PTGS2 (+ many more) | PTGS1, PTGS2, TNF, IL1B, IL6, GDF15 | PASS |
| COX pathway explanation | Expected | Detailed COX-1/COX-2 mechanism described | PASS |
| GI bleeding risk | Key concern | Gastric ulcer + hemorrhagic disorder flagged | PASS |
| Shared AEs (3-drug) | No 3-way overlap in DB | No overlap found | PASS (correct) |
| Iterations / Tools | - | 3 iter, 6 tools | Efficient |

**Notes**: Best result. Agent correctly identified the core PTGS1/PTGS2 (COX-1/COX-2) shared targets, explained the prostaglandin-mediated GI protection mechanism, and flagged relevant GI adverse events from individual drug profiles. The 3-drug AE overlap being empty was correctly reported.

---

### Summary

| Combo | Domain | Targets | AEs | Iterations | Overall |
|-------|--------|---------|-----|------------|---------|
| 1. Cardiovascular | warfarin+verapamil+metoprolol | PASS | PARTIAL | 2 / 4 tools | Good |
| 2. Psychiatric | ziprasidone+venlafaxine+lithium | PASS | PARTIAL (data gap) | 2 / 4 tools | Good |
| 3. Oncology | vorinostat+imatinib+methotrexate | FAIL | FAIL (data gap) | 5 / 14 tools | Poor |
| 4. Pain/NSAID | ibuprofen+aspirin+celecoxib | PASS | PASS | 3 / 6 tools | Excellent |

### Key Observations

1. **Target identification works well for small-to-medium target lists** (combos 1, 2, 4) but fails when lists are very large (combo 3 with 400+ targets total).

2. **AE data coverage is uneven**: Common drugs (aspirin, methotrexate, celecoxib, ibuprofen) have good AE data. Specialty drugs (vorinostat, imatinib, ziprasidone) often have no AE records.

3. **The agent correctly identifies data gaps** and tries alternative retrieval strategies (FAERS signals, label sections, entity claims).

4. **Efficiency is good** when data exists: 2-3 iterations, 4-6 tool calls. When data is missing, the agent exhausts iterations trying alternatives.

### Recommended Improvements

1. **`find_shared_targets(drug_keys)`** - SQL-based set intersection tool to handle large target lists reliably.
2. **`find_shared_adverse_events(drug_keys)`** - Same for AE overlap.
3. **Expand AE data coverage** - Load SIDER side effects for more drugs, expand FAERS signal extraction.
4. **Increase context window** for oncology-scale queries, or chunk target comparison across multiple iterations.
