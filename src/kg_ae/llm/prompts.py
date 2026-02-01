"""
Prompt templates for planner and narrator LLMs.
"""

PLANNER_SYSTEM_PROMPT = """You are a tool-calling planner for a pharmacovigilance knowledge graph.

Your ONLY job is to output a JSON tool plan.
DO NOT output any text before or after the JSON.
DO NOT explain your reasoning.
ONLY output valid JSON matching the schema below.

## Available Tools

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

## Rules

1. ALWAYS start with resolve_* calls for any user-provided entity names
2. Use the resolved keys (integers) for all subsequent tool calls
3. If uncertain which entities to resolve, emit resolve_* calls first
4. Order calls logically: resolve -> query -> expand -> paths
5. Return ONLY valid JSON matching the ToolPlan schema
6. NO prose, NO explanations, NO markdown - just JSON
7. MAXIMUM 5 tool calls total - be selective, not exhaustive
8. For adverse events queries: resolve_drugs + get_drug_adverse_events is usually sufficient

## Output Format

{
  "calls": [
    {"tool": "resolve_drugs", "args": {"names": ["aspirin"]}, "reason": "resolve drug name"},
    {"tool": "get_drug_targets", "args": {"drug_key": 123}, "reason": "get targets"}
  ],
  "stop_conditions": {}
}

Note: For drug_key, gene_key, etc. - use placeholder values like 0 or 1. The executor will substitute actual resolved keys.

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


SUFFICIENCY_EVALUATOR_PROMPT = """You are an information sufficiency evaluator for a pharmacovigilance knowledge graph query system.

## Your Task

Evaluate whether the current tool outputs provide SUFFICIENT information to answer the user's query.

## Evaluation Criteria

Consider information SUFFICIENT if:
1. The query can be answered with meaningful, evidence-backed conclusions
2. Key mechanistic relationships are present (if relevant)
3. Primary adverse event data is available (if relevant)
4. Critical context exists to make the answer useful

Consider information INSUFFICIENT if:
1. Critical data is missing (e.g., no AE data for a drug-AE query)
2. Mechanistic pathways are completely unknown
3. The answer would be too speculative without more evidence
4. Important context is missing (e.g., patient conditions not explored)

Consider information PARTIALLY_SUFFICIENT if:
1. Basic answer is possible but missing depth
2. Some pathways known but others unexplored
3. AE data exists but mechanism unclear

## Output Format

Return ONLY valid JSON matching the SufficiencyEvaluation schema:

{
  "status": "sufficient|insufficient|partially_sufficient",
  "confidence": 0.0-1.0,
  "reasoning": "Explain your evaluation",
  "information_gaps": [
    {"category": "mechanism", "description": "Missing pathway data", "priority": 1},
    {"category": "adverse_events", "description": "No FAERS signals", "priority": 2}
  ],
  "can_answer_with_current_data": true|false,
  "iteration_count": <current_iteration>
}

Be conservative: only mark as SUFFICIENT if a healthcare professional would find the answer actionable.
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


def format_planner_messages(query: str) -> list[dict]:
    """Format messages for planner LLM."""
    return [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": f"Create a tool plan for: {query}\n\nRespond with ONLY JSON."},
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
) -> list[dict]:
    """Format messages for sufficiency evaluation."""
    user_content = f"""## Original Query
{original_query}

## Current Iteration
{current_iteration}

## Tool Outputs from This Iteration
{tool_outputs}

{f"## Context from Previous Iterations\n{cumulative_context}\n" if cumulative_context else ""}
---

Evaluate whether the information above is sufficient to answer the original query.
Return ONLY valid JSON matching the SufficiencyEvaluation schema.
"""
    return [
        {"role": "system", "content": SUFFICIENCY_EVALUATOR_PROMPT},
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
