#!/usr/bin/env python
"""
Test script for LLM layer components.

Usage:
    uv run python scripts/test_llm.py           # Run all tests
    uv run python scripts/test_llm.py --quick   # Health check only
    uv run python scripts/test_llm.py --demo    # Run interactive demo
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    pass

console = Console()


def check_servers() -> tuple[bool, bool]:
    """Check if LLM servers are running."""
    import httpx

    planner_ok = False
    narrator_ok = False

    try:
        r = httpx.get("http://127.0.0.1:8081/health", timeout=2)
        planner_ok = r.status_code == 200
    except Exception:
        pass

    try:
        r = httpx.get("http://127.0.0.1:8082/health", timeout=2)
        narrator_ok = r.status_code == 200
    except Exception:
        pass

    return planner_ok, narrator_ok


def test_planner_basic() -> bool:
    """Test planner can generate a simple response."""
    from openai import OpenAI

    console.print("Testing Planner (Phi-4-mini)...", style="bold blue")

    client = OpenAI(base_url="http://127.0.0.1:8081/v1", api_key="x")
    response = client.chat.completions.create(
        model="phi4mini",
        messages=[{"role": "user", "content": "Say hello in exactly 5 words."}],
        max_tokens=20,
    )
    text = response.choices[0].message.content
    console.print(f"  Response: {text}")
    return len(text) > 0


def test_narrator_basic() -> bool:
    """Test narrator can generate medical text."""
    from openai import OpenAI

    console.print("Testing Narrator (Phi-4)...", style="bold blue")

    client = OpenAI(base_url="http://127.0.0.1:8082/v1", api_key="x")
    response = client.chat.completions.create(
        model="phi4",
        messages=[{"role": "user", "content": "Define hypertension in one sentence."}],
        max_tokens=50,
    )
    text = response.choices[0].message.content
    console.print(f"  Response: {text}")
    return len(text) > 0


def test_planner_structured() -> bool:
    """Test planner can produce structured ToolPlan output."""
    from kg_ae.llm import LLMConfig, PlannerClient

    console.print("Testing Planner structured output...", style="bold blue")

    config = LLMConfig()
    planner = PlannerClient(config)

    plan = planner.plan("What adverse events might metformin cause?")

    console.print(f"  Generated {len(plan.calls)} tool calls:")
    for call in plan.calls:
        tool_name = call.tool.value if hasattr(call.tool, 'value') else call.tool
        console.print(f"    - {tool_name}: {call.reason}")

    return len(plan.calls) > 0


def test_narrator_evidence() -> bool:
    """Test narrator can summarize formatted evidence."""
    from kg_ae.llm import LLMConfig, NarratorClient

    console.print("Testing Narrator evidence summary...", style="bold blue")

    config = LLMConfig()
    narrator = NarratorClient(config)

    # Simulated evidence context
    evidence = """
## Query
What cardiac risks does metformin have?

## Resolved Entities
- Drug: Metformin (drug_key=123)

## Drug Targets
- Metformin -> AMPK (PRKAA1, gene_key=456)

## Adverse Events (FAERS)
- Lactic acidosis: 0.85 signal score
- Cardiac failure: 0.32 signal score

## Paths Found
1. Metformin -> AMPK -> Cellular metabolism -> Cardiac stress
"""

    summary = narrator.narrate(
        "What cardiac risks does metformin have?",
        evidence,
    )
    console.print(f"  Summary ({len(summary)} chars): {summary[:200]}...")
    return len(summary) > 50


def run_demo() -> None:
    """Run an interactive demo of the LLM pipeline."""
    from kg_ae.llm import LLMConfig, NarratorClient, PlannerClient

    console.print(Panel("LLM Layer Demo", style="bold green"))

    config = LLMConfig()
    planner = PlannerClient(config)
    narrator = NarratorClient(config)

    queries = [
        "What adverse events might metformin cause via its AMPK target?",
        "Does warfarin have bleeding risks through CYP2C9?",
        "Explain the cardiac effects of atorvastatin",
    ]

    for query in queries:
        console.print(f"\n[bold cyan]Query:[/] {query}")

        # Get plan
        console.print("[dim]Planning...[/dim]")
        plan = planner.plan(query)

        table = Table(title="Tool Plan", show_header=True)
        table.add_column("Tool")
        table.add_column("Reason")
        for call in plan.calls[:5]:  # Show first 5
            tool_name = call.tool.value if hasattr(call.tool, 'value') else call.tool
            table.add_row(tool_name, (call.reason or "")[:50])
        console.print(table)

        # Simulate evidence and narrate
        evidence = f"""
## Query
{query}

## Note
This is simulated evidence for demo purposes.
In production, tools would execute against the knowledge graph.
"""
        console.print("[dim]Summarizing...[/dim]")
        summary = narrator.narrate(query, evidence)
        console.print(Panel(summary[:500], title="Summary"))

        console.print("-" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Test LLM layer components")
    parser.add_argument("--quick", action="store_true", help="Health check only")
    parser.add_argument("--demo", action="store_true", help="Run interactive demo")
    args = parser.parse_args()

    console.print(Panel("LLM Layer Tests", style="bold"))

    # Check servers
    console.print("\n[bold]Server Health Check[/bold]")
    planner_ok, narrator_ok = check_servers()

    table = Table(show_header=False)
    table.add_column("Server")
    table.add_column("Status")
    table.add_row(
        "Planner (8081)",
        "[green]OK[/green]" if planner_ok else "[red]DOWN[/red]",
    )
    table.add_row(
        "Narrator (8082)",
        "[green]OK[/green]" if narrator_ok else "[red]DOWN[/red]",
    )
    console.print(table)

    if not (planner_ok and narrator_ok):
        console.print(
            "\n[red]Servers not running.[/red] Start with: "
            "[cyan].\\scripts\\start_llm_servers.ps1[/cyan]"
        )
        return 1

    if args.quick:
        console.print("\n[green]Quick check passed![/green]")
        return 0

    if args.demo:
        run_demo()
        return 0

    # Run all tests
    console.print("\n[bold]Component Tests[/bold]")
    results = []

    try:
        results.append(("Planner basic", test_planner_basic()))
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")
        results.append(("Planner basic", False))

    try:
        results.append(("Narrator basic", test_narrator_basic()))
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")
        results.append(("Narrator basic", False))

    try:
        results.append(("Planner structured", test_planner_structured()))
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")
        results.append(("Planner structured", False))

    try:
        results.append(("Narrator evidence", test_narrator_evidence()))
    except Exception as e:
        console.print(f"  [red]Error: {e}[/red]")
        results.append(("Narrator evidence", False))

    # Summary
    console.print("\n[bold]Results[/bold]")
    table = Table(show_header=True)
    table.add_column("Test")
    table.add_column("Result")
    for name, passed in results:
        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        table.add_row(name, status)
    console.print(table)

    passed = sum(1 for _, p in results if p)
    total = len(results)
    console.print(f"\n{passed}/{total} tests passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
