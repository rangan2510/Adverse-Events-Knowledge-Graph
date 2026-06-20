#!/usr/bin/env python
"""
Compare Mistral model variants on the pharmacovigilance agent.

Runs a fixed set of representative queries through each candidate model (single
agent, no ensemble, for a fair per-model comparison) and records the answer,
the tools the model chose to call, and the wall-clock latency. This is an
A/B harness for picking the deployment model: all candidates are open-weight
Mistral variants (compliance-safe).

Usage:
    uv run python scripts/compare_models.py
    uv run python scripts/compare_models.py --models mistralai/ministral-8b-2512
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from kg_ae.llm.agent import run_agent

console = Console()

# Open-weight, tool-calling Mistral variants available on OpenRouter.
DEFAULT_MODELS = [
    "mistralai/mistral-small-3.2-24b-instruct",  # current default
    "mistralai/ministral-8b-2512",               # newer, efficient
    "mistralai/mistral-small-2603",              # "Mistral Small 4" (newest small)
    "mistralai/mistral-large-2512",              # most capable, Apache 2.0
]

# Representative queries spanning the agent's insight capabilities.
QUERIES = [
    "Why might atorvastatin cause myopathy? Explain the mechanism.",
    "What adverse events do statins share, and through which targets?",
    "What happens if you combine warfarin and aspirin?",
    "What genes are associated with Parkinson disease, and do any approved drugs target them?",
]


def run_comparison(models: list[str], queries: list[str]) -> list[dict]:
    rows: list[dict] = []
    for model in models:
        for q in queries:
            console.print(f"[dim]-> {model}  |  {q[:60]}...[/]")
            start = time.time()
            try:
                result = run_agent(q, ensemble_size=1, model=model)
                elapsed = time.time() - start
                rows.append(
                    {
                        "model": model,
                        "query": q,
                        "answer": result.answer,
                        "tools": result.tool_calls,
                        "n_tools": len(result.tool_calls),
                        "latency_s": round(elapsed, 1),
                        "error": None,
                    }
                )
            except Exception as e:  # noqa: BLE001 - record and continue
                rows.append(
                    {
                        "model": model,
                        "query": q,
                        "answer": "",
                        "tools": [],
                        "n_tools": 0,
                        "latency_s": round(time.time() - start, 1),
                        "error": str(e),
                    }
                )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    ap.add_argument("--out", default="model_comparison.json")
    args = ap.parse_args()

    rows = run_comparison(args.models, QUERIES)

    Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")

    table = Table(title="Model comparison (single agent)")
    table.add_column("Model", style="cyan")
    table.add_column("Query", overflow="ellipsis", max_width=40)
    table.add_column("Tools", justify="right")
    table.add_column("Latency", justify="right")
    table.add_column("OK", justify="center")
    for r in rows:
        table.add_row(
            r["model"].split("/")[-1],
            r["query"],
            str(r["n_tools"]),
            f"{r['latency_s']}s",
            "[green]y[/]" if not r["error"] else "[red]n[/]",
        )
    console.print(table)
    console.print(f"[dim]Full answers written to {args.out}[/]")


if __name__ == "__main__":
    main()
