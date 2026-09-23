"""Scripted walkthrough for showing the agent in a meeting.

    uv run pv demo              all five cases, pausing between each
    uv run pv demo --no-pause   straight through
    uv run pv demo --only 3     one case

Each case states what it is meant to prove before it runs, so the terminal explains itself
while it works.
"""

from __future__ import annotations

import time

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from pv_agent.chat import ask, show_network

console = Console()

CASES: list[tuple[str, str, str]] = [
    (
        "Spelling and the systemic label",
        "Is there a drug interaction between cyclosporin and posaconazole? "
        "What is the precise mechanism and what are the potential clinical consequences?",
        "'cyclosporin' is not a spelling any database indexes, and openFDA returns eye drops "
        "first for this drug. Watch the resolve step fix the name and the FDA label step land "
        "on the systemic product.",
    ),
    (
        "EU labels, not just US",
        "What does the EMA product information say about the letermovir and cyclosporine dose adjustment?",
        "The US label says to reduce the letermovir dose but gives no paediatric figure. The EU "
        "SmPC does. This is the gap web search alone would not close.",
    ),
    (
        "Three drugs at once",
        "Are there interactions between cyclosporin, posaconazole and letermovir?",
        "Three drugs means twelve retrievals running in parallel, then pairwise co-report "
        "counts. Nothing about the triple combination is claimed, because no source covers it.",
    ),
    (
        "Refusing to invent",
        "What are the known interactions of zelmoxifene with warfarin?",
        "There is no such drug. The answer should say so and stop, not reach for a similar-sounding one.",
    ),
    (
        "Why does the adverse event happen",
        "Why does atorvastatin cause myopathy? Which genes and pathways are involved?",
        "The mechanistic branch: genetic variants with evidence levels from the pharmacogenomics "
        "knowledge base, the pathways those genes sit in from Reactome, and any curated causal "
        "chain from the adverse outcome pathway wiki. Watch for the evidence level on each claim.",
    ),
]


def run_demo(*, pause: bool = True, only: int | None = None) -> int:
    chosen = [CASES[only - 1]] if only else CASES
    console.print(
        Panel(
            "[bold]pv-agent demo[/bold]\n\n"
            "Every answer below is built from live API calls made while you watch: FDA labels, "
            "EMA SmPCs, FAERS, ChEMBL, Open Targets, DGIdb, Reactome, Europe PMC.\n"
            "No database, no cached corpus, nothing pre-computed.",
            border_style="blue",
        )
    )

    times: list[tuple[str, float]] = []
    for i, (title, question, why) in enumerate(chosen, start=1):
        console.print()
        console.print(Rule(f"[bold]{i}/{len(chosen)}  {title}[/bold]"))
        console.print(Panel(why, title="what to watch for", title_align="left", border_style="dim"))

        if pause:
            try:
                console.input("[dim]enter to run[/dim] ")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]stopped[/dim]")
                return 0

        start = time.monotonic()
        turn = ask(question, [])
        times.append((title, time.monotonic() - start))
        show_network(turn)

    console.print()
    console.print(Rule("summary"))
    table = Table(show_edge=False, pad_edge=False)
    table.add_column("case")
    table.add_column("time", justify="right")
    for title, seconds in times:
        table.add_row(title, f"{seconds:.0f}s")
    console.print(table)
    return 0
