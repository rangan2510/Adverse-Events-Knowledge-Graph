"""
ReAct-style iterative orchestrator for multi-iteration query refinement.

Implements the loop:
  [Thought]     Planner reasons about what's needed (mini model)
  [Action]      Planner outputs tool plan
  [Execute]     Tools are executed
  [Observation] Narrator evaluates results (full model)
  [Repeat or Finish]
"""

from __future__ import annotations

import time
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .client import PlannerClient, NarratorClient
from .schemas import ToolPlan
from .iterative_schemas import (
    SufficiencyEvaluation,
    ToolExecutionRecord,
    IterationRecord,
    IterativeContext,
    SufficiencyStatus,
)
from .prompts import (
    format_planner_messages,
    format_sufficiency_evaluation_messages,
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
        tool_executor_fn: Callable[[ToolPlan], list],
        max_iterations: int | None = None,
    ) -> IterativeContext:
        """
        Execute ReAct-style iterative query.
        
        Args:
            query: User's natural language query
            tool_executor_fn: Function that takes ToolPlan and returns list of ToolResult
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
            console.print(f"\n[bold cyan]Query:[/] {query}")
            console.print(f"[dim](max {max_iter} iterations)[/]\n")
        
        cumulative_context = ""  # Builds up across iterations
        
        # ReAct loop: Thought -> Action -> Execute -> Observation -> (Repeat or Finish)
        while context.can_continue():
            iteration_num = context.current_iteration
            
            if self.verbose:
                console.print(f"\n[bold yellow]--- Iteration {iteration_num} ---[/]")
            
            start_time = time.time()
            
            # [Thought + Action] - Planner generates reasoning and tool plan
            plan = self._plan_iteration(
                original_query=query,
                cumulative_context=cumulative_context,
                iteration=iteration_num,
            )
            
            if self.verbose:
                self._display_thought_action(plan)
            
            # Check if planner decided to stop
            if plan.stop_conditions.no_relevant_tools or plan.stop_conditions.sufficient_information:
                if self.verbose:
                    reason = "sufficient information" if plan.stop_conditions.sufficient_information else "no relevant tools"
                    console.print(f"\n[green]Planner stopped: {reason}[/]")
                
                # Create iteration record with no tool executions
                iteration_record = IterationRecord(
                    iteration_number=iteration_num,
                    query=query,
                    tool_executions=[],
                    timestamp_start=start_time,
                    timestamp_end=time.time(),
                )
                context.add_iteration_record(iteration_record)
                
                # Generate final response from what we have
                final_response = self._generate_final_response(context, cumulative_context)
                context.final_response = final_response
                context.mark_complete("planner_stopped")
                break
            
            # [Execute] - Run the planned tools
            tool_results = tool_executor_fn(plan)
            
            # Convert to ToolExecutionRecord list
            execution_records = self._convert_tool_results(tool_results, plan)
            
            # Format tool outputs for context
            tool_outputs_text = self._format_tool_outputs(execution_records)
            
            # Create iteration record
            iteration_record = IterationRecord(
                iteration_number=iteration_num,
                query=query,
                tool_executions=execution_records,
                timestamp_start=start_time,
            )
            
            # [Observation] - Narrator evaluates results
            observation = self._generate_observation(
                original_query=query,
                iteration=iteration_num,
                tool_outputs=tool_outputs_text,
                cumulative_context=cumulative_context,
            )
            
            iteration_record.sufficiency_evaluation = observation
            iteration_record.timestamp_end = time.time()
            context.add_iteration_record(iteration_record)
            
            if self.verbose:
                self._display_observation(observation)
            
            # Update cumulative context for next iteration
            cumulative_context = self._build_cumulative_context(
                previous_context=cumulative_context,
                iteration=iteration_num,
                thought=plan.thought,
                tool_outputs=tool_outputs_text,
                observation=observation.reasoning,
            )
            
            # Decide: continue or finish
            if observation.status == SufficiencyStatus.SUFFICIENT or observation.can_answer_with_current_data:
                if self.verbose:
                    console.print(f"\n[green]Observation: sufficient. Generating final response...[/]")
                
                final_response = self._generate_final_response(context, cumulative_context)
                context.final_response = final_response
                context.mark_complete("sufficient")
                break
            
            elif context.current_iteration >= context.max_iterations:
                if self.verbose:
                    console.print(f"\n[yellow]Max iterations reached. Generating best-effort response...[/]")
                
                final_response = self._generate_final_response(context, cumulative_context)
                context.final_response = final_response
                context.mark_complete("max_iterations")
                break
            
            else:
                # Continue to next iteration - planner will see updated context
                context.increment_iteration()
        
        return context
    
    def _plan_iteration(
        self,
        original_query: str,
        cumulative_context: str,
        iteration: int,
    ) -> ToolPlan:
        """
        Ask planner LLM to generate thought + action (tool plan).
        
        Uses mini model (fast) to reason about what tools are needed.
        """
        messages = format_planner_messages(
            query=original_query,
            cumulative_context=cumulative_context,
            iteration=iteration,
        )
        
        result = self.planner.generate_structured(
            messages=messages,
            response_model=ToolPlan,
        )
        
        return result
    
    def _convert_tool_results(
        self,
        tool_results: list,
        plan: ToolPlan,
    ) -> list[ToolExecutionRecord]:
        """Convert raw tool results to ToolExecutionRecord list."""
        records = []
        
        # Build reason lookup from plan
        reason_map = {}
        for call in plan.calls:
            key = (call.tool, str(call.args))
            reason_map[key] = call.reason
        
        for result in tool_results:
            key = (result.tool, str(result.args))
            reason = reason_map.get(key, None)
            
            record = ToolExecutionRecord(
                tool_name=result.tool,
                args=result.args,
                success=result.success,
                result_summary=self._summarize_result(result),
                error=result.error,
                iteration=1,  # Will be set correctly by caller
                reason=reason or getattr(result, 'reason', None),
            )
            records.append(record)
        
        return records
    
    def _generate_observation(
        self,
        original_query: str,
        iteration: int,
        tool_outputs: str,
        cumulative_context: str,
    ) -> SufficiencyEvaluation:
        """
        Ask narrator LLM to generate observation (evaluate results).
        
        Uses full model (smart) to analyze tool outputs and determine sufficiency.
        """
        messages = format_sufficiency_evaluation_messages(
            original_query=original_query,
            current_iteration=iteration,
            tool_outputs=tool_outputs,
            cumulative_context=cumulative_context,
        )
        
        result = self.narrator.generate_structured(
            messages=messages,
            response_model=SufficiencyEvaluation,
        )
        
        return result
    
    def _build_cumulative_context(
        self,
        previous_context: str,
        iteration: int,
        thought: str,
        tool_outputs: str,
        observation: str,
    ) -> str:
        """Build cumulative context string for next iteration."""
        new_section = f"""
=== Iteration {iteration} ===
[Thought] {thought}

[Tool Results]
{tool_outputs}

[Observation] {observation}
"""
        return previous_context + new_section
    
    def _generate_final_response(self, context: IterativeContext, cumulative_context: str) -> str:
        """Generate final narrative response using all gathered evidence."""
        if self.verbose:
            console.print("\n[bold cyan]Generating final response...[/]")
        
        messages = format_narrator_messages(
            query=context.original_query,
            evidence_context=cumulative_context,
        )
        
        response = self.narrator.generate_text(messages=messages)
        return response
    
    def _format_tool_outputs(self, tool_results: list[ToolExecutionRecord]) -> str:
        """Format tool outputs for LLM context."""
        lines = []
        for result in tool_results:
            status = "\u2713" if result.success else "\u2717"
            reason_str = f" [{result.reason}]" if result.reason else ""
            lines.append(f"{status} {result.tool_name}({result.args}){reason_str}")
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
    
    def _display_thought_action(self, plan: ToolPlan) -> None:
        """Display the planner's thought and action (tool plan)."""
        console.print(f"\n[bold magenta][Thought][/] {plan.thought}")
        
        if not plan.calls:
            console.print(f"\n[bold blue][Action][/] No tools to call")
        else:
            console.print(f"\n[bold blue][Action][/] Calling {len(plan.calls)} tool(s):")
            for call in plan.calls:
                reason_str = f" - {call.reason}" if call.reason else ""
                console.print(f"  - {call.tool}({call.args}){reason_str}")
    
    def _display_observation(self, observation: SufficiencyEvaluation) -> None:
        """Display the narrator's observation."""
        status_color = {
            SufficiencyStatus.SUFFICIENT: "green",
            SufficiencyStatus.INSUFFICIENT: "red",
            SufficiencyStatus.PARTIALLY_SUFFICIENT: "yellow",
        }
        
        color = status_color.get(observation.status, "white")
        
        console.print(f"\n[bold cyan][Observation][/]")
        console.print(f"  [{color}]Status: {observation.status}[/] (confidence: {observation.confidence:.0%})")
        console.print(f"  {observation.reasoning}")
        
        if observation.information_gaps:
            console.print(f"\n  [dim]Information gaps:[/]")
            for gap in observation.information_gaps:
                tool_hint = f" (use {gap.suggested_tool})" if gap.suggested_tool else ""
                console.print(f"    - [{gap.category}] {gap.description}{tool_hint}")
