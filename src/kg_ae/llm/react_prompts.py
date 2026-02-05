"""
Prompts for ReAct-style iterative reasoning.

Single LLM handles: Thought -> Action -> Observation -> (loop or finish)
"""

TOOL_CATALOG = """
## Available Tools

### Entity Resolution (ALWAYS call first for user-provided names)
- resolve_drugs(names: list[str]) -> dict[name, {key, name, confidence}]
  Resolve drug names to database keys. Returns None for unresolved names.

- resolve_genes(symbols: list[str]) -> dict[symbol, {key, symbol, confidence}]
  Resolve gene symbols to database keys.

- resolve_diseases(terms: list[str]) -> dict[term, {key, name, confidence}]
  Resolve disease terms to database keys.

- resolve_adverse_events(terms: list[str]) -> dict[term, {key, label, confidence}]
  Resolve adverse event terms to database keys.

### Adverse Events
- get_drug_adverse_events(drug_key: int, limit: int=50) -> list[{ae_key, ae_label, frequency, relation}]
  Get known adverse events for a drug from SIDER/labels. Returns top AEs by frequency.

- get_drug_faers_signals(drug_key: int, top_k: int=50) -> list[{ae_label, count, prr, ror}]
  Get FAERS pharmacovigilance signals. PRR/ROR indicate disproportionality.

- get_drug_profile(drug_key: int) -> {drug_info, targets[], adverse_events[]}
  Complete drug profile with targets and top AEs.

### Mechanism
- get_drug_targets(drug_key: int) -> list[{gene_key, gene_symbol, action, source}]
  Get gene/protein targets for a drug.

- get_gene_pathways(gene_key: int) -> list[{pathway_key, name, reactome_id}]
  Get pathways containing a gene.

- get_gene_diseases(gene_key: int, min_score: float=0.0) -> list[{disease_key, name, score}]
  Get disease associations for a gene.

- expand_mechanism(drug_key: int) -> {targets[], pathways[], diseases[]}
  Full mechanism expansion: drug -> targets -> pathways -> diseases.

### Paths
- find_drug_to_ae_paths(drug_key: int, ae_key: int=None, max_paths: int=5)
  Find mechanistic paths from drug to adverse event through gene/pathway/disease nodes.

### Evidence
- get_claim_evidence(claim_key: int) -> {claim_info, evidence_records[]}
  Get full evidence trail for a specific claim.
"""

REACT_SYSTEM_PROMPT = """You are a ReAct agent for pharmacovigilance knowledge graph queries.

You operate in a loop: THOUGHT -> ACTION -> OBSERVATION -> (repeat or answer)

{tool_catalog}

## Output Format

Return ONLY valid JSON matching this schema:

{{
  "thought": "Reasoning about what we know and what we need...",
  "tool_calls": [
    {{"tool": "tool_name", "args": {{"arg": "value"}}, "reason": "why this call"}}
  ],
  "observation": "Summary of what was learned from tool results...",
  "confidence": "low|medium|high",
  "missing_info": ["specific info still needed"],
  "trace_summary": "Compact summary of ALL steps taken so far...",
  "is_complete": false
}}

## Rules

1. FIRST ITERATION: Always start with resolve_* to convert names to keys
2. Use resolved keys (integers) for subsequent tool calls
3. MAXIMUM 4 tool calls per iteration
4. In trace_summary: summarize what tools were called and key findings (NOT full data)
5. Set is_complete=true when confidence is HIGH and tool_calls is empty
6. Tool outputs are truncated - if you need more specific data, call with different filters

## Confidence Levels

- LOW: Missing critical information, more tools needed
- MEDIUM: Have some data but gaps remain, can attempt partial answer
- HIGH: Have sufficient evidence to fully answer the query

## When to Stop

Set is_complete=true and tool_calls=[] when:
- confidence is HIGH, OR
- You've tried available tools and have best possible answer, OR
- Max iterations reached (make best effort with available data)
"""

REACT_USER_FIRST = """Query: {query}

This is iteration 1. Start by resolving any drug/gene/disease names in the query.
Return ONLY JSON."""

REACT_USER_CONTINUE = """Query: {query}

## Iteration {iteration}

## Previous Trace Summary
{trace_summary}

## Tool Results from Last Iteration
{tool_results}

## Resolved Entities
{resolved_entities}

Based on the above, determine next steps. If you have enough info, set is_complete=true.
Return ONLY JSON."""


FINAL_RESPONSE_SYSTEM = """You are a medical writer summarizing pharmacovigilance findings.

Based on the ReAct trace and gathered evidence, generate a final response.

## Constraints
- ONLY use information from the provided evidence
- Do NOT invent relationships not in the data
- Clearly state limitations and gaps
- Use professional medical language

## Output Format

Return ONLY valid JSON:

{{
  "summary": "Executive summary answering the query...",
  "findings": ["Key finding 1", "Key finding 2", ...],
  "evidence_summary": "Summary of sources and evidence quality...",
  "limitations": ["Limitation 1", "Limitation 2"],
  "confidence": "low|medium|high"
}}
"""

FINAL_RESPONSE_USER = """## Original Query
{query}

## Complete Trace Summary
{trace_summary}

## Final Observation
{final_observation}

## Key Data Gathered
{gathered_data}

Generate the final response based ONLY on the evidence above.
Return ONLY JSON."""


def format_react_messages(
    query: str,
    iteration: int = 1,
    trace_summary: str = "",
    tool_results: str = "",
    resolved_entities: str = "",
) -> list[dict]:
    """Format messages for ReAct iteration."""
    
    system = REACT_SYSTEM_PROMPT.format(tool_catalog=TOOL_CATALOG)
    
    if iteration == 1:
        user = REACT_USER_FIRST.format(query=query)
    else:
        user = REACT_USER_CONTINUE.format(
            query=query,
            iteration=iteration,
            trace_summary=trace_summary or "(No previous trace)",
            tool_results=tool_results or "(No tool results yet)",
            resolved_entities=resolved_entities or "(No entities resolved yet)",
        )
    
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def format_final_response_messages(
    query: str,
    trace_summary: str,
    final_observation: str,
    gathered_data: str,
) -> list[dict]:
    """Format messages for final response generation."""
    
    user = FINAL_RESPONSE_USER.format(
        query=query,
        trace_summary=trace_summary,
        final_observation=final_observation,
        gathered_data=gathered_data,
    )
    
    return [
        {"role": "system", "content": FINAL_RESPONSE_SYSTEM},
        {"role": "user", "content": user},
    ]
