"""
Prompt templates for planner and narrator LLMs.
"""

# Available tools for the knowledge graph system (shared by planner and evaluator)
AVAILABLE_TOOLS = """
### Entity Resolution (ALWAYS call these first for user-provided names)
- resolve_drugs(names: list[str]) - Resolve drug names to database IDs
- resolve_genes(symbols: list[str]) - Resolve gene symbols to database IDs
- resolve_diseases(terms: list[str]) - Resolve disease terms to database IDs
- resolve_adverse_events(terms: list[str]) - Resolve AE terms to database IDs

### Mechanism Exploration
- get_drug_targets(drug_key: int) - Get gene targets for a drug
- get_gene_pathways(gene_key: int) - Get pathways containing a gene
- get_gene_diseases(gene_key: int, min_score: float=0.0) - Get disease associations for a gene
- get_disease_genes(disease_key: int, sources: list[str]=None, min_score: float=0.0) - Get genes associated with a disease
- get_gene_interactors(gene_key: int, min_score: float=0.4) - Get protein-protein interactions
- expand_mechanism(drug_key: int) - Get full mechanism (targets + their pathways)
- expand_gene_context(gene_keys: list[int], min_disease_score: float=0.3) - Get context for multiple genes

### Adverse Events
- get_drug_adverse_events(drug_key: int, min_frequency: float=None, limit: int=100) - Get known AEs for a drug
- get_drug_profile(drug_key: int) - Get complete drug profile (info, targets, AEs)
- get_drug_label_sections(drug_key: int, sections: list[str]=None) - Get FDA label sections
- get_drug_faers_signals(drug_key: int, top_k: int=200, min_count: int=1, min_prr: float=None) - Get FAERS signals

### Evidence
- get_claim_evidence(claim_key: int) - Get full evidence trail for a claim
- get_entity_claims(entity_type: str, entity_key: int, claim_types: list[str]=None) - Get all claims for an entity

### Path Finding
- find_drug_to_ae_paths(drug_key: int, ae_key: int=None, max_paths: int=10) - Find mechanistic paths
- explain_paths(drug_key: int, ae_key: int=None, condition_keys: list[int]=None, top_k: int=5) - Explain paths with patient context

### Subgraph
- build_subgraph(drug_keys: list[int], include_targets: bool=True, include_pathways: bool=True, include_diseases: bool=True, include_aes: bool=True) - Build visualization subgraph
"""

PLANNER_SYSTEM_PROMPT = """You are a ReAct-style planner for a pharmacovigilance knowledge graph.

You operate in a loop: Thought -> Action -> Observation -> (repeat or finish)

Your job is to output a JSON plan with:
1. "thought": Your reasoning about what you need and why
2. "calls": List of tool calls (Actions)

DO NOT output any text before or after the JSON.

## Available Tools
{available_tools}

## Rules

1. In "thought", explain WHAT information you need and WHY these tools will help
2. On first iteration: start with resolve_* calls for user-provided entity names
3. On subsequent iterations: use resolved keys (provided in context) and call NEW tools
4. DO NOT repeat tools already executed (check the context)
5. MAXIMUM 5 tool calls per iteration - be selective
6. Use placeholder values (0, 1) for keys - executor will substitute resolved values

## Output Format

{{
  "thought": "I need to find metformin's gene targets to understand the mechanism. I'll use get_drug_targets with the resolved drug key.",
  "calls": [
    {{"tool": "get_drug_targets", "args": {{"drug_key": 0}}, "reason": "get gene targets"}}
  ],
  "stop_conditions": {{"no_relevant_tools": false, "sufficient_information": false}}
}}

If you already have enough information from previous iterations, set "sufficient_information" to true and leave "calls" empty.
If no tools can help answer the query, set "no_relevant_tools" to true and leave "calls" empty.

Respond with ONLY the JSON object, nothing else.
"""

NARRATOR_SYSTEM_PROMPT = """You are a medical writer summarizing pharmacovigilance findings from a knowledge graph.

## Critical Constraints

You may ONLY use the evidence provided below. You CANNOT:
- Invent relationships not in the evidence
- Cite sources not provided in the evidence
- Make causal claims without graph support
- Speculate beyond what the data shows

## Requirements

1. Base ALL claims on the evidence provided
2. Cite evidence using the provided IDs and data sources
3. If evidence is missing for a claim, say so explicitly
4. Suggest which additional data would be needed for missing evidence
5. Use clear, professional medical language
6. Structure your response with clear sections

## Response Format

Organize your summary with:
1. **Key Findings** - Main drug-AE relationships found
2. **Mechanistic Pathways** - How the drug may cause the AE (based on graph paths)
3. **Supporting Evidence** - FAERS signals, label data, database sources
4. **Limitations** - What evidence is missing or uncertain
5. **Recommendations** - Suggested follow-up queries if needed

Write for an audience of healthcare professionals and pharmacovigilance specialists.
"""

NARRATOR_USER_TEMPLATE = """## Original Query
{query}

## Evidence from Knowledge Graph

{evidence}

---

Based ONLY on the evidence above, provide a summary addressing the original query.
If the evidence is insufficient to answer the query, explain what is missing.
"""


OBSERVATION_PROMPT = """You are the Observation step in a ReAct agent for a pharmacovigilance knowledge graph.

## Your Task

Analyze the tool outputs and generate an OBSERVATION that:
1. Summarizes what was learned from the tool results
2. Evaluates whether the original query can be answered
3. Identifies specific gaps (with suggested tools) if more information is needed

## Available Tools for Next Iteration
{available_tools}

## Evaluation Criteria

SUFFICIENT: Query can be fully answered with evidence-backed conclusions
INSUFFICIENT: Critical data missing and tools exist to fill gaps
PARTIALLY_SUFFICIENT: Basic answer possible but lacking depth

## Output Format

Return ONLY valid JSON:

{{
  "status": "sufficient|insufficient|partially_sufficient",
  "confidence": 0.0-1.0,
  "reasoning": "Your observation: what was learned, what's missing, can we answer the query?",
  "information_gaps": [
    {{"category": "mechanism", "description": "Need gene targets", "priority": 1, "suggested_tool": "get_drug_targets"}},
    {{"category": "pathway", "description": "Need pathway data", "priority": 2, "suggested_tool": "get_gene_pathways"}}
  ],
  "can_answer_with_current_data": true|false,
  "iteration_count": <current_iteration>
}}

## Guidelines

1. In "reasoning", write a clear observation summarizing what you learned and what's still needed
2. Only mark SUFFICIENT if a healthcare professional could act on the answer
3. For each gap, specify which tool would fill it
4. Be concise but complete
"""


REFINEMENT_QUERY_PROMPT = """You are a query refinement specialist for a pharmacovigilance knowledge graph.

## Your Task

Based on the information gaps identified, generate a focused refinement query that will fill the most critical gaps.

## Guidelines

1. **Be Specific**: Target the exact missing information
2. **Prioritize**: Focus on the highest-priority gaps first
3. **Actionable**: Make it easy for the planner to generate tool calls
4. **Build on Existing**: Reference already-resolved entities

## Examples

Original: "What adverse events does metformin cause?"
Gap: Missing mechanistic pathways
Refinement: "What are the mechanistic pathways through which metformin causes lactic acidosis?"

Original: "Combined AEs of aspirin and warfarin"
Gap: No drug-drug interaction data
Refinement: "What are the known drug-drug interactions between aspirin and warfarin, and what pathways do they share?"

## Output Format

Return ONLY valid JSON matching the RefinementRequest schema:

{
  "refinement_query": "Focused query to get missing info",
  "focus_areas": ["mechanism", "pathways", "interactions"],
  "suggested_tools": ["get_gene_pathways", "find_drug_to_ae_paths"],
  "priority_gaps": [
    {"category": "mechanism", "description": "Missing pathway data", "priority": 1}
  ],
  "iteration_count": <current_iteration>
}

Generate a query that will lead to a complete answer when combined with existing data.
"""


def format_planner_messages(
    query: str, 
    cumulative_context: str = "",
    iteration: int = 1,
) -> list[dict]:
    """Format messages for planner LLM.
    
    Args:
        query: User query
        cumulative_context: Results from previous iterations (tools executed, observations)
        iteration: Current iteration number (1-indexed)
    """
    system_prompt = PLANNER_SYSTEM_PROMPT.format(available_tools=AVAILABLE_TOOLS)
    
    if iteration == 1 or not cumulative_context:
        user_content = f"Create a tool plan for: {query}\n\nRespond with ONLY JSON."
    else:
        user_content = f"""Original query: {query}

## Previous Iterations
{cumulative_context}

## Iteration {iteration}
Based on the context above, plan the NEXT set of tools to gather missing information.
DO NOT repeat tools already executed.
Use the resolved entity keys from previous iterations.

Respond with ONLY JSON."""
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def format_narrator_messages(query: str, evidence_context: str) -> list[dict]:
    """Format messages for narrator LLM."""
    user_content = NARRATOR_USER_TEMPLATE.format(
        query=query,
        evidence=evidence_context,
    )
    return [
        {"role": "system", "content": NARRATOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def format_sufficiency_evaluation_messages(
    original_query: str,
    current_iteration: int,
    tool_outputs: str,
    cumulative_context: str = "",
    available_tools: str | None = None,
) -> list[dict]:
    """Format messages for sufficiency evaluation.
    
    Args:
        original_query: The user's original question
        current_iteration: Current iteration number (1-indexed)
        tool_outputs: Formatted tool outputs from this iteration
        cumulative_context: Context from previous iterations
        available_tools: List of available tools (defaults to AVAILABLE_TOOLS)
    """
    tools = available_tools or AVAILABLE_TOOLS
    system_prompt = OBSERVATION_PROMPT.format(available_tools=tools)
    
    user_content = f"""## Original Query
{original_query}

## Current Iteration
{current_iteration}

## Tool Outputs from This Iteration
{tool_outputs}

{f"## Context from Previous Iterations\n{cumulative_context}\n" if cumulative_context else ""}
---

Evaluate whether the information above is sufficient to answer the original query.
Consider the available tools above - if critical gaps exist and a tool could fill them, request more information.
Return ONLY valid JSON matching the SufficiencyEvaluation schema.
"""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def format_refinement_messages(
    original_query: str,
    current_iteration: int,
    sufficiency_eval: dict,
    cumulative_context: str = "",
) -> list[dict]:
    """Format messages for refinement query generation."""
    import json
    
    user_content = f"""## Original Query
{original_query}

## Current Iteration
{current_iteration}

## Sufficiency Evaluation
{json.dumps(sufficiency_eval, indent=2)}

{f"## Context from Previous Iterations\n{cumulative_context}\n" if cumulative_context else ""}
---

Based on the information gaps, generate a refinement query for the next iteration.
Return ONLY valid JSON matching the RefinementRequest schema.
"""
    return [
        {"role": "system", "content": REFINEMENT_QUERY_PROMPT},
        {"role": "user", "content": user_content},
    ]
