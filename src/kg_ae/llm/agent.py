"""
LangChain/LangGraph ReAct agent for the pharmacovigilance knowledge graph.

Replaces the bespoke ReAct + iterative orchestrators with a single
``create_react_agent`` wired to the GraphStore tools (and optional Tavily).
The LLM remains a controller over deterministic tools: it narrates only what
the tools return.

Multiple-agents-doing-the-same-work is implemented as a self-consistency
ensemble: ``agent_ensemble_size`` independent agents answer the same query and
their answers are reconciled by a final pass. With size 1 it is a single agent.
This adds robustness, which also helps the EU AI Act accuracy/robustness story.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from kg_ae.config import settings
from kg_ae.llm.lc_tools import build_tools
from kg_ae.llm.llm_client import build_chat_model

SYSTEM_PROMPT = """You are a pharmacovigilance reasoning controller over a curated knowledge graph.

The graph traces: Drug -> Gene (target) -> Pathway / Disease, and Drug -> Adverse Event.
Every fact you state MUST come from a tool result. You may NOT invent drug targets,
pathways, disease links, adverse events, frequencies, or citations.

Workflow:
1. Resolve any drug/gene/disease/AE names to integer keys FIRST (the resolve_* tools).
2. Use the returned integer keys with the other tools to gather evidence.
3. When you have enough evidence, write a concise answer that cites the graph
   data you retrieved (drug/gene/pathway names, scores, frequencies).

Choosing tools for INSIGHT (prefer the most specific tool for the question):
- "Why might drug X cause adverse event Y?" -> resolve drug + AE, then
  explain_paths (ranked, evidence-weighted mechanistic paths). If explain_paths
  returns no path that reaches the AE, FALL BACK to get_drug_targets +
  expand_mechanism and explain the mechanism via the drug's primary target and
  its pathways (e.g. the target whose inhibition is the drug's mechanism of
  action). Do NOT invent a disease-to-AE link the tools did not return.
- "What does drug X target / how does it work?" -> get_drug_targets, then
  expand_mechanism for target pathways. Add gene_interactors for indirect
  (one-hop) mechanism when direct targets are sparse.
- "What genes drive disease Z / what else targets them?" -> resolve disease,
  get_disease_genes, then reason toward drugs that hit those genes.
- Drug-drug interaction (polypharmacy): resolve BOTH drugs, then
  drug-drug-interactions for combination AEs (TWOSIDES).
- Corroborate adverse events with FAERS signals (PRR/ROR) and, when present,
  drug label sections (boxed warnings, contraindications).

Reporting rules (make answers insightful, not just lists):
- Rank by evidence strength: lead with the highest-scored / multi-source links.
- Always cite the concrete numbers you retrieved (binding/association scores,
  PRR, frequency) and the source dataset.
- Distinguish DIRECT mechanism (drug's own target) from INDIRECT (via an
  interacting gene) and say which it is.
- Prefer mechanistic explanations (drug -> target -> pathway/disease) over bare lists.

Rules:
- If a name does not resolve, say so plainly; do not guess.
- The web-search tool, if present, is ONLY for normalizing/verifying a term to a
  canonical name. Never treat its output as mechanistic evidence or a citation.
- Never include patient-specific identifiers in any tool call.
"""

RECONCILE_PROMPT = """You are reconciling {n} independent answers to the same pharmacovigilance question.

Question: {query}

Candidate answers:
{candidates}

Produce one consolidated answer. Keep only claims that are supported across the
candidates or clearly grounded in graph evidence. Drop anything contradictory or
unsupported. Be concise and mechanistic.
"""


@dataclass
class AgentResult:
    """Result of an agent run."""

    answer: str
    tool_calls: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)


def _run_single(query: str, max_iterations: int, model: str | None = None) -> tuple[str, list[str]]:
    chat_model = build_chat_model(model=model)
    tools = build_tools()
    agent = create_react_agent(chat_model, tools)

    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=query)]
    result = agent.invoke(
        {"messages": messages},
        config={"recursion_limit": max_iterations * 2 + 1},
    )
    msgs = result["messages"]

    tool_calls: list[str] = []
    for m in msgs:
        for tc in getattr(m, "tool_calls", None) or []:
            tool_calls.append(tc.get("name", "?"))

    answer = ""
    for m in reversed(msgs):
        if isinstance(m, AIMessage) and m.content:
            answer = m.content if isinstance(m.content, str) else str(m.content)
            break
    return answer, tool_calls


def _reconcile(query: str, candidates: list[str]) -> str:
    model = build_chat_model(temperature=0.0)
    listed = "\n\n".join(f"[Answer {i + 1}]\n{c}" for i, c in enumerate(candidates))
    prompt = RECONCILE_PROMPT.format(n=len(candidates), query=query, candidates=listed)
    resp = model.invoke([HumanMessage(content=prompt)])
    return resp.content if isinstance(resp.content, str) else str(resp.content)


def run_agent(
    query: str,
    ensemble_size: int | None = None,
    max_iterations: int | None = None,
    model: str | None = None,
) -> AgentResult:
    """Answer a query with a single agent or a self-consistency ensemble.

    ``model`` optionally overrides the configured LLM (for A/B experiments).
    """
    n = ensemble_size or settings.agent_ensemble_size
    iters = max_iterations or settings.max_iterations

    candidates: list[str] = []
    all_tool_calls: list[str] = []
    for _ in range(max(n, 1)):
        answer, tool_calls = _run_single(query, iters, model=model)
        candidates.append(answer)
        all_tool_calls.extend(tool_calls)

    final = candidates[0] if len(candidates) == 1 else _reconcile(query, candidates)
    return AgentResult(answer=final, tool_calls=all_tool_calls, candidates=candidates)
