"""Terminal front end.

    pv chat                  loop until /exit, memory in RAM
    pv ask "question"        one shot

Tool calls stream as they happen; the answer streams as it is written, then is re-rendered as
Markdown once verified.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from pv_agent import network
from pv_agent.config import get_settings
from pv_agent.graph import Event, Turn, run

# Answers contain arrows and dashes. When stdout is a file or a legacy Windows console, Python
# falls back to cp1252 and the print crashes after the whole graph has run. Force UTF-8 once.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

console = Console()

BANNER = """[bold]pv-agent[/bold]  pharmacovigilance over live sources
FDA labels, EMA SmPC, FAERS, ChEMBL, Open Targets, DGIdb, Reactome, Europe PMC, regulator web.
Commands: [cyan]/exit[/cyan]  [cyan]/clear[/cyan]  [cyan]/refs[/cyan] references  [cyan]/network[/cyan] relationships"""


class View:
    """Everything the screen shows while one question runs."""

    def __init__(self) -> None:
        self.stage = ""
        self.tools: list[tuple[str, str, str]] = []
        self.tokens: list[str] = []
        self.note = ""
        self.start = time.monotonic()

    def handle(self, e: Event) -> None:
        if e.kind == "stage":
            self.stage = e.text
            # Each model stage streams its own text; the reviewed answer replaces the draft.
            self.tokens.clear()
        elif e.kind == "tool":
            self.tools.append((e.stage, e.text, e.detail))
        elif e.kind == "token":
            self.tokens.append(e.text)
        elif e.kind == "note":
            self.note = e.text

    def render(self) -> Group:
        parts: list = []
        elapsed = f"{time.monotonic() - self.start:4.0f}s"
        parts.append(Spinner("dots", text=Text(f" {self.stage}  {elapsed}", style="bold cyan")))

        if self.tools:
            t = Table.grid(padding=(0, 1))
            t.add_column(style="dim", width=9)
            t.add_column()
            t.add_column(style="dim")
            for stage, name, detail in self.tools[-14:]:
                colour = "red" if detail in ("error", "no match") or "unavailable" in detail else "green"
                t.add_row(stage, name, Text(detail[:70], style=colour))
            parts.append(t)

        if self.tokens:
            parts.append(Rule(style="dim"))
            parts.append(Markdown("".join(self.tokens)))
        if self.note:
            parts.append(Text(self.note, style="dim"))
        return Group(*parts)


def ask(question: str, history: list[BaseMessage]) -> Turn:
    view = View()
    with Live(view.render(), console=console, refresh_per_second=8, transient=True) as live:

        def emit(e: Event) -> None:
            view.handle(e)
            live.update(view.render())

        turn = run(question, history, emit)

    elapsed = time.monotonic() - view.start
    console.print(
        Panel(
            Markdown(turn.answer or "_No answer was produced._"),
            title="answer",
            title_align="left",
            border_style="green",
        )
    )

    # Retrieval branches count as calls too; turn.tool_calls only counts what the model asked for.
    calls = len(view.tools)
    fixed = f", {len(turn.problems)} citation issue(s) fixed" if turn.problems else ""
    console.print(f"[dim]{elapsed:.0f}s, {calls} retrieval(s), {len(turn.refs)} reference(s){fixed}[/dim]")
    sources = ", ".join(sorted({r.source for r in turn.refs.values()}))
    console.print(f"[dim]sources: {sources}[/dim]\n")
    return turn


def show_network(turn: Turn | None) -> None:
    panel = network.render(network.collect(turn.evidence), turn.drugs) if turn else None
    console.print(panel if panel else "[dim]no relationships to show[/dim]")


def show_refs(turn: Turn | None) -> None:
    if not turn or not turn.refs:
        console.print("[dim]no references yet[/dim]")
        return
    t = Table(title="references", show_lines=False)
    t.add_column("id", style="cyan", no_wrap=True)
    t.add_column("source", style="dim")
    t.add_column("title")
    t.add_column("url", style="dim", overflow="fold")
    for rid, r in turn.refs.items():
        title = r.title + (f"  [red]({r.caution})[/red]" if r.caution else "")
        t.add_row(rid, r.source, title, r.url)
    console.print(t)


def chat() -> int:
    console.print(Panel(BANNER, border_style="blue"))
    history: list[BaseMessage] = []
    last: Turn | None = None
    while True:
        try:
            q = console.input("[bold blue]>[/bold blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0
        if not q:
            continue
        if q in ("/exit", "/quit"):
            return 0
        if q == "/clear":
            history.clear()
            last = None
            console.print("[dim]history cleared[/dim]")
            continue
        if q == "/refs":
            show_refs(last)
            continue
        if q == "/network":
            show_network(last)
            continue
        last = ask(q, history)
        history += [HumanMessage(q), AIMessage(last.answer)]
        # Keep memory bounded: last five exchanges.
        del history[:-10]


def set_keys(openrouter_key: str | None, tavily_key: str | None) -> bool:
    """Put command-line keys into the environment, where config.py reads them.

    A key given on the command line wins over one in .env. Returns False when the model runs on
    OpenRouter and no OpenRouter key is available from either place. A local server needs no key.
    """
    if openrouter_key:
        os.environ["OPENROUTER_API_KEY"] = openrouter_key
    if tavily_key:
        os.environ["TAVILY_API_KEY"] = tavily_key
    if "openrouter.ai" not in get_settings().llm_base_url:
        return True
    return bool(os.getenv("OPENROUTER_API_KEY"))


def use_model(model: str | None, local_url: str) -> None:
    """Point config.py at OpenRouter or a local llama.cpp server. None keeps .env as it is."""
    if model == "local":
        os.environ["PV_LLM_BASE_URL"] = local_url
        os.environ["PV_LLM_MODEL"] = "local"
    elif model == "openrouter":
        os.environ["PV_LLM_BASE_URL"] = "https://openrouter.ai/api/v1"


def main() -> int:
    keys = argparse.ArgumentParser(add_help=False)
    keys.add_argument("--openrouter-key", help="OpenRouter API key (needed with --model openrouter)")
    keys.add_argument("--tavily-key", help="Tavily API key (optional; without it web search is disabled)")
    keys.add_argument("--model", choices=["openrouter", "local"], help="where the model runs (default: .env)")
    keys.add_argument(
        "--local-url", default="http://127.0.0.1:8080/v1", help="llama.cpp server address for --model local"
    )

    p = argparse.ArgumentParser(prog="pv", description="Pharmacovigilance agent over live sources.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("chat", parents=[keys], help="interactive session, memory in RAM")
    a = sub.add_parser("ask", parents=[keys], help="one question")
    a.add_argument("question", nargs="+")
    a.add_argument("--refs", action="store_true", help="print the reference table after the answer")
    a.add_argument("--network", action="store_true", help="print the relationship view after the answer")
    d = sub.add_parser("demo", parents=[keys], help="scripted walkthrough for a meeting")
    d.add_argument("--no-pause", action="store_true", help="do not wait for a keypress between cases")
    d.add_argument("--only", type=int, choices=[1, 2, 3, 4, 5], help="run a single case")
    args = p.parse_args()

    use_model(getattr(args, "model", None), getattr(args, "local_url", ""))
    if not set_keys(getattr(args, "openrouter_key", None), getattr(args, "tavily_key", None)):
        console.print("[red]No OpenRouter key.[/red] Pass --openrouter-key or set OPENROUTER_API_KEY in .env.")
        return 2
    if not os.getenv("TAVILY_API_KEY"):
        console.print("[dim]No Tavily key: regulator web search is disabled.[/dim]")

    if args.cmd == "demo":
        # Imported here so `pv ask` does not pay for it, and to keep the cycle explicit:
        # demo builds on ask, not the other way round.
        from pv_agent.demo import run_demo

        return run_demo(pause=not args.no_pause, only=args.only)

    if args.cmd == "ask":
        turn = ask(" ".join(args.question), [])
        if args.network:
            show_network(turn)
        if args.refs:
            show_refs(turn)
        return 0
    return chat()


if __name__ == "__main__":
    sys.exit(main())
