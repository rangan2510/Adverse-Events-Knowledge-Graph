"""
Iterative orchestrator for multi-iteration query refinement.

Implements the flow:
1. Query → Planner → Tool calls
2. Narrator evaluates sufficiency
3. If insufficient → Refinement query → Loop back to step 1
4. Continue until sufficient OR max iterations
5. Narrator generates final response
"""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .client import PlannerClient, NarratorClient
from .iterative_schemas import (
    SufficiencyEvaluation,
    RefinementRequest,
    ToolExecutionRecord,
    IterationRecord,
    IterativeContext,
    SufficiencyStatus,
)
from .prompts import (
    format_planner_messages,
    format_sufficiency_evaluation_messages,
    format_refinement_messages,
    format_narrator_messages,
)

console = Console()


class IterativeOrchestrator:
    """
    Orchestrates iterative query refinement with multi-step reasoning.
    
    The narrator LLM evaluates after each iteration whether sufficient
    information has been gathered, and can request additional tool calls.
    """
    
    def __init__(
        self,
        planner_client: PlannerClient,
        narrator_client: NarratorClient,
        max_iterations: int = 3,
        verbose: bool = True,
    ):
        """
        Initialize orchestrator.
        
        Args:
            planner_client: Client for planner LLM (tool calling)
            narrator_client: Client for narrator LLM (evaluation + final response)
            max_iterations: Maximum iterations before forcing final answer
            verbose: Whether to print progress updates
        """
        self.planner = planner_client
        self.narrator = narrator_client
        self.max_iterations = max_iterations
        self.verbose = verbose
    
    def query(
        self,
        query: str,
        tool_executor_fn: Any,  # Function that takes (query) -> list[ToolResult]
        max_iterations: int | None = None,
    ) -> IterativeContext:
        """
        Execute iterative query with multi-step refinement.
        
        Args:
            query: User's natural language query
            tool_executor_fn: Function to execute tool plans (returns ToolResult list)
            max_iterations: Override default max iterations
            
        Returns:
            Complete IterativeContext with all iterations and final response
        """
        max_iter = max_iterations or self.max_iterations
        context = IterativeContext(
            original_query=query,
            max_iterations=max_iter,
        )
        
        if self.verbose:
            console.print(
                Panel(
                    f"[bold cyan]Query:[/] {query}\n[dim]Max iterations: {max_iter}[/]",
                    title="🔄 Iterative Query Pipeline",
                    border_style="cyan",
                )
            )
        
        current_query = query
        
        # Iterative loop
        while context.can_continue():
            iteration_num = context.current_iteration
            
            if self.verbose:
                console.print(f"\n[bold yellow]━━━ Iteration {iteration_num}/{max_iter} ━━━[/]")
            
            # Start timing
            start_time = time.time()
            
            # Phase 1: Execute tools for current query
            tool_results = self._execute_iteration(current_query, tool_executor_fn)
            
            # Create iteration record
            iteration_record = IterationRecord(
                iteration_number=iteration_num,
                query=current_query,
                tool_executions=tool_results,
                timestamp_start=start_time,
            )
            
            # Phase 2: Evaluate sufficiency
            tool_outputs_text = self._format_tool_outputs(tool_results)
            cumulative_context = context.get_cumulative_context() if iteration_num > 1 else ""
            
            sufficiency_eval = self._evaluate_sufficiency(
                original_query=query,
                current_iteration=iteration_num,
                tool_outputs=tool_outputs_text,
                cumulative_context=cumulative_context,
            )
            
            iteration_record.sufficiency_evaluation = sufficiency_eval
            
            if self.verbose:
                self._display_sufficiency_eval(sufficiency_eval)
            
            # Phase 3: Decide next action
            if sufficiency_eval.status == SufficiencyStatus.SUFFICIENT or sufficiency_eval.can_answer_with_current_data:
                # We have enough - generate final response
                iteration_record.timestamp_end = time.time()
                context.add_iteration_record(iteration_record)
                
                final_response = self._generate_final_response(context, tool_outputs_text)
                context.final_response = final_response
                context.mark_complete("sufficient")
                
                if self.verbose:
                    console.print(f"\n[green]✓ Sufficient information gathered after {iteration_num} iteration(s)[/]")
                
                break
            
            elif not context.can_continue():
                # Hit max iterations - force final response
                iteration_record.timestamp_end = time.time()
                context.add_iteration_record(iteration_record)
                
                final_response = self._generate_final_response(context, tool_outputs_text)
                context.final_response = final_response
                context.mark_complete("max_iterations")
                
                if self.verbose:
                    console.print(f"\n[yellow]⚠ Maximum iterations reached - generating best-effort response[/]")
                
                break
            
            else:
                # Need more information - generate refinement
                refinement = self._generate_refinement(
                    original_query=query,
                    current_iteration=iteration_num,
                    sufficiency_eval=sufficiency_eval,
                    cumulative_context=cumulative_context,
                )
                
                iteration_record.refinement_request = refinement
                iteration_record.timestamp_end = time.time()
                context.add_iteration_record(iteration_record)
                
                if self.verbose:
                    self._display_refinement(refinement)
                
                # Update query for next iteration
                current_query = refinement.refinement_query
                context.increment_iteration()
        
        return context
    
    def _execute_iteration(self, query: str, tool_executor_fn: Any) -> list[ToolExecutionRecord]:
        """Execute tools for one iteration."""
        if self.verbose:
            console.print(f"[dim]Planning tools for:[/] {query}")
        
        # Call tool executor (returns list of ToolResult)
        tool_results = tool_executor_fn(query)
        
        # Convert to ToolExecutionRecord
        records = []
        for result in tool_results:
            record = ToolExecutionRecord(
                tool_name=result.tool,
                args=result.args,
                success=result.success,
                result_summary=self._summarize_result(result),
                error=result.error,
                iteration=1,  # Will be updated by caller
            )
            records.append(record)
        
        if self.verbose:
            console.print(f"[green]✓ Executed {len(records)} tool(s)[/]")
        
        return records
    
    def _evaluate_sufficiency(
        self,
        original_query: str,
        current_iteration: int,
        tool_outputs: str,
        cumulative_context: str,
    ) -> SufficiencyEvaluation:
        """Ask narrator LLM to evaluate sufficiency."""
        if self.verbose:
            console.print("[dim]Evaluating information sufficiency...[/]")
        
        messages = format_sufficiency_evaluation_messages(
            original_query=original_query,
            current_iteration=current_iteration,
            tool_outputs=tool_outputs,
            cumulative_context=cumulative_context,
        )
        
        result = self.narrator.generate_structured(
            messages=messages,
            response_model=SufficiencyEvaluation,
        )
        
        return result
    
    def _generate_refinement(
        self,
        original_query: str,
        current_iteration: int,
        sufficiency_eval: SufficiencyEvaluation,
        cumulative_context: str,
    ) -> RefinementRequest:
        """Ask narrator LLM to generate refinement query."""
        if self.verbose:
            console.print("[dim]Generating refinement query...[/]")
        
        messages = format_refinement_messages(
            original_query=original_query,
            current_iteration=current_iteration,
            sufficiency_eval=sufficiency_eval.model_dump(),
            cumulative_context=cumulative_context,
        )
        
        result = self.narrator.generate_structured(
            messages=messages,
            response_model=RefinementRequest,
        )
        
        return result
    
    def _generate_final_response(self, context: IterativeContext, latest_tool_outputs: str) -> str:
        """Generate final narrative response using all gathered evidence."""
        if self.verbose:
            console.print("\n[bold cyan]Generating final response...[/]")
        
        # Combine all tool outputs from all iterations
        all_evidence = context.get_cumulative_context() + "\n\n" + latest_tool_outputs
        
        messages = format_narrator_messages(
            query=context.original_query,
            evidence_context=all_evidence,
        )
        
        response = self.narrator.generate_text(messages=messages)
        return response
    
    def _format_tool_outputs(self, tool_results: list[ToolExecutionRecord]) -> str:
        """Format tool outputs for LLM context."""
        lines = []
        for result in tool_results:
            status = "✓" if result.success else "✗"
            lines.append(f"{status} {result.tool_name}({result.args})")
            if result.success:
                lines.append(f"  Result: {result.result_summary}")
            else:
                lines.append(f"  Error: {result.error}")
        return "\n".join(lines)
    
    def _summarize_result(self, result: Any) -> str:
        """Create brief summary of tool result."""
        if not result.success:
            return "Failed"
        
        if result.result is None:
            return "No data"
        
        if isinstance(result.result, list):
            return f"{len(result.result)} items"
        
        if isinstance(result.result, dict):
            return f"{len(result.result)} entries"
        
        return "Success"
    
    def _display_sufficiency_eval(self, eval_result: SufficiencyEvaluation) -> None:
        """Display sufficiency evaluation in rich format."""
        status_color = {
            SufficiencyStatus.SUFFICIENT: "green",
            SufficiencyStatus.INSUFFICIENT: "red",
            SufficiencyStatus.PARTIALLY_SUFFICIENT: "yellow",
        }
        
        color = status_color.get(eval_result.status, "white")
        
        table = Table(title="Sufficiency Evaluation", show_header=False, box=None)
        table.add_column("Key", style="bold")
        table.add_column("Value")
        
        table.add_row("Status", f"[{color}]{eval_result.status}[/]")
        table.add_row("Confidence", f"{eval_result.confidence:.2f}")
        table.add_row("Can Answer", "✓" if eval_result.can_answer_with_current_data else "✗")
        table.add_row("Reasoning", eval_result.reasoning[:100] + "..." if len(eval_result.reasoning) > 100 else eval_result.reasoning)
        
        if eval_result.information_gaps:
            gaps_str = ", ".join(f"{g.category} (P{g.priority})" for g in eval_result.information_gaps[:3])
            table.add_row("Gaps", gaps_str)
        
        console.print(table)
    
    def _display_refinement(self, refinement: RefinementRequest) -> None:
        """Display refinement request in rich format."""
        console.print(
            Panel(
                f"[bold]Refinement Query:[/]\n{refinement.refinement_query}\n\n"
                f"[bold]Focus Areas:[/] {', '.join(refinement.focus_areas)}\n"
                f"[bold]Priority Gaps:[/] {len(refinement.priority_gaps)} gap(s)",
                title=f"🔍 Iteration {refinement.iteration_count} → {refinement.iteration_count + 1}",
                border_style="yellow",
            )
        )
