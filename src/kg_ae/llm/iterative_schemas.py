"""
Pydantic schemas for iterative reasoning flow.

Supports multi-iteration query refinement where the narrator LLM evaluates
sufficiency of tool outputs and requests additional information if needed.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SufficiencyStatus(str, Enum):
    """Status of information sufficiency."""
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    PARTIALLY_SUFFICIENT = "partially_sufficient"


class InformationGap(BaseModel):
    """Describes a specific gap in available information."""
    category: str = Field(..., description="Category of missing info (e.g., 'mechanism', 'pathway', 'interaction')")
    description: str = Field(..., description="What information is missing")
    priority: int = Field(default=1, description="Priority 1=high, 2=medium, 3=low")
    suggested_tool: str | None = Field(
        default=None,
        description="Tool that could fill this gap (e.g., 'get_gene_pathways')"
    )


class SufficiencyEvaluation(BaseModel):
    """Narrator's assessment of whether current tool outputs answer the query."""
    
    status: SufficiencyStatus = Field(
        ..., 
        description="Overall sufficiency status"
    )
    
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0,
        description="Confidence in this evaluation (0-1)"
    )
    
    reasoning: str = Field(
        ..., 
        description="Explanation of why information is or isn't sufficient"
    )
    
    information_gaps: list[InformationGap] = Field(
        default_factory=list,
        description="Specific gaps in information (empty if sufficient)"
    )
    
    can_answer_with_current_data: bool = Field(
        ..., 
        description="Can we give a meaningful answer with what we have?"
    )
    
    iteration_count: int = Field(
        ..., 
        ge=1,
        description="Current iteration number"
    )
    
    class Config:
        use_enum_values = True


class RefinementRequest(BaseModel):
    """Request for additional information to fill gaps."""
    
    refinement_query: str = Field(
        ..., 
        description="Natural language query for the next iteration"
    )
    
    focus_areas: list[str] = Field(
        ..., 
        min_length=1,
        description="Specific areas to investigate (e.g., ['pathways', 'interactions'])"
    )
    
    suggested_tools: list[str] = Field(
        default_factory=list,
        description="Optional tool suggestions for the planner"
    )
    
    priority_gaps: list[InformationGap] = Field(
        ...,
        min_length=1,
        description="Ordered list of gaps to address (highest priority first)"
    )
    
    iteration_count: int = Field(
        ..., 
        ge=1,
        description="Iteration that generated this request"
    )


class ToolExecutionRecord(BaseModel):
    """Record of a single tool execution."""
    
    tool_name: str = Field(..., description="Name of the tool")
    args: dict = Field(default_factory=dict, description="Arguments passed")
    success: bool = Field(..., description="Whether execution succeeded")
    result_summary: str = Field(..., description="Brief summary of result")
    error: str | None = Field(None, description="Error message if failed")
    iteration: int = Field(..., description="Which iteration this was executed in")
    reason: str | None = Field(None, description="Why this tool was called")


class IterationRecord(BaseModel):
    """Complete record of a single iteration."""
    
    iteration_number: int = Field(..., ge=1, description="1-indexed iteration number")
    query: str = Field(..., description="Query for this iteration")
    tool_executions: list[ToolExecutionRecord] = Field(
        default_factory=list,
        description="Tools executed in this iteration"
    )
    sufficiency_evaluation: SufficiencyEvaluation | None = Field(
        None,
        description="Sufficiency check result"
    )
    refinement_request: RefinementRequest | None = Field(
        None,
        description="Request for next iteration (if not sufficient)"
    )
    timestamp_start: float = Field(..., description="Unix timestamp when iteration started")
    timestamp_end: float | None = Field(None, description="Unix timestamp when iteration ended")


class IterativeContext(BaseModel):
    """
    Maintains state across multiple iterations of query refinement.
    
    Flow:
    1. Original query → Iteration 1
    2. Narrator evaluates sufficiency
    3. If insufficient → RefinementRequest → Iteration 2
    4. Repeat until sufficient OR max_iterations reached
    5. Narrator generates final response
    """
    
    original_query: str = Field(..., description="The user's initial query")
    
    current_iteration: int = Field(default=1, ge=1, description="Current iteration number")
    
    max_iterations: int = Field(
        default=3, 
        ge=1, 
        le=20,
        description="Maximum iterations before forcing final answer"
    )
    
    iterations: list[IterationRecord] = Field(
        default_factory=list,
        description="History of all iterations"
    )
    
    final_response: str | None = Field(
        None,
        description="Final narrative response (set when done)"
    )
    
    is_complete: bool = Field(
        default=False,
        description="Whether the iterative process is finished"
    )
    
    completion_reason: str | None = Field(
        None,
        description="Why iteration stopped (sufficient|max_iterations|error)"
    )
    
    def can_continue(self) -> bool:
        """Check if another iteration is allowed."""
        return not self.is_complete and self.current_iteration <= self.max_iterations
    
    def increment_iteration(self) -> None:
        """Move to next iteration."""
        if self.can_continue():
            self.current_iteration += 1
    
    def mark_complete(self, reason: str) -> None:
        """Mark the iterative process as complete."""
        self.is_complete = True
        self.completion_reason = reason
    
    def get_current_iteration_record(self) -> IterationRecord | None:
        """Get the record for the current iteration."""
        if self.iterations and len(self.iterations) >= self.current_iteration:
            return self.iterations[self.current_iteration - 1]
        return None
    
    def add_iteration_record(self, record: IterationRecord) -> None:
        """Add a new iteration record."""
        self.iterations.append(record)
    
    def get_all_tool_executions(self) -> list[ToolExecutionRecord]:
        """Get flat list of all tool executions across iterations."""
        all_tools = []
        for iteration in self.iterations:
            all_tools.extend(iteration.tool_executions)
        return all_tools
    
    def get_cumulative_context(self) -> str:
        """
        Build cumulative context from all iterations.
        Used to inform the narrator in subsequent iterations.
        """
        lines = [f"Original Query: {self.original_query}\n"]
        
        for iteration in self.iterations:
            lines.append(f"\n--- Iteration {iteration.iteration_number} ---")
            if iteration.query != self.original_query:
                lines.append(f"Refinement: {iteration.query}")
            
            lines.append(f"Tools Executed: {len(iteration.tool_executions)}")
            for tool_exec in iteration.tool_executions:
                status = "\u2713" if tool_exec.success else "\u2717"
                reason_str = f" [{tool_exec.reason}]" if tool_exec.reason else ""
                lines.append(f"  {status} {tool_exec.tool_name}{reason_str}: {tool_exec.result_summary}")
            
            if iteration.sufficiency_evaluation:
                eval_result = iteration.sufficiency_evaluation
                lines.append(f"Sufficiency: {eval_result.status} (confidence: {eval_result.confidence:.2f})")
                if eval_result.information_gaps:
                    lines.append(f"  Gaps: {', '.join(g.category for g in eval_result.information_gaps)}")
        
        return "\n".join(lines)
