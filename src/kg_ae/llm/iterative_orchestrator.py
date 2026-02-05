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
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.status import Status
from rich.text import Text

from .client import NarratorClient, PlannerClient
from .iterative_schemas import (
    IterationRecord,
    IterativeContext,
    SufficiencyEvaluation,
    SufficiencyStatus,
    ToolExecutionRecord,
)
from .prompts import (
    format_narrator_messages,
    format_planner_messages,
    format_sufficiency_evaluation_messages,
)
from .schemas import ToolPlan

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
            query_panel = Panel(
                Text(query, style="white"),
                title="[bold cyan]Query[/]",
                subtitle=f"[dim]max {max_iter} iterations[/]",
                border_style="cyan",
            )
            console.print(query_panel)
        
        cumulative_context = ""  # Builds up across iterations
        
        # ReAct loop: Thought -> Action -> Execute -> Observation -> (Repeat or Finish)
        while context.can_continue():
            iteration_num = context.current_iteration
            
            if self.verbose:
                console.print()
                console.rule(f"[bold yellow]Iteration {iteration_num}[/]", style="yellow")
            
            start_time = time.time()
            
            # [Thought + Action] - Planner generates reasoning and tool plan
            if self.verbose:
                with Status("[bold blue]Planner thinking...[/]", spinner="dots", console=console):
                    plan = self._plan_iteration(
                        original_query=query,
                        cumulative_context=cumulative_context,
                        iteration=iteration_num,
                    )
            else:
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
                    reason = (
                        "sufficient information gathered"
                        if plan.stop_conditions.sufficient_information
                        else "no relevant tools available"
                    )
                    stop_panel = Panel(
                        f"[bold]{reason}[/]",
                        title="[bold green]Planner Stopped[/]",
                        border_style="green",
                    )
                    console.print(stop_panel)
                
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
            if self.verbose:
                with Status(f"[bold green]Executing {len(plan.calls)} tool(s)...[/]", spinner="dots", console=console):
                    tool_results = tool_executor_fn(plan)
            else:
                tool_results = tool_executor_fn(plan)
            
            # Convert to ToolExecutionRecord list
            execution_records = self._convert_tool_results(tool_results, plan)
            
            # Display tool results in a table
            if self.verbose:
                self._display_tool_results(tool_results, execution_records)
            
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
            if self.verbose:
                with Status("[bold cyan]Narrator evaluating...[/]", spinner="dots", console=console):
                    observation = self._generate_observation(
                        original_query=query,
                        iteration=iteration_num,
                        tool_outputs=tool_outputs_text,
                        cumulative_context=cumulative_context,
                    )
            else:
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
                    console.print()
                    console.print("[bold green]Evidence sufficient - generating final response...[/]")
                
                final_response = self._generate_final_response(context, cumulative_context)
                context.final_response = final_response
                context.mark_complete("sufficient")
                break
            
            elif context.current_iteration >= context.max_iterations:
                if self.verbose:
                    console.print()
                    console.print("[bold yellow]Max iterations reached - generating best-effort response...[/]")
                
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
            reason = reason_map.get(key)
            
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
        messages = format_narrator_messages(
            query=context.original_query,
            evidence_context=cumulative_context,
        )
        
        if self.verbose:
            with Status("[bold magenta]Narrator writing final response...[/]", spinner="dots", console=console):
                response = self.narrator.generate_text(messages=messages)
        else:
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
        # Build thought panel content
        thought_content = Text()
        thought_content.append(plan.thought, style="white")
        
        if plan.observations:
            thought_content.append("\n\n")
            thought_content.append("Observations: ", style="bold green")
            thought_content.append(plan.observations, style="green")
        
        if plan.action_trace:
            thought_content.append("\n\n")
            thought_content.append("Trace: ", style="dim")
            thought_content.append(plan.action_trace, style="dim italic")
        
        thought_panel = Panel(
            thought_content,
            title="[bold magenta]Planner Thought[/]",
            border_style="magenta",
        )
        console.print(thought_panel)
        
        # Display action (tool calls)
        if not plan.calls:
            console.print("[dim]No tools to call[/]")
        else:
            action_table = Table(
                title=f"[bold blue]Action: {len(plan.calls)} Tool Call(s)[/]",
                show_header=True,
                header_style="bold blue",
                border_style="blue",
            )
            action_table.add_column("Tool", style="cyan")
            action_table.add_column("Arguments", style="white")
            action_table.add_column("Reason", style="dim")
            
            for call in plan.calls:
                args_str = ", ".join(f"{k}={v!r}" for k, v in call.args.items()) if call.args else "-"
                action_table.add_row(
                    str(call.tool),
                    args_str,
                    call.reason or "-",
                )
            
            console.print(action_table)
    
    def _display_tool_results(self, raw_results: list, execution_records: list[ToolExecutionRecord]) -> None:
        """Display tool execution results in a table."""
        results_table = Table(
            title="[bold green]Tool Results[/]",
            show_header=True,
            header_style="bold green",
            border_style="green",
        )
        results_table.add_column("Status", width=3, justify="center")
        results_table.add_column("Tool", style="cyan")
        results_table.add_column("Result Summary", style="white")
        results_table.add_column("Details", style="dim", max_width=60)
        
        for raw, record in zip(raw_results, execution_records):
            status_icon = "[green]OK[/]" if record.success else "[red]ERR[/]"
            
            # Get more detailed result info
            details = ""
            if record.success and hasattr(raw, 'result') and raw.result is not None:
                result_data = raw.result
                if isinstance(result_data, list) and len(result_data) > 0:
                    # Show first few items as preview
                    if isinstance(result_data[0], dict):
                        keys = list(result_data[0].keys())[:3]
                        details = f"Keys: {', '.join(keys)}"
                    else:
                        preview = str(result_data[:2])[:50]
                        details = preview + "..." if len(str(result_data)) > 50 else preview
                elif isinstance(result_data, dict):
                    keys = list(result_data.keys())[:4]
                    details = f"Keys: {', '.join(keys)}"
            elif record.error:
                details = record.error[:50] + "..." if len(record.error or "") > 50 else (record.error or "")
            
            results_table.add_row(
                status_icon,
                record.tool_name,
                record.result_summary,
                details,
            )
        
        console.print(results_table)
    
    def _display_observation(self, observation: SufficiencyEvaluation) -> None:
        """Display the narrator's observation."""
        status_config = {
            SufficiencyStatus.SUFFICIENT: ("green", "SUFFICIENT"),
            SufficiencyStatus.INSUFFICIENT: ("red", "INSUFFICIENT"),
            SufficiencyStatus.PARTIALLY_SUFFICIENT: ("yellow", "PARTIAL"),
        }
        
        color, status_label = status_config.get(observation.status, ("white", "UNKNOWN"))
        
        # Confidence level label
        if observation.confidence >= 0.8:
            conf_label, conf_color = "high", "green"
        elif observation.confidence >= 0.5:
            conf_label, conf_color = "medium", "yellow"
        else:
            conf_label, conf_color = "low", "red"
        
        # Build observation content
        obs_content = Text()
        obs_content.append("Status: ", style="bold")
        obs_content.append(status_label, style=f"bold {color}")
        obs_content.append("  |  Confidence: ", style="bold")
        obs_content.append(conf_label, style=f"bold {conf_color}")
        obs_content.append("\n\n")
        obs_content.append(observation.reasoning, style="white")
        
        # Add information gaps if any
        if observation.information_gaps:
            obs_content.append("\n\n")
            obs_content.append("Information Gaps:", style="bold yellow")
            for gap in observation.information_gaps:
                obs_content.append(f"\n  - [{gap.category}] ", style="dim")
                obs_content.append(gap.description, style="white")
                if gap.suggested_tool:
                    obs_content.append(f" (use {gap.suggested_tool})", style="cyan dim")
        
        obs_panel = Panel(
            obs_content,
            title="[bold cyan]Narrator Observation[/]",
            border_style="cyan",
        )
        console.print(obs_panel)
