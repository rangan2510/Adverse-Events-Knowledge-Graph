"""
LLM orchestration layer for the Drug-AE Knowledge Graph.

Two-phase architecture:
- Planner (Phi-4-mini): Generates structured tool plans
- Narrator (MediPhi): Summarizes evidence into natural language

Usage:
    from kg_ae.llm import Orchestrator, ask

    # Simple query
    result = ask(conn, "What adverse events might metformin cause?")
    print(result.narrative)

    # With progress output
    orchestrator = Orchestrator(conn, verbose=True)
    result = orchestrator.query("Explain warfarin bleeding risk")
"""

from .config import LLMConfig
from .schemas import ToolName, ToolCall, ToolPlan, ResolvedEntities
from .evidence import EvidencePack
from .client import PlannerClient, NarratorClient
from .executor import ToolExecutor
from .orchestrator import Orchestrator, QueryResult, ask
from .prompts import (
    PLANNER_SYSTEM_PROMPT,
    NARRATOR_SYSTEM_PROMPT,
    format_planner_messages,
    format_narrator_messages,
)

__all__ = [
    # Config
    "LLMConfig",
    # Schemas
    "ToolName",
    "ToolCall",
    "ToolPlan",
    "ResolvedEntities",
    # Evidence
    "EvidencePack",
    # Clients
    "PlannerClient",
    "NarratorClient",
    # Executor
    "ToolExecutor",
    # Orchestrator
    "Orchestrator",
    "QueryResult",
    "ask",
    # Prompts
    "PLANNER_SYSTEM_PROMPT",
    "NARRATOR_SYSTEM_PROMPT",
    "format_planner_messages",
    "format_narrator_messages",
]
