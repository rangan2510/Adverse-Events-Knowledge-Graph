"""
ReAct-style orchestrator for iterative knowledge graph queries.

Single LLM loop:
  Thought -> Action -> Execute -> Observation -> (repeat or answer)

Key design:
- Single Groq LLM for all steps (not separate planner/narrator)
- Rolling trace summary (not full trace) for context efficiency
- Tool output truncation to prevent context overflow
"""

from __future__ import annotations

import time

import instructor
from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .config import LLMConfig
from .react_executor import (
    ReActExecutor,
    format_resolved_entities,
    format_tool_results,
)
from .react_prompts import format_final_response_messages, format_react_messages
from .react_schemas import (
    FinalResponse,
    ReActContext,
    ReActStep,
)

console = Console()


class ReActOrchestrator:
    """
    Orchestrates ReAct-style iterative reasoning.
    
    Features:
    - Single LLM for thought/action/observation
    - Rolling trace summary (not full history)
    - Truncated tool outputs
    - Clear terminal output
    """
    
    def __init__(
        self,
        config: LLMConfig | None = None,
        max_iterations: int = 10,
        verbose: bool = True,
    ):
        """
        Args:
            config: LLM configuration (defaults to env settings)
            max_iterations: Maximum iterations before forcing answer
            verbose: Print detailed progress
        """
        self.config = config or LLMConfig()
        self.max_iterations = max_iterations
        self.verbose = verbose
        
        # Initialize LLM client with Instructor
        self._raw_client = OpenAI(
            base_url=self.config.get_planner_url(),
            api_key=self.config.get_api_key(),
        )
        mode = (
            instructor.Mode.JSON
            if self.config.provider == "groq"
            else instructor.Mode.JSON_SCHEMA
        )
        self._client = instructor.from_openai(self._raw_client, mode=mode)
    
    def query(self, query: str, max_iterations: int | None = None) -> tuple[ReActContext, str]:
        """
        Execute ReAct query loop.
        
        Args:
            query: User's natural language query
            max_iterations: Override default max iterations
            
        Returns:
            (ReActContext with full state, final_response_text)
        """
        max_iter = max_iterations or self.max_iterations
        
        # Initialize context
        context = ReActContext(
            original_query=query,
            max_iterations=max_iter,
        )
        
        if self.verbose:
            console.print(Panel(query, title="[bold cyan]Query[/]", border_style="cyan"))
            console.print(f"[dim](max {max_iter} iterations)[/]\n")
        
        # Track gathered data for final response
        gathered_data = []
        
        # ReAct loop
        while context.can_continue():
            iteration_start = time.time()
            
            if self.verbose:
                console.print(f"\n[bold yellow]=== Iteration {context.iteration} ===[/]")
            
            # Get ReAct step from LLM
            step = self._get_react_step(context)
            
            if self.verbose:
                self._display_step(step)
            
            # Execute tool calls if any
            if step.tool_calls:
                executor = ReActExecutor(context, verbose=self.verbose)
                results = executor.execute_calls(step.tool_calls)
                context.last_tool_results = results
                
                # Track gathered data
                for r in results:
                    if r.success and r.data:
                        gathered_data.append({
                            "tool": r.tool,
                            "args": r.args,
                            "data": r.data,
                            "truncated": r.truncated,
                        })
            else:
                context.last_tool_results = []
            
            # Update trace summary from step
            context.trace_summary = step.trace_summary
            context.final_observation = step.observation
            
            # Check completion
            if step.is_complete:
                context.is_complete = True
                if self.verbose:
                    conf_val = step.confidence.value if hasattr(step.confidence, 'value') else step.confidence
                    console.print(f"\n[green]Sufficient (confidence: {conf_val})[/]")
                break
            
            # Move to next iteration
            context.increment()
            
            if self.verbose:
                elapsed = time.time() - iteration_start
                console.print(f"[dim]Iteration completed in {elapsed:.1f}s[/]")
        
        # Generate final response
        if self.verbose:
            console.print("\n[bold cyan]Generating final response...[/]")
        
        final_response = self._generate_final_response(context, gathered_data)
        
        if self.verbose:
            console.print("\n" + "=" * 80)
            console.print(Panel(
                Markdown(self._format_final_response(final_response)),
                title="[bold green]Final Response[/]",
                border_style="green",
            ))
        
        return context, self._format_final_response(final_response)
    
    def _get_react_step(self, context: ReActContext) -> ReActStep:
        """Get next ReAct step from LLM."""
        
        # Format tool results from last iteration
        tool_results_str = ""
        if context.last_tool_results:
            tool_results_str = format_tool_results(context.last_tool_results)
            if self.verbose and context.iteration > 1:
                console.print("[dim]Tool results for LLM:[/]")
                preview = tool_results_str[:800] + "..." if len(tool_results_str) > 800 else tool_results_str
                console.print(f"[dim]{preview}[/]")
        
        # Format resolved entities
        resolved_str = format_resolved_entities(context)
        
        # Build messages
        messages = format_react_messages(
            query=context.original_query,
            iteration=context.iteration,
            trace_summary=context.trace_summary,
            tool_results=tool_results_str,
            resolved_entities=resolved_str,
        )
        
        # Call LLM with Instructor
        step = self._client.chat.completions.create(
            model=self.config.get_planner_model(),
            messages=messages,
            response_model=ReActStep,
            temperature=self.config.get_planner_temperature(),
            max_tokens=self.config.get_planner_max_tokens(),
            max_retries=2,
        )
        
        return step
    
    def _generate_final_response(
        self, 
        context: ReActContext, 
        gathered_data: list[dict],
    ) -> FinalResponse:
        """Generate final response from gathered evidence."""
        
        # Format gathered data with focus on useful fields
        data_lines = []
        for item in gathered_data[-10:]:  # Last 10 tool results
            tool = item["tool"]
            data = item["data"]
            
            if isinstance(data, list) and len(data) > 0:
                data_lines.append(f"\n### {tool} ({len(data)} items)")
                
                # For AE results, extract and list the ae_labels
                if tool == "get_drug_adverse_events":
                    ae_labels = [d.get("ae_label", d.get("ae_key")) for d in data if isinstance(d, dict)]
                    if ae_labels:
                        data_lines.append(f"Adverse events: {', '.join(str(x) for x in ae_labels[:20])}")
                        if len(ae_labels) > 20:
                            data_lines.append(f"  ... and {len(ae_labels) - 20} more")
                else:
                    # For other tools, show key fields
                    for d in data[:10]:
                        if isinstance(d, dict):
                            # Prioritize name/label fields
                            for key in ["ae_label", "name", "gene_symbol", "label", "pathway"]:
                                if key in d:
                                    data_lines.append(f"  - {d[key]}")
                                    break
                            else:
                                compact = ", ".join(f"{k}={v}" for k, v in list(d.items())[:3])
                                data_lines.append(f"  - {compact}")
                    if len(data) > 10:
                        data_lines.append(f"  ... and {len(data) - 10} more")
                        
            elif isinstance(data, dict):
                data_lines.append(f"\n### {tool}")
                for k, v in data.items():
                    if isinstance(v, list):
                        data_lines.append(f"  {k}: {len(v)} items")
                    else:
                        data_lines.append(f"  {k}: {v}")
        
        gathered_str = "\n".join(data_lines) if data_lines else "(No data gathered)"
        
        messages = format_final_response_messages(
            query=context.original_query,
            trace_summary=context.trace_summary,
            final_observation=context.final_observation,
            gathered_data=gathered_str,
        )
        
        response = self._client.chat.completions.create(
            model=self.config.get_narrator_model(),
            messages=messages,
            response_model=FinalResponse,
            temperature=self.config.get_narrator_temperature(),
            max_tokens=self.config.get_narrator_max_tokens(),
            max_retries=2,
        )
        
        return response
    
    def _display_step(self, step: ReActStep) -> None:
        """Display ReAct step in terminal."""
        
        # Thought
        console.print("\n[bold magenta][Thought][/]")
        console.print(f"  {step.thought}")
        
        # Action
        console.print("\n[bold blue][Action][/]")
        if step.tool_calls:
            for call in step.tool_calls:
                console.print(f"  - {call.tool}({call.args})")
                console.print(f"    [dim]Reason: {call.reason}[/]")
        else:
            console.print("  [dim](No tool calls)[/]")
        
        # Observation
        console.print("\n[bold cyan][Observation][/]")
        console.print(f"  {step.observation}")
        
        # Confidence
        conf_val = step.confidence.value if hasattr(step.confidence, 'value') else step.confidence
        color = {"low": "red", "medium": "yellow", "high": "green"}.get(conf_val, "white")
        console.print(f"  [bold {color}]Confidence: {conf_val}[/]")
        
        if step.missing_info:
            console.print(f"  [dim]Missing: {', '.join(step.missing_info)}[/]")
    
    def _format_final_response(self, response: FinalResponse) -> str:
        """Format FinalResponse as markdown text."""
        lines = [
            "## Summary",
            response.summary,
            "",
            "## Key Findings",
        ]
        
        for finding in response.findings:
            lines.append(f"- {finding}")
        
        lines.extend([
            "",
            "## Evidence",
            response.evidence_summary,
        ])
        
        if response.limitations:
            lines.extend([
                "",
                "## Limitations",
            ])
            for lim in response.limitations:
                lines.append(f"- {lim}")
        
        conf_val = response.confidence.value if hasattr(response.confidence, 'value') else response.confidence
        lines.extend([
            "",
            f"**Confidence: {conf_val}**",
        ])
        
        return "\n".join(lines)
