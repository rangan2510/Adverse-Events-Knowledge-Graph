#!/usr/bin/env python
"""
Natural-language query script for the Drug-AE Knowledge Graph.

Runs a LangChain/LangGraph ReAct agent over the file-based JSON graph. The LLM
is reached through one OpenAI-compatible endpoint (OpenRouter in dev, a local
server in deployment). Use --ensemble N for self-consistency reconciliation.

Usage:
    uv run python scripts/query_react.py "What gene does atorvastatin target?"
    uv run python scripts/query_react.py --ensemble 3 "AEs shared by statins?"
    uv run python scripts/query_react.py --interactive
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.panel import Panel

from kg_ae.llm import run_agent
from kg_ae.llm.llm_client import llm_summary

console = Console()


def run_query(query: str, ensemble: int | None, max_iterations: int | None, verbose: bool = True) -> None:
    if verbose:
        console.print(f"[dim]{llm_summary()}[/]")
    result = run_agent(query, ensemble_size=ensemble, max_iterations=max_iterations)
    if verbose and result.tool_calls:
        console.print(f"[dim]tools used: {', '.join(result.tool_calls)}[/]")
    console.print()
    console.print(Panel(result.answer, title="Answer", border_style="green"))


def interactive_mode(ensemble: int | None, max_iterations: int | None) -> None:
    console.print(
        Panel(
            "[bold cyan]Pharmacovigilance Query Interface[/]\n\n"
            "Ask about drugs, targets, pathways, diseases, and adverse events.\n"
            "Answers are grounded in the curated knowledge graph.\n\n"
            "Type 'quit' or 'exit' to stop.",
            title="KG Agent",
            border_style="cyan",
        )
    )
    while True:
        try:
            query = console.input("\n[bold green]Query>[/] ").strip()
            if not query:
                continue
            if query.lower() in ("quit", "exit", "q"):
                console.print("[dim]Goodbye![/]")
                break
            run_query(query, ensemble, max_iterations)
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted[/]")
            break
        except Exception as e:  # noqa: BLE001 - surface any agent error to the user
            console.print(f"[red]Error: {e}[/]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge graph agent query")
    parser.add_argument("query", nargs="?", help="Query to execute (omit for interactive mode)")
    parser.add_argument("--ensemble", "-e", type=int, default=None, help="Number of agents to reconcile")
    parser.add_argument("--max-iterations", "-n", type=int, default=None, help="Max ReAct iterations")
    parser.add_argument("--interactive", "-i", action="store_true", help="Run in interactive mode")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output")
    args = parser.parse_args()

    if args.interactive or not args.query:
        interactive_mode(args.ensemble, args.max_iterations)
    else:
        run_query(args.query, args.ensemble, args.max_iterations, verbose=not args.quiet)


if __name__ == "__main__":
    main()
