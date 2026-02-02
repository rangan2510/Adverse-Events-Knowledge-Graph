"""
LLM orchestration layer for the Drug-AE Knowledge Graph.

Two-phase architecture:
- Planner (Phi-4-mini): Generates structured tool plans
- Narrator (Phi-4): Synthesizes evidence into natural language

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
from .schemas import ToolName, ToolCall, ToolPlan, StopConditions, ResolvedEntities
from .iterative_schemas import (
    SufficiencyStatus,
    InformationGap,
    SufficiencyEvaluation,
    RefinementRequest,
    ToolExecutionRecord,
    IterationRecord,
    IterativeContext,
)
from .evidence import EvidencePack
from .client import PlannerClient, NarratorClient
from .executor import ToolExecutor
from .orchestrator import Orchestrator, QueryResult, ask
from .iterative_orchestrator import IterativeOrchestrator
from .prompts import (
    AVAILABLE_TOOLS,
    PLANNER_SYSTEM_PROMPT,
    NARRATOR_SYSTEM_PROMPT,
    OBSERVATION_PROMPT,
    REFINEMENT_QUERY_PROMPT,
    format_planner_messages,
    format_narrator_messages,
    format_sufficiency_evaluation_messages,
    format_refinement_messages,
)

__all__ = [
    # Config
    "LLMConfig",
    # Schemas
    "ToolName",
    "ToolCall",
    "ToolPlan",
    "ResolvedEntities",
    # Iterative Reasoning Schemas
    "SufficiencyStatus",
    "InformationGap",
    "SufficiencyEvaluation",
    "RefinementRequest",
    "ToolExecutionRecord",
    "IterationRecord",
    "IterativeContext",
    # Evidence
    "EvidencePack",
    # Clients
    "PlannerClient",
    "NarratorClient",
    # Executor
    "ToolExecutor",
    # Orchestrators
    "Orchestrator",
    "QueryResult",
    "IterativeOrchestrator",
    # Prompts
    "AVAILABLE_TOOLS",
    "PLANNER_SYSTEM_PROMPT",
    "NARRATOR_SYSTEM_PROMPT",
    "OBSERVATION_PROMPT",
    "REFINEMENT_QUERY_PROMPT",
    "format_planner_messages",
    "format_narrator_messages",
    "format_sufficiency_evaluation_messages",
    "format_refinement_messages",
    # Entry point
    "ask",
]
