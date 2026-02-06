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

from dotenv import load_dotenv

load_dotenv(override=True)

import argparse
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from kg_ae.llm import (
    IterativeOrchestrator,
    LLMConfig,
    NarratorClient,
    PlannerClient,
)

console = Console()


def execute_tools_for_plan(plan):
    """
    Execute tools from a ToolPlan.
    
    Takes a ToolPlan object (with thought, calls, stop_conditions)
    and executes each tool call, returning results.
    
    Args:
        plan: ToolPlan object from planner
        
    Returns:
        list of ToolResult-like objects
    """
    from dataclasses import dataclass
    from typing import Any
    
    @dataclass
    class ToolResult:
        tool: str
        args: dict
        success: bool
        result: Any = None
        error: str | None = None
        reason: str | None = None
    
    results = []
    
    for call in plan.calls:
        # Mock execution - replace with actual tool implementation
        if call.tool == "resolve_drugs":
            result = ToolResult(
                tool=call.tool,
                args=call.args,
                success=True,
                result=[{"name": "metformin", "drug_key": 14042}],
                reason=call.reason,
            )
        elif call.tool == "get_drug_adverse_events":
            result = ToolResult(
                tool=call.tool,
                args=call.args,
                success=True,
                result=[{"ae": "lactic acidosis", "frequency": 0.001}] * 84,
                reason=call.reason,
            )
        elif call.tool == "get_drug_targets":
            result = ToolResult(
                tool=call.tool,
                args=call.args,
                success=True,
                result=[{"gene": "AMPK", "action": "activator"}],
                reason=call.reason,
            )
        elif call.tool == "expand_mechanism":
            result = ToolResult(
                tool=call.tool,
                args=call.args,
                success=True,
                result={"pathways": ["glucose metabolism", "lipid metabolism"]},
                reason=call.reason,
            )
        elif call.tool == "get_gene_pathways":
            result = ToolResult(
                tool=call.tool,
                args=call.args,
                success=True,
                result=[
                    {"pathway": "AMPK signaling pathway", "reactome_id": "R-HSA-380972"},
                    {"pathway": "Glucose metabolism", "reactome_id": "R-HSA-70326"},
                    {"pathway": "Mitochondrial biogenesis", "reactome_id": "R-HSA-1592230"},
                ],
                reason=call.reason,
            )
        elif call.tool == "resolve_genes":
            result = ToolResult(
                tool=call.tool,
                args=call.args,
                success=True,
                result=[{"name": "PRKAA1", "gene_key": 5562, "symbol": "AMPK"}],
                reason=call.reason,
            )
        elif call.tool == "get_gene_diseases":
            result = ToolResult(
                tool=call.tool,
                args=call.args,
                success=True,
                result=[
                    {"disease": "Type 2 Diabetes", "mondo_id": "MONDO:0005148"},
                    {"disease": "Metabolic syndrome", "mondo_id": "MONDO:0005152"},
                ],
                reason=call.reason,
            )
        elif call.tool == "get_drug_profile":
            result = ToolResult(
                tool=call.tool,
                args=call.args,
                success=True,
                result={
                    "name": "metformin",
                    "drug_class": "biguanide",
                    "indications": ["Type 2 Diabetes"],
                    "targets": ["AMPK", "Complex I"],
                },
                reason=call.reason,
            )
        else:
            result = ToolResult(
                tool=call.tool,
                args=call.args,
                success=False,
                error=f"Unknown tool: {call.tool}",
                reason=call.reason,
            )
        
        results.append(result)
    
    return results


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
        tool_executor_fn=execute_tools_for_plan,
        max_iterations=max_iterations,
    )
    
    # Display final results
    if verbose:
        console.print("\n" + "=" * 80)
        console.print(
            f"[bold green]Complete[/] ({len(context.iterations)} iterations, "
            f"{len(context.get_all_tool_executions())} total tools)"
        )
        
        if context.final_response:
            console.print("\n[bold cyan]Final Response:[/]")
            console.print(Markdown(context.final_response))
    
    return context


def interactive_mode(max_iterations: int = 3):
    """Run in interactive mode."""
    console.print(
        Panel(
            "[bold cyan]Query[/]\n\n"
            f"Max iterations: {max_iterations}\n"
            "Type 'quit' or 'exit' to stop\n"
            "Type 'set-max N' to change max iterations",
            title="Interactive Mode",
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
                        console.print(f"[green]\u2713 Max iterations set to {current_max}[/]")
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
        help="Maximum iterations before forcing final answer (1-20, default: 3)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only show final response",
    )
    
    args = parser.parse_args()
    
    # Validate max iterations
    if not 1 <= args.max_iterations <= 20:
        console.print("[red]Error: max-iterations must be between 1 and 20[/]")
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
