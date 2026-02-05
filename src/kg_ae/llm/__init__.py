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

from .client import NarratorClient, PlannerClient
from .config import LLMConfig
from .evidence import EvidencePack
from .executor import ToolExecutor
from .iterative_orchestrator import IterativeOrchestrator
from .iterative_schemas import (
    InformationGap,
    IterationRecord,
    IterativeContext,
    RefinementRequest,
    SufficiencyEvaluation,
    SufficiencyStatus,
    ToolExecutionRecord,
)
from .orchestrator import Orchestrator, QueryResult, ask
from .prompts import (
    AVAILABLE_TOOLS,
    NARRATOR_SYSTEM_PROMPT,
    OBSERVATION_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    REFINEMENT_QUERY_PROMPT,
    format_narrator_messages,
    format_planner_messages,
    format_refinement_messages,
    format_sufficiency_evaluation_messages,
)

# ReAct-style iterative reasoning
from .react_executor import ReActExecutor, format_resolved_entities, format_tool_results
from .react_orchestrator import ReActOrchestrator
from .react_prompts import TOOL_CATALOG, format_final_response_messages, format_react_messages
from .react_schemas import (
    Confidence,
    FinalResponse,
    ReActContext,
    ReActStep,
    ToolCallRequest,
    ToolResult,
)
from .schemas import ResolvedEntities, StopConditions, ToolCall, ToolName, ToolPlan

__all__ = [
    # Config
    "LLMConfig",
    # Schemas
    "ToolName",
    "ToolCall",
    "ToolPlan",
    "ResolvedEntities",
    "StopConditions",
    # Iterative Reasoning Schemas
    "SufficiencyStatus",
    "InformationGap",
    "SufficiencyEvaluation",
    "RefinementRequest",
    "ToolExecutionRecord",
    "IterationRecord",
    "IterativeContext",
    # ReAct Schemas
    "Confidence",
    "ToolCallRequest",
    "ToolResult",
    "ReActStep",
    "ReActContext",
    "FinalResponse",
    # Evidence
    "EvidencePack",
    # Clients
    "PlannerClient",
    "NarratorClient",
    # Executor
    "ToolExecutor",
    "ReActExecutor",
    # Orchestrators
    "Orchestrator",
    "QueryResult",
    "IterativeOrchestrator",
    "ReActOrchestrator",
    # Prompts
    "AVAILABLE_TOOLS",
    "TOOL_CATALOG",
    "PLANNER_SYSTEM_PROMPT",
    "NARRATOR_SYSTEM_PROMPT",
    "OBSERVATION_PROMPT",
    "REFINEMENT_QUERY_PROMPT",
    "format_planner_messages",
    "format_narrator_messages",
    "format_sufficiency_evaluation_messages",
    "format_refinement_messages",
    "format_react_messages",
    "format_final_response_messages",
    "format_tool_results",
    "format_resolved_entities",
    # Entry point
    "ask",
]
