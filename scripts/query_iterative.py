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
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from kg_ae.llm import (
    IterativeOrchestrator,
    LLMConfig,
    NarratorClient,
    PlannerClient,
)
from kg_ae.llm.executor import ToolExecutor

console = Console()

# Module-level executor holder (reusable across iterations)
_tool_executor: ToolExecutor | None = None


@dataclass
class ToolResult:
    """Result from a single tool execution."""
    tool: str
    args: dict
    success: bool
    result: Any = None
    error: str | None = None
    reason: str | None = None


def _init_executor():
    """Initialize or reuse the ToolExecutor (persists resolved keys across iterations)."""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor(conn=None)
    return _tool_executor


def _serialize_item(item: Any) -> Any:
    """Convert dataclass / complex objects to JSON-safe dicts."""
    if item is None:
        return None
    if isinstance(item, (str, int, float, bool)):
        return item
    if isinstance(item, (list, tuple)):
        return [_serialize_item(i) for i in item]
    if isinstance(item, dict):
        return {k: _serialize_item(v) for k, v in item.items()}
    if hasattr(item, "__dataclass_fields__"):
        return {
            k: _serialize_item(getattr(item, k))
            for k in item.__dataclass_fields__
        }
    return str(item)


def _summarize_for_context(tool_name: str, result: Any) -> Any:
    """Truncate large results so they fit in LLM context."""
    MAX_ITEMS = 100
    serialized = _serialize_item(result)
    if isinstance(serialized, list) and len(serialized) > MAX_ITEMS:
        return serialized[:MAX_ITEMS]
    return serialized


def _accumulate_resolved_keys(executor: ToolExecutor, tool, result):
    """
    Store resolved entity keys so subsequent tool calls can use them.

    Handles the actual return types from tool functions:
    - resolve_drugs returns dict[str, ResolvedEntity|None]
    - resolve_genes returns dict[str, ResolvedEntity|None]
    - resolve_diseases returns dict[str, ResolvedEntity|None]
    - resolve_adverse_events returns dict[str, ResolvedEntity|None]
    """
    from kg_ae.llm.schemas import ToolName

    try:
        if tool == ToolName.RESOLVE_DRUGS and isinstance(result, dict):
            for name, entity in result.items():
                if entity is not None and hasattr(entity, "key"):
                    executor.resolved.drug_keys[name.lower()] = entity.key
        elif tool == ToolName.RESOLVE_GENES and isinstance(result, dict):
            for symbol, entity in result.items():
                if entity is not None and hasattr(entity, "key"):
                    executor.resolved.gene_keys[symbol.upper()] = entity.key
        elif tool == ToolName.RESOLVE_DISEASES and isinstance(result, dict):
            for term, entity in result.items():
                if entity is not None and hasattr(entity, "key"):
                    executor.resolved.disease_keys[term.lower()] = entity.key
        elif tool == ToolName.RESOLVE_ADVERSE_EVENTS and isinstance(result, dict):
            for term, entity in result.items():
                if entity is not None and hasattr(entity, "key"):
                    executor.resolved.ae_keys[term.lower()] = entity.key
    except Exception:
        pass  # Best-effort: don't fail the tool call over accumulation


def execute_tools_for_plan(plan):
    """
    Execute tools from a ToolPlan against the real database.

    Takes a ToolPlan object (with thought, calls, stop_conditions)
    and executes each tool call via ToolExecutor, returning results.
    """
    executor = _init_executor()
    results = []

    for call in plan.calls:
        from kg_ae.llm.executor import TOOL_REGISTRY

        tool_fn = TOOL_REGISTRY.get(call.tool)
        if tool_fn is None:
            results.append(ToolResult(
                tool=call.tool.value if hasattr(call.tool, "value") else str(call.tool),
                args=call.args,
                success=False,
                error=f"Unknown tool: {call.tool}",
                reason=call.reason,
            ))
            continue

        # Substitute resolved keys
        args = executor._substitute_keys(call.args)

        try:
            raw_result = tool_fn(**args)
            # Accumulate resolved keys for subsequent calls (best-effort)
            _accumulate_resolved_keys(executor, call.tool, raw_result)
            # Convert to serializable form for LLM context
            summarized = _summarize_for_context(
                call.tool.value if hasattr(call.tool, "value") else str(call.tool),
                raw_result,
            )
            results.append(ToolResult(
                tool=call.tool.value if hasattr(call.tool, "value") else str(call.tool),
                args=call.args,
                success=True,
                result=summarized,
                reason=call.reason,
            ))
        except Exception as e:
            results.append(ToolResult(
                tool=call.tool.value if hasattr(call.tool, "value") else str(call.tool),
                args=call.args,
                success=False,
                error=str(e),
                reason=call.reason,
            ))

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
