"""
Pydantic schemas for ReAct-style iterative reasoning.

Single-LLM loop: Thought -> Action -> Execute -> Observation -> (repeat or finish)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    """Sufficiency confidence level."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolCallRequest(BaseModel):
    """A single tool call request from the planner."""
    tool: str = Field(..., description="Tool name to call")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    reason: str = Field(..., description="Why this tool call is needed")


class ReActStep(BaseModel):
    """
    Complete ReAct step output from the planner.
    
    The planner outputs this on EVERY iteration:
    - Thought: reasoning about current state
    - Action: tool calls to make (empty if sufficient)
    - Observation: what was learned + sufficiency assessment
    """
    
    # Thought: reasoning about what we know and need
    thought: str = Field(
        ...,
        description="Reasoning about current information state and what's needed next"
    )
    
    # Action: tool calls (empty list = done)
    tool_calls: list[ToolCallRequest] = Field(
        default_factory=list,
        description="Tool calls to execute. Empty if sufficient."
    )
    
    # Observation / Sufficiency assessment
    observation: str = Field(
        ...,
        description="Summary of what was learned from previous tool results"
    )
    
    confidence: Confidence = Field(
        ...,
        description="Confidence that we can answer the query: low/medium/high"
    )
    
    missing_info: list[str] = Field(
        default_factory=list,
        description="Specific information still needed (empty if high confidence)"
    )
    
    # Trace summary for next iteration
    trace_summary: str = Field(
        ...,
        description="Compact summary of all steps taken so far (for context efficiency)"
    )
    
    # Control
    is_complete: bool = Field(
        default=False,
        description="True if we have enough info to generate final answer"
    )


class ToolResult(BaseModel):
    """Result of executing a single tool."""
    tool: str
    args: dict[str, Any]
    success: bool
    data: Any = None
    error: str | None = None
    truncated: bool = False
    original_count: int | None = None


class ReActContext(BaseModel):
    """
    Maintains state across ReAct iterations.
    
    Key design: Only keep rolling summary, not full trace.
    """
    
    original_query: str = Field(..., description="User's original query")
    
    # Rolling summary (replaces full trace)
    trace_summary: str = Field(
        default="",
        description="Compact summary of all iterations so far"
    )
    
    # Current iteration
    iteration: int = Field(default=1, ge=1)
    max_iterations: int = Field(default=10, ge=1, le=20)
    
    # Last tool results (only keep most recent)
    last_tool_results: list[ToolResult] = Field(
        default_factory=list,
        description="Results from most recent tool execution"
    )
    
    # Resolved entities (persist across iterations)
    resolved_drugs: dict[str, int] = Field(default_factory=dict)
    resolved_genes: dict[str, int] = Field(default_factory=dict)
    resolved_diseases: dict[str, int] = Field(default_factory=dict)
    resolved_aes: dict[str, int] = Field(default_factory=dict)
    
    # Final state
    is_complete: bool = Field(default=False)
    final_observation: str = Field(default="")
    
    def can_continue(self) -> bool:
        """Check if we can do another iteration."""
        return not self.is_complete and self.iteration <= self.max_iterations
    
    def increment(self) -> None:
        """Move to next iteration."""
        self.iteration += 1


class FinalResponse(BaseModel):
    """Final response after ReAct loop completes."""
    
    summary: str = Field(
        ...,
        description="Executive summary answering the query"
    )
    
    findings: list[str] = Field(
        ...,
        description="Key findings as bullet points"
    )
    
    evidence_summary: str = Field(
        ...,
        description="Summary of evidence gathered and sources"
    )
    
    limitations: list[str] = Field(
        default_factory=list,
        description="Known limitations or gaps in the analysis"
    )
    
    confidence: Confidence = Field(
        ...,
        description="Overall confidence in the answer"
    )
