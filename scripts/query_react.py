#!/usr/bin/env python
"""
ReAct-style iterative query script.

Clean implementation of Thought -> Action -> Observation loop
with single LLM (Groq) and context-efficient trace management.

Usage:
    uv run python scripts/query_react.py "What adverse events do cyclosporine and tacrolimus share?"
    uv run python scripts/query_react.py --max-iterations 5 "Query here"
    uv run python scripts/query_react.py --interactive
"""

from __future__ import annotations

# Load environment before anything else
from dotenv import load_dotenv
load_dotenv(override=True)

import argparse
import sys

from rich.console import Console
from rich.panel import Panel

from kg_ae.llm import LLMConfig, ReActOrchestrator

console = Console()


def run_query(query: str, max_iterations: int = 10, verbose: bool = True):
    """Execute ReAct query loop."""
    
    # Show config
    config = LLMConfig()
    if verbose:
        console.print(f"[dim]Provider: {config.provider}[/]")
        console.print(f"[dim]Model: {config.get_planner_model()}[/]")
        console.print(f"[dim]Max tokens: {config.get_planner_max_tokens()}[/]")
        console.print()
    
    # Create orchestrator
    orchestrator = ReActOrchestrator(
        config=config,
        max_iterations=max_iterations,
        verbose=verbose,
    )
    
    # Run query
    context, final_response = orchestrator.query(query, max_iterations=max_iterations)
    
    return context, final_response


def interactive_mode(max_iterations: int = 10):
    """Run in interactive mode."""
    console.print(Panel(
        "[bold cyan]ReAct Query Interface[/]\n\n"
        "Enter pharmacovigilance queries about drugs and adverse events.\n"
        "The system will iteratively gather evidence and synthesize a response.\n\n"
        "Type 'quit' or 'exit' to stop.",
        title="ReAct Mode",
        border_style="cyan",
    ))
    
    while True:
        try:
            query = console.input("\n[bold green]Query>[/] ").strip()
            
            if not query:
                continue
            
            if query.lower() in ("quit", "exit", "q"):
                console.print("[dim]Goodbye![/]")
                break
            
            run_query(query, max_iterations=max_iterations)
            
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted[/]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")


def main():
    parser = argparse.ArgumentParser(
        description="ReAct-style iterative knowledge graph query"
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Query to execute (omit for interactive mode)"
    )
    parser.add_argument(
        "--max-iterations", "-n",
        type=int,
        default=10,
        help="Maximum iterations (default: 10)"
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run in interactive mode"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimal output"
    )
    
    args = parser.parse_args()
    
    if args.interactive or not args.query:
        interactive_mode(max_iterations=args.max_iterations)
    else:
        run_query(
            args.query,
            max_iterations=args.max_iterations,
            verbose=not args.quiet,
        )


if __name__ == "__main__":
    main()
