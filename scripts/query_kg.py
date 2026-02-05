#!/usr/bin/env python
"""
Full drug-AE query pipeline.

Query -> Planner LLM (Phi-4-mini) -> Tool Execution -> Narrator LLM (Phi-4) -> Response

Usage:
    uv run python scripts/query_kg.py "What adverse events might metformin cause?"
    uv run python scripts/query_kg.py --interactive

Options:
    --quiet        Only show final response
    --interactive  Interactive mode
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv(override=True)

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from kg_ae.llm import LLMConfig, NarratorClient, PlannerClient
from kg_ae.llm.schemas import ToolPlan
from kg_ae.tools import (
    build_subgraph,
    expand_gene_context,
    expand_mechanism,
    explain_paths,
    find_drug_to_ae_paths,
    get_claim_evidence,
    get_disease_genes,
    get_drug_adverse_events,
    get_drug_faers_signals,
    get_drug_label_sections,
    get_drug_profile,
    get_drug_targets,
    get_entity_claims,
    get_gene_diseases,
    get_gene_interactors,
    get_gene_pathways,
    resolve_adverse_events,
    resolve_diseases,
    resolve_drugs,
    resolve_genes,
)

console = Console()

# Tool registry - maps names to functions
TOOLS = {
    "resolve_drugs": resolve_drugs,
    "resolve_genes": resolve_genes,
    "resolve_diseases": resolve_diseases,
    "resolve_adverse_events": resolve_adverse_events,
    "get_drug_targets": get_drug_targets,
    "get_gene_pathways": get_gene_pathways,
    "get_gene_diseases": get_gene_diseases,
    "get_disease_genes": get_disease_genes,
    "get_gene_interactors": get_gene_interactors,
    "expand_mechanism": expand_mechanism,
    "expand_gene_context": expand_gene_context,
    "get_drug_adverse_events": get_drug_adverse_events,
    "get_drug_profile": get_drug_profile,
    "get_drug_label_sections": get_drug_label_sections,
    "get_drug_faers_signals": get_drug_faers_signals,
    "get_claim_evidence": get_claim_evidence,
    "get_entity_claims": get_entity_claims,
    "find_drug_to_ae_paths": find_drug_to_ae_paths,
    "explain_paths": explain_paths,
    "build_subgraph": build_subgraph,
}


@dataclass
class ToolResult:
    """Result from a single tool call."""
    tool: str
    args: dict
    success: bool
    result: Any = None
    error: str | None = None
    reason: str | None = None  # Why this tool was called
    
    def to_context(self, max_items: int = 50) -> str:
        """
        Format for narrator context.
        
        Args:
            max_items: Max items to include for list results (prevents context overflow)
        """
        if not self.success:
            return f"### {self.tool}\nError: {self.error}"
        
        # Format result based on type
        if self.result is None:
            return f"### {self.tool}\nNo results"
        
        if isinstance(self.result, list):
            total = len(self.result)
            if total == 0:
                return f"### {self.tool}\nNo results"
            
            # Smart sampling: group by drug/gene if applicable, sample evenly
            sampled_items = self._smart_sample(self.result, max_items)
            
            # Format list of dataclass objects
            items = []
            for item in sampled_items:
                if hasattr(item, "__dataclass_fields__"):
                    items.append(self._format_dataclass(item))
                else:
                    items.append(str(item))
            
            truncation_note = ""
            if total > len(sampled_items):
                truncation_note = f"\n[Showing {len(sampled_items)} of {total} results - sampled across all entities]"
            
            return f"### {self.tool}\n" + "\n".join(f"- {i}" for i in items) + truncation_note
        
        if isinstance(self.result, dict):
            # Format dict results
            total = len(self.result)
            lines = [f"- {k}: {v}" for k, v in list(self.result.items())[:max_items]]
            truncation_note = f"\n[Showing {max_items} of {total} entries]" if total > max_items else ""
            return f"### {self.tool}\n" + "\n".join(lines) + truncation_note
        
        if hasattr(self.result, "__dataclass_fields__"):
            return f"### {self.tool}\n" + self._format_dataclass(self.result)
        
        return f"### {self.tool}\n{self.result}"
    
    def _smart_sample(self, items: list, max_items: int) -> list:
        """
        Smart sample from list - groups by drug/gene key and samples evenly.
        
        For multi-drug AE queries, this ensures each drug gets representation
        instead of just showing the first N items (which would be all one drug).
        """
        if len(items) <= max_items:
            return items
        
        # Try to group by common keys (drug_key, drug_name, gene_key, etc.)
        group_keys = ["drug_key", "drug_name", "gene_key", "gene_symbol"]
        
        for group_key in group_keys:
            # Check if items have this attribute
            if items and hasattr(items[0], group_key):
                groups = {}
                for item in items:
                    key_val = getattr(item, group_key, None)
                    if key_val not in groups:
                        groups[key_val] = []
                    groups[key_val].append(item)
                
                # If we have multiple groups, sample evenly
                if len(groups) > 1:
                    sampled = []
                    items_per_group = max(1, max_items // len(groups))
                    
                    for _group_val, group_items in groups.items():
                        sampled.extend(group_items[:items_per_group])
                    
                    # If we have room for more, add extras
                    remaining = max_items - len(sampled)
                    if remaining > 0:
                        all_remaining = []
                        for _group_val, group_items in groups.items():
                            all_remaining.extend(group_items[items_per_group:])
                        sampled.extend(all_remaining[:remaining])
                    
                    return sampled[:max_items]
        
        # Fallback to simple truncation
        return items[:max_items]
    
    def _format_dataclass(self, obj) -> str:
        """Format a dataclass object as a string."""
        parts = []
        for fname in obj.__dataclass_fields__:
            val = getattr(obj, fname)
            if val is not None:
                parts.append(f"{fname}={val}")
        return ", ".join(parts)


@dataclass 
class ExecutionContext:
    """Tracks resolved keys during execution."""
    drug_keys: dict[str, int] = field(default_factory=dict)
    gene_keys: dict[str, int] = field(default_factory=dict)
    disease_keys: dict[str, int] = field(default_factory=dict)
    ae_keys: dict[str, int] = field(default_factory=dict)
    
    def substitute_args(self, args: dict) -> dict:
        """Substitute placeholder keys with resolved values.
        
        The planner often uses indices (0, 1, 2, 3) as placeholders for drugs
        that will be resolved. This maps those indices to actual resolved keys.
        
        Examples:
            drug_key=0 -> first resolved drug key
            drug_key=1 -> second resolved drug key
            drug_key="metformin" -> look up by name
        """
        result = {}
        for key, value in args.items():
            if key == "drug_key" and isinstance(value, (int, str)):
                # Handle integer placeholders (0, 1, 2, 3...) - map to resolved keys by index
                if isinstance(value, int) and value < 100:  # Small int = likely placeholder
                    resolved_keys = list(self.drug_keys.values())
                    if value < len(resolved_keys):
                        result[key] = resolved_keys[value]
                    elif resolved_keys:
                        # Fallback to first resolved key if index out of range
                        result[key] = resolved_keys[0]
                    else:
                        result[key] = value
                # Handle string name lookup
                elif isinstance(value, str) and value.lower() in self.drug_keys:
                    result[key] = self.drug_keys[value.lower()]
                else:
                    result[key] = value
                    
            elif key == "gene_key" and isinstance(value, (int, str)):
                if isinstance(value, int) and value < 100:
                    resolved_keys = list(self.gene_keys.values())
                    if value < len(resolved_keys):
                        result[key] = resolved_keys[value]
                    elif resolved_keys:
                        result[key] = resolved_keys[0]
                    else:
                        result[key] = value
                elif isinstance(value, str) and value.upper() in self.gene_keys:
                    result[key] = self.gene_keys[value.upper()]
                else:
                    result[key] = value
                    
            elif key == "disease_key" and isinstance(value, (int, str)):
                if isinstance(value, int) and value < 100:
                    resolved_keys = list(self.disease_keys.values())
                    if value < len(resolved_keys):
                        result[key] = resolved_keys[value]
                    elif resolved_keys:
                        result[key] = resolved_keys[0]
                    else:
                        result[key] = value
                elif isinstance(value, str) and value.lower() in self.disease_keys:
                    result[key] = self.disease_keys[value.lower()]
                else:
                    result[key] = value
                    
            elif key == "ae_key" and isinstance(value, (int, str)):
                if isinstance(value, int) and value < 100:
                    resolved_keys = list(self.ae_keys.values())
                    if value < len(resolved_keys):
                        result[key] = resolved_keys[value]
                    elif resolved_keys:
                        result[key] = resolved_keys[0]
                    else:
                        result[key] = value
                elif isinstance(value, str) and value.lower() in self.ae_keys:
                    result[key] = self.ae_keys[value.lower()]
                else:
                    result[key] = value
                    
            elif key == "drug_keys" and isinstance(value, list):
                result[key] = list(self.drug_keys.values()) or value
            elif key == "gene_keys" and isinstance(value, list):
                result[key] = list(self.gene_keys.values()) or value
            else:
                result[key] = value
        return result
    
    def update_from_result(self, tool: str, result: Any) -> None:
        """Update resolved keys from tool results."""
        if tool == "resolve_drugs" and isinstance(result, dict):
            for name, resolved in result.items():
                if resolved and hasattr(resolved, 'key'):
                    self.drug_keys[name.lower()] = resolved.key
        elif tool == "resolve_genes" and isinstance(result, dict):
            for sym, resolved in result.items():
                if resolved and hasattr(resolved, 'key'):
                    self.gene_keys[sym.upper()] = resolved.key
        elif tool == "resolve_diseases" and isinstance(result, dict):
            for term, resolved in result.items():
                if resolved and hasattr(resolved, 'key'):
                    self.disease_keys[term.lower()] = resolved.key
        elif tool == "resolve_adverse_events" and isinstance(result, dict):
            for term, resolved in result.items():
                if resolved and hasattr(resolved, 'key'):
                    self.ae_keys[term.lower()] = resolved.key


def normalize_args(tool_name: str, args: dict) -> dict:
    """
    Normalize tool arguments - handle common planner mistakes.
    
    Fixes:
    - drug_keys (list) -> multiple calls or first item for drug_key
    - gene_keys (list) -> gene_key
    """
    result = dict(args)
    
    # Handle plural -> singular key mapping for tools that expect single key
    singular_tools = {
        "get_drug_adverse_events": ("drug_keys", "drug_key"),
        "get_drug_targets": ("drug_keys", "drug_key"),
        "get_drug_profile": ("drug_keys", "drug_key"),
        "get_drug_label_sections": ("drug_keys", "drug_key"),
        "get_drug_faers_signals": ("drug_keys", "drug_key"),
        "get_gene_pathways": ("gene_keys", "gene_key"),
        "get_gene_diseases": ("gene_keys", "gene_key"),
        "get_gene_interactors": ("gene_keys", "gene_key"),
        "get_disease_genes": ("disease_keys", "disease_key"),
    }
    
    if tool_name in singular_tools:
        plural_key, singular_key = singular_tools[tool_name]
        if plural_key in result and singular_key not in result:
            # Convert list to first item (will be expanded in execute_tool_expanded)
            keys = result.pop(plural_key)
            if isinstance(keys, list) and len(keys) > 0:
                result[singular_key] = keys[0]
                result["_remaining_keys"] = keys[1:] if len(keys) > 1 else []
    
    return result


def execute_tool(tool_name: str, args: dict, ctx: ExecutionContext, reason: str | None = None) -> ToolResult:
    """Execute a single tool and return result."""
    tool_fn = TOOLS.get(tool_name)
    if tool_fn is None:
        return ToolResult(
            tool=tool_name,
            args=args,
            success=False,
            error=f"Unknown tool: {tool_name}",
            reason=reason,
        )
    
    # Normalize args (fix planner mistakes like drug_keys -> drug_key)
    norm_args = normalize_args(tool_name, args)
    remaining_keys = norm_args.pop("_remaining_keys", [])
    
    # Substitute resolved keys
    subst_args = ctx.substitute_args(norm_args)
    
    try:
        result = tool_fn(**subst_args)
        
        # If there are remaining keys (from plural->singular conversion), 
        # execute for each resolved key and combine results
        if remaining_keys and isinstance(result, list):
            # Get the resolved keys from context based on tool type
            resolved_keys = []
            if "drug" in tool_name.lower():
                resolved_keys = list(ctx.drug_keys.values())
            elif "gene" in tool_name.lower():
                resolved_keys = list(ctx.gene_keys.values())
            elif "disease" in tool_name.lower():
                resolved_keys = list(ctx.disease_keys.values())
            
            # Skip first key (already processed), process rest
            for resolved_key in resolved_keys[1:]:
                extra_args = dict(norm_args)
                # Find the _key arg and set to resolved key
                for k in extra_args:
                    if k.endswith("_key"):
                        extra_args[k] = resolved_key
                        break
                extra_result = tool_fn(**extra_args)
                if isinstance(extra_result, list):
                    result.extend(extra_result)
        
        ctx.update_from_result(tool_name, result)
        return ToolResult(
            tool=tool_name,
            args=subst_args,
            success=True,
            result=result,
            reason=reason,
        )
    except Exception as e:
        return ToolResult(
            tool=tool_name,
            args=subst_args,
            success=False,
            error=str(e),
            reason=reason,
        )


def execute_plan(plan: ToolPlan, verbose: bool = True) -> list[ToolResult]:
    """Execute all tools in a plan."""
    ctx = ExecutionContext()
    results = []
    
    for i, call in enumerate(plan.calls, 1):
        tool_name = call.tool if isinstance(call.tool, str) else call.tool.value
        reason = call.reason
        
        if verbose:
            reason_str = f" - {reason}" if reason else ""
            console.print(f"[dim][{i}/{len(plan.calls)}] {tool_name}{reason_str}[/dim]")
        
        result = execute_tool(tool_name, call.args, ctx, reason=reason)
        results.append(result)
        
        if verbose:
            if result.success:
                # Show brief result
                if isinstance(result.result, list):
                    console.print(f"  [green]OK[/green] - {len(result.result)} results")
                elif isinstance(result.result, dict):
                    console.print(f"  [green]OK[/green] - {len(result.result)} items")
                else:
                    console.print("  [green]OK[/green]")
            else:
                console.print(f"  [red]ERROR[/red]: {result.error}")
    
    return results


def format_context_for_narrator(
    query: str,
    plan: ToolPlan,
    results: list[ToolResult],
    max_items_per_tool: int = 50,
) -> str:
    """
    Format everything for the narrator LLM.
    
    Args:
        query: Original user query
        plan: Tool execution plan
        results: Tool execution results
        max_items_per_tool: Limit items per tool to prevent context overflow
    """
    sections = []
    
    sections.append(f"## Query\n{query}")
    
    # Plan summary
    plan_lines = []
    for call in plan.calls:
        tool_name = call.tool if isinstance(call.tool, str) else call.tool.value
        plan_lines.append(f"- {tool_name}: {call.reason or 'no reason given'}")
    sections.append("## Execution Plan\n" + "\n".join(plan_lines))
    
    # Tool results (with truncation)
    sections.append("## Tool Results")
    for result in results:
        context = result.to_context(max_items=max_items_per_tool)
        sections.append(context)
    
    return "\n\n".join(sections)


def run_query(query: str, verbose: bool = True) -> str:
    """
    Run full query pipeline and return narrator response.
    
    Args:
        query: User query
        verbose: Show detailed output
    """
    config = LLMConfig()
    planner = PlannerClient(config)
    narrator = NarratorClient(config)
    
    # Phase 1: Planning
    if verbose:
        console.print(Panel(query, title="Query", border_style="cyan"))
        console.print("\n[bold blue]Phase 1: Planning[/bold blue]")
    
    plan = planner.plan(query)
    
    if verbose:
        table = Table(title="Tool Plan", show_header=True)
        table.add_column("#", style="dim")
        table.add_column("Tool")
        table.add_column("Arguments")
        table.add_column("Reason")
        for i, call in enumerate(plan.calls, 1):
            tool_name = call.tool if isinstance(call.tool, str) else call.tool.value
            args_str = json.dumps(call.args, default=str)[:40]
            table.add_row(str(i), tool_name, args_str, (call.reason or "")[:30])
        console.print(table)
    
    # Phase 2: Execution
    if verbose:
        console.print("\n[bold blue]Phase 2: Tool Execution[/bold blue]")
    
    results = execute_plan(plan, verbose=verbose)
    
    # Show detailed results
    if verbose:
        console.print("\n[bold blue]Tool Outputs[/bold blue]")
        for result in results:
            if result.success:
                panel_content = result.to_context().replace(f"### {result.tool}\n", "")
                console.print(Panel(
                    panel_content[:1000] + ("..." if len(panel_content) > 1000 else ""),
                    title=f"[green]{result.tool}[/green]",
                    border_style="green",
                ))
            else:
                console.print(Panel(
                    f"Error: {result.error}",
                    title=f"[red]{result.tool}[/red]",
                    border_style="red",
                ))
    
    # Phase 3: Narration
    if verbose:
        console.print("\n[bold blue]Phase 3: Generating Response[/bold blue]")
    
    context = format_context_for_narrator(query, plan, results)
    
    if verbose:
        console.print("[dim]Sending to narrator...[/dim]")
    
    response = narrator.narrate(query, context)
    
    if verbose:
        console.print(Panel(
            Markdown(response),
            title="[bold green]Response[/bold green]",
            border_style="green",
        ))
    
    return response


def interactive_mode():
    """Run interactive query loop."""
    console.print(Panel(
        "Drug-AE Knowledge Graph Query System\n"
        "Type a question, or 'quit' to exit.",
        title="Interactive Mode",
        border_style="blue",
    ))
    
    while True:
        try:
            query = console.input("\n[bold cyan]Query>[/bold cyan] ").strip()
            if not query:
                continue
            if query.lower() in ("quit", "exit", "q"):
                console.print("[dim]Goodbye![/dim]")
                break
            
            run_query(query, verbose=True)
            
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted[/dim]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


def main():
    parser = argparse.ArgumentParser(description="Query the Drug-AE Knowledge Graph")
    parser.add_argument("query", nargs="?", help="Query to run")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only show final response")
    args = parser.parse_args()
    
    if args.interactive:
        interactive_mode()
    elif args.query:
        response = run_query(args.query, verbose=not args.quiet)
        if args.quiet:
            print(response)
    else:
        parser.print_help()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
