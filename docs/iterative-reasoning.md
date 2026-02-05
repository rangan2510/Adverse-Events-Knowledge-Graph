# Iterative Reasoning System

## Overview

The system provides two iterative reasoning implementations:

| Implementation | Script | LLM Architecture | Context Strategy |
|---------------|--------|------------------|------------------|
| **ReAct** (recommended) | `query_react.py` | Single LLM | Rolling trace summary |
| **Two-Phase** | `query_iterative.py` | Planner + Narrator | Full trace accumulation |

---

## ReAct Orchestrator (Recommended)

The ReAct (Reasoning + Acting) orchestrator uses a single LLM for all reasoning steps with efficient context management.

### Architecture

```
Query
  |
  v
[THOUGHT] -----> LLM reasons about information needs
  |
  v
[ACTION] ------> LLM emits tool calls with reasons
  |
  v
[EXECUTE] -----> Tools run, outputs TRUNCATED (max 30 items)
  |
  v
[OBSERVATION] -> LLM evaluates sufficiency (low/medium/high)
  |
  +--- Insufficient --> Loop with ROLLING SUMMARY (not full trace)
  |
  +--- Sufficient ----> FINAL RESPONSE
```

### Key Design Decisions

1. **Single LLM**: Both planning and observation use the same model (e.g., llama-3.3-70b-versatile)
2. **Rolling Trace Summary**: Only keeps a compact summary of previous iterations, not full tool outputs
3. **Output Truncation**: Tool results capped at 30 items to prevent context overflow
4. **Priority Field Formatting**: Shows `ae_label` before `ae_key` for better LLM comprehension

### Usage

```bash
# Basic query
uv run python scripts/query_react.py "What adverse events are shared by cyclosporine and tacrolimus?"

# With iteration limit
uv run python scripts/query_react.py --max-iterations 5 "Your query here"

# Interactive mode
uv run python scripts/query_react.py --interactive
```

### Pydantic Schemas

```python
from kg_ae.llm import ReActStep, ReActContext, FinalResponse, Confidence

# Each iteration produces a ReActStep
class ReActStep(BaseModel):
    thought: str           # Reasoning about current state
    tool_calls: list[ToolCallRequest]  # Tools to execute
    observation: str       # What was learned
    confidence: Confidence # low | medium | high
    missing_info: list[str]
    trace_summary: str     # Compact summary for next iteration
    is_complete: bool

# Context maintained across iterations
class ReActContext(BaseModel):
    original_query: str
    trace_summary: str     # Rolling summary (not full trace)
    iteration: int
    max_iterations: int
    resolved_drugs: dict[str, int]   # Persisted across iterations
    resolved_genes: dict[str, int]
    last_tool_results: list[ToolResult]

# Final response structure
class FinalResponse(BaseModel):
    summary: str
    findings: list[str]
    evidence_summary: str
    limitations: list[str]
    confidence: Confidence
```

### Python API

```python
from kg_ae.llm import LLMConfig, ReActOrchestrator

config = LLMConfig()  # Reads from .env
orchestrator = ReActOrchestrator(config, max_iterations=10, verbose=True)

context, final_response = orchestrator.query(
    "What adverse events are shared by cyclosporine and tacrolimus?"
)

print(final_response)  # Markdown-formatted response
print(context.iteration)  # Number of iterations used
```

### Module Structure

```
src/kg_ae/llm/
  react_schemas.py      # ReActStep, ReActContext, FinalResponse, Confidence
  react_prompts.py      # System prompts, tool catalog, message formatting
  react_executor.py     # Tool execution with truncation
  react_orchestrator.py # Main ReAct loop
```

---

## Two-Phase Orchestrator (Legacy)

The two-phase system uses separate Planner and Narrator LLMs with full trace accumulation.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Iterative Query Loop                      │
│                                                              │
│  ┌────────┐                                                 │
│  │ Query  │                                                 │
│  └───┬────┘                                                 │
│      │                                                      │
│      ▼                                                      │
│  ┌────────────────┐     ┌──────────────┐                   │
│  │ Planner LLM    │────▶│ Tool Execute │                   │
│  │ (Phi-4-mini)   │     │              │                   │
│  └────────────────┘     └──────┬───────┘                   │
│                                 │                           │
│                                 ▼                           │
│                         ┌───────────────┐                   │
│                         │ Tool Outputs  │                   │
│                         └───────┬───────┘                   │
│                                 │                           │
│                                 ▼                           │
│                    ┌────────────────────────┐               │
│                    │ Narrator LLM           │               │
│                    │ Sufficiency Evaluation │               │
│                    └────────┬───────────────┘               │
│                             │                               │
│                    ┌────────┴────────┐                      │
│                    │                 │                      │
│              ┌─────▼─────┐    ┌─────▼──────┐               │
│              │ Sufficient │    │Insufficient│               │
│              └─────┬──────┘    └─────┬──────┘               │
│                    │                 │                      │
│                    │           ┌─────▼──────────┐           │
│                    │           │ Refinement     │           │
│                    │           │ Request        │           │
│                    │           └─────┬──────────┘           │
│                    │                 │                      │
│                    │                 ▼                      │
│                    │           [Loop back to Planner]       │
│                    │           [Increment iteration]        │
│                    │                                        │
│                    ▼                                        │
│            ┌────────────────┐                               │
│            │ Final Response │                               │
│            └────────────────┘                               │
└─────────────────────────────────────────────────────────────┘
```

## Flow Stages

### 1. Initial Planning
- User submits query
- Planner LLM generates tool plan
- Tools execute and return results

### 2. Sufficiency Evaluation
Narrator LLM evaluates whether tool outputs provide sufficient information.

**Key feature**: The evaluator receives the **list of available tools** so it can make informed decisions about what additional information could be gathered. For each information gap, it suggests which specific tool would fill that gap.

- **SUFFICIENT**: Information is complete, generate final answer
- **INSUFFICIENT**: Critical gaps exist AND tools exist to fill them
- **PARTIALLY_SUFFICIENT**: Basic answer possible but tools could provide more depth

Evaluation considers:
- Can the query be answered meaningfully?
- Are mechanistic pathways present (if relevant)?
- Is adverse event data available (if relevant)?
- Is critical context missing?
- **Which available tools could fill each gap?**

### 3. Decision Point

#### If Sufficient:
- Generate final narrative response
- End iteration loop
- Mark completion reason: `"sufficient"`

#### If Insufficient:
- Generate refinement query
- List information gaps by priority
- Suggest focus areas
- Loop back to step 1 with refined query
- Increment iteration counter

#### If Max Iterations Reached:
- Force final response with available data
- Mark completion reason: `"max_iterations"`
- Note limitations in response

## Pydantic Models

### InformationGap
```python
class InformationGap(BaseModel):
    category: str          # e.g., "mechanism", "pathway", "interaction"
    description: str       # What information is missing
    priority: int          # 1=high, 2=medium, 3=low
    suggested_tool: str | None  # Tool that could fill this gap
```

### SufficiencyEvaluation
```python
class SufficiencyEvaluation(BaseModel):
    status: SufficiencyStatus  # sufficient|insufficient|partially_sufficient
    confidence: float  # 0.0-1.0
    reasoning: str
    information_gaps: list[InformationGap]  # Each gap includes suggested_tool
    can_answer_with_current_data: bool
    iteration_count: int
```

### RefinementRequest
```python
class RefinementRequest(BaseModel):
    refinement_query: str  # New query for next iteration
    focus_areas: list[str]  # e.g., ["mechanism", "pathways"]
    suggested_tools: list[str]  # Optional tool hints
    priority_gaps: list[InformationGap]  # Ordered by priority
    iteration_count: int
```

### IterativeContext
```python
class IterativeContext(BaseModel):
    original_query: str
    current_iteration: int
    max_iterations: int
    iterations: list[IterationRecord]
    final_response: str | None
    is_complete: bool
    completion_reason: str | None  # sufficient|max_iterations|error
```

### IterationRecord
```python
class IterationRecord(BaseModel):
    iteration_number: int
    query: str
    tool_executions: list[ToolExecutionRecord]
    sufficiency_evaluation: SufficiencyEvaluation | None
    refinement_request: RefinementRequest | None
    timestamp_start: float
    timestamp_end: float | None
```

## Usage

### Basic Usage
```python
from kg_ae.llm import (
    PlannerClient,
    NarratorClient,
    IterativeOrchestrator,
)

# Initialize
planner = PlannerClient()
narrator = NarratorClient()
orchestrator = IterativeOrchestrator(
    planner_client=planner,
    narrator_client=narrator,
    max_iterations=3,
)

# Run query
context = orchestrator.query(
    query="What adverse events might metformin cause?",
    tool_executor_fn=your_tool_executor,
)

# Access results
print(context.final_response)
print(f"Iterations: {len(context.iterations)}")
print(f"Completion: {context.completion_reason}")
```

### Command Line
```bash
# Single query with default 3 iterations
uv run python scripts/query_iterative.py "What are the combined AEs of aspirin and warfarin?"

# Set max iterations
uv run python scripts/query_iterative.py --max-iterations 5 "Complex query"

# Interactive mode
uv run python scripts/query_iterative.py --interactive

# Quiet mode (only final answer)
uv run python scripts/query_iterative.py --quiet "Query text"
```

### Interactive Commands
```
Query> What adverse events does metformin cause?
[... iterative processing ...]

Query> set-max 5
✓ Max iterations set to 5

Query> quit
```

## Example Scenario

### Iteration 1
**Query**: "What adverse events might metformin cause?"

**Tools Executed**:
- `resolve_drugs(["metformin"])` → drug_key=14042
- `get_drug_adverse_events(14042)` → 84 AEs found

**Sufficiency Evaluation**:
- Status: `PARTIALLY_SUFFICIENT`
- Reasoning: "AE data available but no mechanistic explanation"
- Gaps:
  ```json
  [
    {"category": "mechanism", "description": "No pathway data for AE causation", "priority": 1, "suggested_tool": "get_drug_targets"},
    {"category": "pathway", "description": "Missing gene-pathway relationships", "priority": 2, "suggested_tool": "get_gene_pathways"}
  ]
  ```
- Can answer: `false`

**Refinement**: "What are the mechanistic pathways through which metformin causes lactic acidosis?"

### Iteration 2
**Query**: "What are the mechanistic pathways through which metformin causes lactic acidosis?"

**Tools Executed**:
- `get_drug_targets(14042)` → 5 targets
- `get_gene_pathways(gene_keys)` → 12 pathways
- `find_drug_to_ae_paths(14042, ae_key=xxx)` → 3 paths

**Sufficiency Evaluation**:
- Status: `SUFFICIENT`
- Reasoning: "Complete pathway data + AE associations present"
- Gaps: `[]` (no gaps - all requested info retrieved)
- Can answer: `true`

**Final Response**: [Comprehensive answer with mechanistic detail]

## Configuration

### Max Iterations
Default: `3`
Range: `1-10`

**Guidelines**:
- Simple AE queries: 1-2 iterations
- Mechanism exploration: 2-3 iterations
- Complex drug interactions: 3-5 iterations
- Research questions: 5-10 iterations

### Temperature Settings
```python
# config.py
planner_temperature = 0.1  # Deterministic planning
narrator_temperature = 0.3  # Slightly creative narration
```

### Token Limits
```python
planner_max_tokens = 512    # Structured output (keep short)
narrator_max_tokens = 2048  # Long-form response
```

## Integration with Existing Pipeline

The iterative orchestrator is designed to wrap the existing `query_kg.py` tool execution logic:

```python
# In query_iterative.py
def execute_tools_for_query(query: str):
    """Bridge to existing tool executor."""
    # Call existing QueryContext and tool execution
    # Return list of ToolResult objects
    from query_kg import execute_query_plan
    return execute_query_plan(query)
```

## Prompts

### Sufficiency Evaluator Prompt
- Evaluates information completeness
- Conservative: only marks SUFFICIENT if actionable
- Identifies specific gaps by category
- Assigns priorities (1=high, 2=medium, 3=low)

### Refinement Query Prompt
- Generates focused refinement query
- Targets highest-priority gaps
- References already-resolved entities
- Suggests specific tool focus areas

## Output Examples

### Terminal Output
```
Query
Query: What adverse events might metformin cause?
Max iterations: 3

--- Iteration 1/3 ---
Planning tools for: What adverse events might metformin cause?
✓ Executed 2 tool(s)

Sufficiency Evaluation
| Status   | partially_sufficient               |
| Confid.  | 0.65                               |
| Can Ans. | ✗                                  |
| Gaps     | mechanism (P1)                     |

Iteration 1 -> 2
Refinement Query: What are the mechanistic pathways...
Focus Areas: mechanism, pathways
Priority Gaps: 1 gap(s)

--- Iteration 2/3 ---
[... continues ...]
```

### JSON Context Export
```json
{
  "original_query": "What AEs does metformin cause?",
  "current_iteration": 2,
  "max_iterations": 3,
  "is_complete": true,
  "completion_reason": "sufficient",
  "iterations": [
    {
      "iteration_number": 1,
      "query": "What AEs does metformin cause?",
      "tool_executions": [...],
      "sufficiency_evaluation": {...},
      "refinement_request": {...}
    },
    {
      "iteration_number": 2,
      "query": "Mechanistic pathways for metformin lactic acidosis",
      "tool_executions": [...],
      "sufficiency_evaluation": {...}
    }
  ],
  "final_response": "..."
}
```

## Best Practices

### 1. Start Conservative
- Begin with max_iterations=3
- Let the system determine if more is needed
- Avoid over-iteration on simple queries

### 2. Monitor Iteration Patterns
- If consistently hitting max iterations → increase limit
- If stopping at 1 iteration → queries may be too narrow

### 3. Review Refinement Quality
- Good refinements are specific and actionable
- Poor refinements repeat the original query
- Adjust prompts if refinements are too vague

### 4. Handle Edge Cases
- Empty tool results → mark INSUFFICIENT immediately
- Tool errors → consider as missing information
- Circular refinements → detect and break loop

### 5. Performance Optimization
- Cache resolved entities across iterations
- Reuse pathway/mechanism data when possible
- Don't re-fetch identical tool calls

## Debugging

### Verbose Mode
```python
orchestrator = IterativeOrchestrator(verbose=True)
```
Shows:
- Tool execution progress
- Sufficiency evaluation details
- Refinement request content
- Iteration timing

### Context Inspection
```python
# After query completion
print(f"Iterations: {len(context.iterations)}")
print(f"Total tools: {len(context.get_all_tool_executions())}")
print(context.get_cumulative_context())  # Full history

# Per-iteration details
for iteration in context.iterations:
    print(f"Iteration {iteration.iteration_number}")
    print(f"  Tools: {len(iteration.tool_executions)}")
    print(f"  Sufficient: {iteration.sufficiency_evaluation.can_answer_with_current_data}")
```

## Future Enhancements

1. **Adaptive Max Iterations**: Dynamically adjust based on query complexity
2. **Parallel Tool Execution**: Run independent tools concurrently in each iteration
3. **Caching Layer**: Store and reuse tool results across queries
4. **Confidence Thresholding**: Only continue if sufficiency confidence > threshold
5. **Tool Cost Tracking**: Monitor API calls and token usage per iteration
6. **Feedback Loop**: Learn which refinements lead to successful completions
