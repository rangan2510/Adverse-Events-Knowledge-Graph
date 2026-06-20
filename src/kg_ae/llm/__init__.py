"""
LLM orchestration layer for the Drug-AE Knowledge Graph.

A single LangChain/LangGraph ReAct agent acts as a controller over the
deterministic GraphStore tools. The LLM is reached through one
OpenAI-compatible endpoint (OpenRouter in dev, a local server in deployment).

Usage:
    from kg_ae.llm import run_agent

    result = run_agent("What gene does atorvastatin target?")
    print(result.answer)
"""

from kg_ae.llm.agent import AgentResult, run_agent
from kg_ae.llm.llm_client import ComplianceError, build_chat_model, llm_summary

__all__ = [
    "run_agent",
    "AgentResult",
    "build_chat_model",
    "llm_summary",
    "ComplianceError",
]
