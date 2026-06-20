#!/usr/bin/env python
"""
Stress test: run a broad set of pharmacovigilance questions through the agent.

Exercises every capability type (mechanism, reverse lookup, polypharmacy, FAERS
signals, label sections, indirect PPI mechanism, unresolvable inputs, etc.) and
records the tools each query actually invoked plus latency. Designed to run
inside the Docker image where the graph is baked in.

Usage:
    uv run python scripts/stress_test.py
    docker run --rm --env-file .env kg-ae:latest \
        sh -c "python scripts/stress_test.py"   # if scripts are copied in
"""

from __future__ import annotations

import time

from rich.console import Console
from rich.table import Table

from kg_ae.llm.agent import run_agent

console = Console()

QUESTIONS = [
    # Mechanism / direct
    "What genes does atorvastatin target?",
    "Why might simvastatin cause rhabdomyolysis? Explain the mechanism.",
    "How does metformin work, and what does it target?",
    "What pathways are affected by ibuprofen's targets?",
    # Adverse events
    "What are the most common adverse events of warfarin?",
    "What FAERS disproportionality signals exist for clozapine?",
    "Does atorvastatin have a boxed warning or notable label sections?",
    # Reverse lookup (disease -> gene)
    "What genes are associated with Parkinson disease?",
    "Which genes drive Alzheimer disease, and do any approved drugs target them?",
    "What genes are linked to type 2 diabetes mellitus?",
    # Polypharmacy / DDI
    "What happens if you combine warfarin and aspirin?",
    "What adverse events are reported for the combination of clopidogrel and omeprazole?",
    "Is it risky to combine sildenafil with nitroglycerin?",
    # Shared / comparative
    "What adverse events do statins share, and through which targets?",
    "Compare the targets of ibuprofen and naproxen.",
    # Indirect mechanism (PPI)
    "Through which interacting genes might imatinib act beyond its direct targets?",
    # Mechanistic path to a specific AE
    "Why might haloperidol cause QT prolongation?",
    "Why might methotrexate cause hepatotoxicity?",
    # Robustness / negative cases
    "What does the drug 'foobarazole' target?",
    "What adverse events does aspirin cause that involve bleeding?",
]


def main() -> None:
    rows: list[dict] = []
    for i, q in enumerate(QUESTIONS, 1):
        console.print(f"[dim][{i}/{len(QUESTIONS)}] {q}[/]")
        start = time.time()
        try:
            result = run_agent(q, ensemble_size=1)
            rows.append(
                {
                    "q": q,
                    "tools": sorted(set(result.tool_calls)),
                    "n_tools": len(result.tool_calls),
                    "chars": len(result.answer),
                    "latency": round(time.time() - start, 1),
                    "ok": bool(result.answer),
                    "answer": result.answer,
                }
            )
        except Exception as e:  # noqa: BLE001
            rows.append(
                {
                    "q": q,
                    "tools": [],
                    "n_tools": 0,
                    "chars": 0,
                    "latency": round(time.time() - start, 1),
                    "ok": False,
                    "answer": f"ERROR: {e}",
                }
            )

    table = Table(title="Agent stress test")
    table.add_column("#", justify="right")
    table.add_column("Question", overflow="ellipsis", max_width=44)
    table.add_column("Tools", justify="right")
    table.add_column("Chars", justify="right")
    table.add_column("Lat", justify="right")
    table.add_column("OK", justify="center")
    for i, r in enumerate(rows, 1):
        table.add_row(
            str(i),
            r["q"],
            str(r["n_tools"]),
            str(r["chars"]),
            f"{r['latency']}s",
            "[green]y[/]" if r["ok"] else "[red]n[/]",
        )
    console.print(table)

    # Print each answer for qualitative review.
    for i, r in enumerate(rows, 1):
        console.rule(f"[bold]Q{i}: {r['q']}")
        console.print(f"[dim]tools: {', '.join(r['tools']) or '(none)'}[/]")
        console.print(r["answer"])


if __name__ == "__main__":
    main()
