#!/usr/bin/env python
"""
Demo script for iterative reasoning pipeline.

Shows the multi-step refinement flow:
1. Query → Planner → Tools
2. Narrator evaluates sufficiency
3. If insufficient → Refinement query → Loop
4. Final response

Usage:
    uv run python scripts/query_iterative.py "What adverse events might metformin cause?"
    uv run python scripts/query_iterative.py --interactive
    uv run python scripts/query_iterative.py --max-iterations 5 "Complex drug interaction query"
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from kg_ae.llm import (
    LLMConfig,
    PlannerClient,
    NarratorClient,
    IterativeOrchestrator,
)

console = Console()


def execute_tools_for_query(query: str):
    """
    Placeholder tool executor that would actually run tools.
    
    In the real implementation, this would:
    1. Call planner.plan(query)
    2. Execute each tool in the plan
    3. Return list of ToolResult objects
    
    For now, this is a stub that returns mock results.
    """
    # Import the full query_kg logic here, or integrate with existing executor
    # This is just a placeholder to show the structure
    
    from dataclasses import dataclass
    from typing import Any
    
    @dataclass
    class MockToolResult:
        tool: str
        args: dict
        success: bool
        result: Any = None
        error: str | None = None
    
    # Mock results - replace with actual tool execution
    return [
        MockToolResult(
            tool="resolve_drugs",
            args={"names": ["metformin"]},
            success=True,
            result=[{"name": "metformin", "drug_key": 14042}],
        ),
        MockToolResult(
            tool="get_drug_adverse_events",
            args={"drug_key": 14042},
            success=True,
            result=[{"ae": "lactic acidosis", "frequency": 0.001}] * 84,
        ),
    ]


def run_query(query: str, max_iterations: int = 3, verbose: bool = True):
    """Execute iterative query."""
    
    # Initialize clients
    config = LLMConfig()
    planner = PlannerClient(config)
    narrator = NarratorClient(config)
    
    # Create orchestrator
    orchestrator = IterativeOrchestrator(
        planner_client=planner,
        narrator_client=narrator,
        max_iterations=max_iterations,
        verbose=verbose,
    )
    
    # Run iterative query
    context = orchestrator.query(
        query=query,
        tool_executor_fn=execute_tools_for_query,
        max_iterations=max_iterations,
    )
    
    # Display final results
    if verbose:
        console.print("\n" + "=" * 80)
        console.print(
            Panel(
                f"[bold]Status:[/] {context.completion_reason}\n"
                f"[bold]Iterations:[/] {len(context.iterations)}/{context.max_iterations}\n"
                f"[bold]Total Tools:[/] {len(context.get_all_tool_executions())}",
                title="📊 Iterative Query Summary",
                border_style="green",
            )
        )
        
        if context.final_response:
            console.print("\n[bold cyan]Final Response:[/]")
            console.print(Panel(Markdown(context.final_response), border_style="cyan"))
        
        # Show iteration breakdown
        console.print("\n[bold yellow]Iteration Breakdown:[/]")
        for iteration in context.iterations:
            status_icon = "✓" if iteration.sufficiency_evaluation and iteration.sufficiency_evaluation.status == "sufficient" else "⟳"
            console.print(
                f"  {status_icon} Iteration {iteration.iteration_number}: "
                f"{len(iteration.tool_executions)} tools, "
                f"{'sufficient' if iteration.sufficiency_evaluation and iteration.sufficiency_evaluation.can_answer_with_current_data else 'needs more info'}"
            )
    
    return context


def interactive_mode(max_iterations: int = 3):
    """Run in interactive mode."""
    console.print(
        Panel(
            "[bold cyan]Iterative Query Pipeline[/]\n\n"
            f"Max iterations: {max_iterations}\n"
            "Type 'quit' or 'exit' to stop\n"
            "Type 'set-max N' to change max iterations",
            title="🔄 Interactive Mode",
            border_style="cyan",
        )
    )
    
    current_max = max_iterations
    
    while True:
        try:
            query = console.input("\n[bold green]Query>[/] ").strip()
            
            if not query:
                continue
            
            if query.lower() in ("quit", "exit"):
                console.print("[yellow]Goodbye![/]")
                break
            
            if query.lower().startswith("set-max "):
                try:
                    new_max = int(query.split()[1])
                    if 1 <= new_max <= 10:
                        current_max = new_max
                        console.print(f"[green]✓ Max iterations set to {current_max}[/]")
                    else:
                        console.print("[red]Max iterations must be 1-10[/]")
                except (IndexError, ValueError):
                    console.print("[red]Usage: set-max N (where N is 1-10)[/]")
                continue
            
            # Run query
            run_query(query, max_iterations=current_max, verbose=True)
            
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted - type 'quit' to exit[/]")
        except Exception as e:
            console.print(f"[bold red]Error:[/] {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Iterative reasoning query pipeline with multi-step refinement"
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Query to execute (or use --interactive)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Run in interactive mode",
    )
    parser.add_argument(
        "--max-iterations",
        "-m",
        type=int,
        default=3,
        help="Maximum iterations before forcing final answer (1-10, default: 3)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only show final response",
    )
    
    args = parser.parse_args()
    
    # Validate max iterations
    if not 1 <= args.max_iterations <= 10:
        console.print("[red]Error: max-iterations must be between 1 and 10[/]")
        sys.exit(1)
    
    # Run mode
    if args.interactive:
        interactive_mode(max_iterations=args.max_iterations)
    elif args.query:
        run_query(args.query, max_iterations=args.max_iterations, verbose=not args.quiet)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
