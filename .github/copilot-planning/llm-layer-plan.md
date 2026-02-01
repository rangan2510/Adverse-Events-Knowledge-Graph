# LLM Orchestration Layer - Implementation Plan

## Overview

The LLM layer uses a **2-phase architecture** that hard-separates planning from narration:

1. **Planner LLM**: Emits validated tool calls only (no prose)
2. **Executor**: Runs tools, builds subgraph, creates evidence pack
3. **Narrator LLM**: Writes executive summary **only from the evidence pack**

This eliminates "LLM answered before tool finished" failures - narration is impossible until the executor returns.

## Architecture

```
User Query
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  PLANNER LLM (Phi-4-mini-instruct)                  │
│  - Emits JSON tool calls only                       │
│  - No prose, no narration                           │
│  - Uses Instructor for schema enforcement           │
└─────────────────────────────────────────────────────┘
    │
    ▼ [Validated ToolPlan]
┌─────────────────────────────────────────────────────┐
│  EXECUTOR (Deterministic Python)                    │
│  - Validates tool calls against allowlist           │
│  - Runs tools (kg_ae.tools)                         │
│  - Builds subgraph, accumulates evidence            │
│  - Produces EvidencePack (IDs + key fields)         │
└─────────────────────────────────────────────────────┘
    │
    ▼ [EvidencePack]
┌─────────────────────────────────────────────────────┐
│  NARRATOR LLM (MediPhi-Instruct)                    │
│  - Medical/clinical fine-tuned                      │
│  - Writes summary ONLY from evidence pack           │
│  - If evidence missing, says so explicitly          │
│  - No tool calls allowed                            │
└─────────────────────────────────────────────────────┘
    │
    ▼
Final Response (Summary + Graph + Evidence)
```

---

## Model Selection

### Planner: Phi-4-mini-instruct (~3.8B)

- Fast instruction following
- Good at structured output
- Small enough to run locally with low latency

**Download (Q4_K_M quant):**
```powershell
mkdir D:\llm\models -Force | Out-Null
cd D:\llm\models

curl.exe -L `
  -o ".\phi4mini.Q4_K_M.gguf" `
  "https://huggingface.co/bartowski/microsoft_Phi-4-mini-instruct-GGUF/resolve/main/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf?download=true"
```

### Narrator: MediPhi-Instruct (~4B)

- Medical/clinical fine-tuned
- Better at pharmacological terminology
- Clean GGUF distribution

**Download (Q4_K_M quant):**
```powershell
curl.exe -L `
  -o ".\mediphi.Q4_K_M.gguf" `
  "https://huggingface.co/tensorblock/microsoft_MediPhi-Instruct-GGUF/resolve/main/MediPhi-Instruct-Q4_K_M.gguf?download=true"
```

### Quantization Guidelines

| Quant | Use Case |
|-------|----------|
| Q4_K_M | Default sweet spot - start here |
| Q5_K_M | If outputs feel "loose" (bad tool plans) |
| Q6_K | Maximum quality, higher VRAM |

---

## Benchmarking

Run `llama-bench` on both models with identical settings:

```powershell
# Verify binaries
where.exe llama-bench
where.exe llama-cli
where.exe llama-server

# Benchmark planner
llama-bench `
  -m "D:\llm\models\phi4mini.Q4_K_M.gguf" `
  -p 16,32,64,96,128,256,512,1024 `
  -n 64,128,256

# Benchmark narrator
llama-bench `
  -m "D:\llm\models\mediphi.Q4_K_M.gguf" `
  -p 16,32,64,96,128,256,512,1024 `
  -n 64,128,256
```

Add `-ngl <N>` for GPU layer offload if available.

**Metrics to record:**
- `tg128`, `tg256` tokens/sec (generation)
- Prompt processing throughput (pp*)

---

## Server Setup

Run **two llama-server instances** (one per role):

```powershell
# Planner server (port 8081)
llama-server -m "D:\llm\models\phi4mini.Q4_K_M.gguf" --port 8081 --host 127.0.0.1

# Narrator server (port 8082)
llama-server -m "D:\llm\models\mediphi.Q4_K_M.gguf" --port 8082 --host 127.0.0.1
```

---

## Components to Build

### 1. Planner Schema (`src/kg_ae/llm/schemas.py`)

Pydantic models for structured planner output.

```python
from enum import Enum
from pydantic import BaseModel, Field

class ToolName(str, Enum):
    RESOLVE_DRUGS = "resolve_drugs"
    RESOLVE_GENES = "resolve_genes"
    RESOLVE_DISEASES = "resolve_diseases"
    RESOLVE_ADVERSE_EVENTS = "resolve_adverse_events"
    GET_DRUG_TARGETS = "get_drug_targets"
    GET_GENE_PATHWAYS = "get_gene_pathways"
    GET_GENE_DISEASES = "get_gene_diseases"
    GET_DISEASE_GENES = "get_disease_genes"
    GET_GENE_INTERACTORS = "get_gene_interactors"
    EXPAND_MECHANISM = "expand_mechanism"
    EXPAND_GENE_CONTEXT = "expand_gene_context"
    GET_DRUG_ADVERSE_EVENTS = "get_drug_adverse_events"
    GET_DRUG_PROFILE = "get_drug_profile"
    GET_DRUG_LABEL_SECTIONS = "get_drug_label_sections"
    GET_DRUG_FAERS_SIGNALS = "get_drug_faers_signals"
    GET_CLAIM_EVIDENCE = "get_claim_evidence"
    GET_ENTITY_CLAIMS = "get_entity_claims"
    FIND_DRUG_TO_AE_PATHS = "find_drug_to_ae_paths"
    EXPLAIN_PATHS = "explain_paths"
    SCORE_PATHS = "score_paths"
    BUILD_SUBGRAPH = "build_subgraph"

class ToolCall(BaseModel):
    """Single tool call with validated arguments."""
    tool: ToolName
    args: dict = Field(default_factory=dict)
    reason: str | None = Field(None, description="Why this tool is needed")

class ToolPlan(BaseModel):
    """Complete execution plan from planner."""
    calls: list[ToolCall] = Field(..., min_length=1)
    stop_conditions: dict = Field(default_factory=dict)
    
class ResolvedEntities(BaseModel):
    """Optional entity resolution results."""
    drugs: dict[str, int | None] = Field(default_factory=dict)
    genes: dict[str, int | None] = Field(default_factory=dict)
    diseases: dict[str, int | None] = Field(default_factory=dict)
    adverse_events: dict[str, int | None] = Field(default_factory=dict)
```

### 2. Evidence Pack (`src/kg_ae/llm/evidence.py`)

Accumulator for executor results.

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class EvidencePack:
    """Evidence accumulated during tool execution."""
    # Resolved entities
    drug_keys: dict[str, int] = field(default_factory=dict)
    gene_keys: dict[str, int] = field(default_factory=dict)
    disease_keys: dict[str, int] = field(default_factory=dict)
    ae_keys: dict[str, int] = field(default_factory=dict)
    
    # Graph data
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    
    # Mechanistic paths
    paths: list[dict] = field(default_factory=list)
    
    # Evidence references
    evidence_ids: list[int] = field(default_factory=list)
    claim_ids: list[int] = field(default_factory=list)
    dataset_ids: list[str] = field(default_factory=list)
    
    # Key statistics
    faers_signals: list[dict] = field(default_factory=list)
    frequencies: list[dict] = field(default_factory=list)
    scores: list[dict] = field(default_factory=list)
    
    # Tool execution log
    tool_results: list[dict] = field(default_factory=list)
    
    def to_narrator_context(self) -> str:
        """Format evidence pack for narrator prompt."""
        # Structured summary for narrator
        ...
```

### 3. LLM Clients (`src/kg_ae/llm/client.py`)

OpenAI-compatible clients for both models.

```python
import instructor
from openai import OpenAI
from pydantic import BaseModel

class PlannerClient:
    """Client for planner LLM (Phi-4-mini)."""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8081/v1"):
        self.client = instructor.from_openai(
            OpenAI(base_url=base_url, api_key="not-needed"),
            mode=instructor.Mode.JSON,
        )
    
    def plan(self, query: str, context: dict | None = None) -> ToolPlan:
        """Generate validated tool plan."""
        return self.client.chat.completions.create(
            model="phi4mini",
            response_model=ToolPlan,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.1,
        )

class NarratorClient:
    """Client for narrator LLM (MediPhi)."""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8082/v1"):
        self.client = OpenAI(base_url=base_url, api_key="not-needed")
    
    def narrate(self, evidence: EvidencePack, query: str) -> str:
        """Generate summary from evidence pack only."""
        response = self.client.chat.completions.create(
            model="mediphi",
            messages=[
                {"role": "system", "content": NARRATOR_SYSTEM_PROMPT},
                {"role": "user", "content": self._format_prompt(evidence, query)},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content
```

### 4. Executor (`src/kg_ae/llm/executor.py`)

Deterministic tool execution engine.

```python
from kg_ae.tools import (
    resolve_drugs, resolve_genes, resolve_diseases, resolve_adverse_events,
    get_drug_targets, get_gene_pathways, get_gene_diseases, get_disease_genes,
    get_gene_interactors, expand_mechanism, expand_gene_context,
    get_drug_adverse_events, get_drug_profile, get_drug_label_sections,
    get_drug_faers_signals, get_claim_evidence, get_entity_claims,
    find_drug_to_ae_paths, explain_paths, score_paths, build_subgraph,
)

class Executor:
    """Executes tool plans and builds evidence pack."""
    
    TOOLS = {
        ToolName.RESOLVE_DRUGS: resolve_drugs,
        ToolName.RESOLVE_GENES: resolve_genes,
        ToolName.RESOLVE_DISEASES: resolve_diseases,
        ToolName.RESOLVE_ADVERSE_EVENTS: resolve_adverse_events,
        ToolName.GET_DRUG_TARGETS: get_drug_targets,
        ToolName.GET_GENE_PATHWAYS: get_gene_pathways,
        ToolName.GET_GENE_DISEASES: get_gene_diseases,
        ToolName.GET_DISEASE_GENES: get_disease_genes,
        ToolName.GET_GENE_INTERACTORS: get_gene_interactors,
        ToolName.EXPAND_MECHANISM: expand_mechanism,
        ToolName.EXPAND_GENE_CONTEXT: expand_gene_context,
        ToolName.GET_DRUG_ADVERSE_EVENTS: get_drug_adverse_events,
        ToolName.GET_DRUG_PROFILE: get_drug_profile,
        ToolName.GET_DRUG_LABEL_SECTIONS: get_drug_label_sections,
        ToolName.GET_DRUG_FAERS_SIGNALS: get_drug_faers_signals,
        ToolName.GET_CLAIM_EVIDENCE: get_claim_evidence,
        ToolName.GET_ENTITY_CLAIMS: get_entity_claims,
        ToolName.FIND_DRUG_TO_AE_PATHS: find_drug_to_ae_paths,
        ToolName.EXPLAIN_PATHS: explain_paths,
        ToolName.SCORE_PATHS: score_paths,
        ToolName.BUILD_SUBGRAPH: build_subgraph,
    }
    
    def execute(self, plan: ToolPlan) -> EvidencePack:
        """Execute tool plan and accumulate evidence."""
        evidence = EvidencePack()
        
        for call in plan.calls:
            # Validate tool exists
            if call.tool not in self.TOOLS:
                raise ValueError(f"Unknown tool: {call.tool}")
            
            # Execute tool
            func = self.TOOLS[call.tool]
            result = func(**call.args)
            
            # Accumulate evidence
            self._accumulate(evidence, call.tool, result)
            
            # Log execution
            evidence.tool_results.append({
                "tool": call.tool.value,
                "args": call.args,
                "result_summary": self._summarize(result),
            })
        
        return evidence
    
    def _accumulate(self, evidence: EvidencePack, tool: ToolName, result) -> None:
        """Add tool result to evidence pack."""
        # Route results to appropriate evidence fields
        ...
    
    def _summarize(self, result) -> dict:
        """Create compact summary of result."""
        ...
```

### 5. Orchestrator (`src/kg_ae/llm/orchestrator.py`)

Main coordination logic.

```python
from dataclasses import dataclass

@dataclass
class Response:
    """Final response with all artifacts."""
    summary: str                    # Narrator output
    subgraph: dict | None           # Graph JSON (nodes/edges)
    paths: list[dict] | None        # Ranked mechanistic paths
    evidence_pack: EvidencePack     # Full evidence
    tool_plan: ToolPlan             # Original plan
    
class Orchestrator:
    """Coordinates planner -> executor -> narrator pipeline."""
    
    def __init__(
        self,
        planner: PlannerClient,
        narrator: NarratorClient,
        executor: Executor,
    ):
        self.planner = planner
        self.narrator = narrator
        self.executor = executor
    
    def run(self, query: str) -> Response:
        """Execute full pipeline."""
        # Phase 1: Plan
        plan = self.planner.plan(query)
        
        # Phase 2: Execute
        evidence = self.executor.execute(plan)
        
        # Phase 3: Narrate
        summary = self.narrator.narrate(evidence, query)
        
        return Response(
            summary=summary,
            subgraph=self._extract_subgraph(evidence),
            paths=evidence.paths,
            evidence_pack=evidence,
            tool_plan=plan,
        )
```

### 6. Prompt Templates (`src/kg_ae/llm/prompts.py`)

```python
PLANNER_SYSTEM_PROMPT = """You are a tool-calling planner for a pharmacovigilance knowledge graph.

Your ONLY job is to output a JSON tool plan. No prose. No explanations.

Available tools:
- resolve_drugs(names: list[str]) - Resolve drug names to database IDs
- resolve_genes(symbols: list[str]) - Resolve gene symbols to database IDs  
- resolve_diseases(terms: list[str]) - Resolve disease terms to database IDs
- resolve_adverse_events(terms: list[str]) - Resolve AE terms to database IDs
- get_drug_targets(drug_key: int) - Get gene targets for a drug
- get_gene_pathways(gene_key: int) - Get pathways for a gene
- get_gene_diseases(gene_key: int, min_score: float) - Get disease associations
- get_disease_genes(disease_key: int, sources: list, min_score: float) - Get genes for disease
- get_gene_interactors(gene_key: int, min_score: float) - Get protein interactions
- expand_mechanism(drug_key: int) - Get full mechanism (targets + pathways)
- get_drug_adverse_events(drug_key: int, min_frequency: float) - Get known AEs
- get_drug_profile(drug_key: int) - Get complete drug profile
- get_drug_label_sections(drug_key: int, sections: list) - Get FDA label sections
- get_drug_faers_signals(drug_key: int, top_k: int, min_prr: float) - Get FAERS signals
- find_drug_to_ae_paths(drug_key: int, ae_key: int) - Find mechanistic paths
- explain_paths(drug_key: int, ae_key: int, condition_keys: list) - Explain paths
- build_subgraph(drug_keys: list[int]) - Build visualization subgraph

Rules:
1. Always start with resolve_* calls for any user-provided names
2. Use resolved keys for subsequent tool calls
3. If uncertain, emit resolve_* calls first
4. Return JSON only - no prose, no explanations
"""

NARRATOR_SYSTEM_PROMPT = """You are a medical writer summarizing pharmacovigilance findings.

You may ONLY use the evidence provided. You CANNOT:
- Invent relationships not in the evidence
- Cite sources not provided
- Make claims without evidence support

If evidence is missing for a claim, say so explicitly and suggest which data would be needed.

Always cite evidence using the provided IDs and reference the data source.

Write in clear, professional medical language suitable for healthcare professionals.
"""
```

---

## Configuration

```python
# src/kg_ae/llm/config.py
from dataclasses import dataclass

@dataclass
class LLMConfig:
    # Planner settings
    planner_url: str = "http://127.0.0.1:8081/v1"
    planner_model: str = "phi4mini"
    planner_temperature: float = 0.1
    
    # Narrator settings
    narrator_url: str = "http://127.0.0.1:8082/v1"
    narrator_model: str = "mediphi"
    narrator_temperature: float = 0.3
    narrator_max_tokens: int = 2048
    
    # Execution limits
    max_tool_calls: int = 20
    tool_timeout: int = 30  # seconds
```

---

## Tool Coverage

All 21 tools from `kg_ae.tools`:

| Category | Tools | Count |
|----------|-------|-------|
| Entity Resolution | resolve_drugs, resolve_genes, resolve_diseases, resolve_adverse_events | 4 |
| Mechanism | get_drug_targets, get_gene_pathways, get_gene_diseases, get_disease_genes, get_gene_interactors, expand_mechanism, expand_gene_context | 7 |
| Adverse Events | get_drug_adverse_events, get_drug_profile, get_drug_label_sections, get_drug_faers_signals | 4 |
| Evidence | get_claim_evidence, get_entity_claims | 2 |
| Paths | find_drug_to_ae_paths, explain_paths, score_paths, score_paths_with_evidence | 4 |
| Subgraph | build_subgraph, score_edges | 2 |

---

## Terminal Output (NetworkX)

For quick inspection, print graph data in terminal:

```python
def print_graph_summary(evidence: EvidencePack):
    """Print graph summary to terminal."""
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    
    # Node counts
    console.print(f"[bold]Nodes:[/bold] Drug={len(evidence.drug_keys)}, "
                  f"Gene={len(evidence.gene_keys)}, "
                  f"Disease={len(evidence.disease_keys)}, "
                  f"AE={len(evidence.ae_keys)}")
    
    # Top edges by score
    table = Table(title="Top Edges (by score)")
    table.add_column("Source")
    table.add_column("Target")
    table.add_column("Type")
    table.add_column("Score")
    
    for edge in sorted(evidence.edges, key=lambda e: e.get("score", 0), reverse=True)[:30]:
        table.add_row(edge["source"], edge["target"], edge["type"], f"{edge.get('score', 0):.3f}")
    
    console.print(table)
    
    # Top paths
    console.print("\n[bold]Top Mechanistic Paths (k=10):[/bold]")
    for i, path in enumerate(evidence.paths[:10], 1):
        path_str = " -> ".join(f"{s['type']}:{s['label']}" for s in path["path"])
        console.print(f"  {i}. {path_str} (score={path['score']:.3f})")
```

---

## Implementation Phases

### Phase 1: Infrastructure (Days 1-3)
- [ ] Download models (phi4mini, mediphi)
- [ ] Run llama-bench, verify performance
- [ ] Start two llama-server instances
- [ ] Implement PlannerClient with Instructor
- [ ] Implement NarratorClient
- [ ] Create Pydantic schemas (ToolPlan, EvidencePack)

**Deliverable:** Can get validated JSON tool plans from planner

### Phase 2: Executor (Days 4-5)
- [ ] Implement Executor with all tool mappings
- [ ] Implement evidence accumulation
- [ ] Add execution logging
- [ ] Test with simple queries

**Deliverable:** Planner -> Executor pipeline works

### Phase 3: Full Pipeline (Days 6-7)
- [ ] Implement Orchestrator
- [ ] Create narrator prompt templates
- [ ] Wire up full pipeline
- [ ] Add terminal output (rich)

**Deliverable:** End-to-end query works

### Phase 4: Testing & Polish (Days 8-10)
- [ ] Benchmark harness (20 fixed queries)
- [ ] Measure: valid plans %, tool calls/query, latency, hallucination rate
- [ ] CLI integration
- [ ] Error handling

**Deliverable:** Production-ready system

---

## Example Workflows

### Workflow 1: Investigate Drug-AE Relationship

```python
from kg_ae.llm import Orchestrator

orchestrator = Orchestrator(...)

response = orchestrator.run(
    "Why does atorvastatin cause myopathy? "
    "Patient has diabetes and takes metformin."
)

# Planner emits:
# {
#   "calls": [
#     {"tool": "resolve_drugs", "args": {"names": ["atorvastatin", "metformin"]}},
#     {"tool": "resolve_adverse_events", "args": {"terms": ["myopathy"]}},
#     {"tool": "resolve_diseases", "args": {"terms": ["diabetes"]}},
#     {"tool": "get_drug_targets", "args": {"drug_key": "$atorvastatin_key"}},
#     {"tool": "find_drug_to_ae_paths", "args": {"drug_key": "$atorvastatin_key", "ae_key": "$myopathy_key"}},
#     {"tool": "get_drug_faers_signals", "args": {"drug_key": "$atorvastatin_key"}}
#   ]
# }

# Executor returns EvidencePack with:
# - Resolved keys
# - Target genes (HMGCR, CYP3A4, ...)
# - Mechanistic paths
# - FAERS signals (PRR, count)

# Narrator writes:
# "Atorvastatin inhibits HMGCR, which may reduce CoQ10 synthesis and impair
#  mitochondrial function in muscle tissue. FAERS data shows PRR=3.2 with
#  1,234 reports of myopathy. The patient's diabetes may increase risk via..."
```

### Workflow 2: Mechanism Exploration

```python
response = orchestrator.run(
    "What genes does imatinib target and what diseases are they associated with?"
)

# Planner emits resolve_drugs -> get_drug_targets -> expand_gene_context
# Narrator summarizes: ABL1 (CML), KIT (GIST), PDGFR (various cancers)
```

### Workflow 3: Comparative Safety

```python
response = orchestrator.run(
    "Compare hepatotoxicity risk between atorvastatin and rosuvastatin"
)

# Planner emits: resolve both drugs, resolve AE, get FAERS signals for both,
#                get label sections (warnings), build comparative subgraph
# Narrator compares: PRR values, report counts, label warnings
```

---

## Quality Guarantees

### What the Planner CAN do:
- Emit validated JSON tool plans
- Select appropriate tools for query type
- Order tools logically (resolve first)

### What the Planner CANNOT do:
- Write prose or explanations
- Access external data
- Skip entity resolution

### What the Narrator CAN do:
- Synthesize evidence into clear summaries
- Cite evidence with IDs
- Identify missing evidence

### What the Narrator CANNOT do:
- Invent relationships not in evidence pack
- Make claims without evidence support
- Call tools or request more data

---

## Testing Strategy

### Benchmark Harness

Run 20 fixed queries and measure:

| Metric | Target |
|--------|--------|
| Valid tool plans | >95% |
| Avg tool calls/query | 5-10 |
| Tokens/sec (planner) | >30 |
| Tokens/sec (narrator) | >20 |
| End-to-end latency | <30s |
| Narrator hallucination rate | <1% |

### Hallucination Detection

```python
def test_no_hallucination():
    """Narrator must not invent edges."""
    response = orchestrator.run("Does aspirin target EGFR?")
    
    # Check evidence pack has no EGFR target
    assert "EGFR" not in [g["symbol"] for g in response.evidence_pack.genes]
    
    # Check narrator acknowledges lack of evidence
    assert "no evidence" in response.summary.lower() or "not found" in response.summary.lower()
```

---

## Dependencies

```toml
# pyproject.toml additions
[project.dependencies]
openai = ">=1.0.0"
instructor = ">=1.0.0"
pydantic = ">=2.0"
httpx = ">=0.25.0"
rich = ">=13.0.0"
networkx = ">=3.0"
```

---

## Next Steps

1. **Download models** (PowerShell commands above)
2. **Run llama-bench** on both models
3. **Start llama-server instances** (ports 8081, 8082)
4. **Implement PlannerClient** with Instructor
5. **Test first tool plan** generation

Ready to start?
