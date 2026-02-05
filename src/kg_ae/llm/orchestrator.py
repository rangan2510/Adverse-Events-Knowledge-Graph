"""
Main orchestrator that coordinates Plan -> Execute -> Narrate pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .client import NarratorClient, PlannerClient
from .config import LLMConfig
from .evidence import EvidencePack
from .executor import ToolExecutor
from .schemas import ToolPlan


@dataclass
class QueryResult:
    """Complete result from a query."""

    query: str
    plan: ToolPlan
    evidence: EvidencePack
    narrative: str
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Short summary of the result."""
        return (
            f"Query: {self.query[:50]}...\n"
            f"Tools called: {len(self.plan.calls)}\n"
            f"Entities found: {len(self.evidence.drug_keys)} drugs, "
            f"{len(self.evidence.gene_keys)} genes, "
            f"{len(self.evidence.disease_keys)} diseases, "
            f"{len(self.evidence.ae_keys)} AEs\n"
            f"Paths found: {len(self.evidence.paths)}\n"
            f"Errors: {len(self.errors)}"
        )


class Orchestrator:
    """
    Main pipeline coordinator for drug-AE queries.

    The orchestrator:
    1. Sends query to Planner LLM -> gets ToolPlan
    2. Executes tools via ToolExecutor -> accumulates EvidencePack
    3. Formats evidence and sends to Narrator LLM -> gets summary
    4. Returns complete QueryResult

    Usage:
        orchestrator = Orchestrator(conn)
        result = orchestrator.query("What AEs might metformin cause via AMPK?")
        print(result.narrative)
    """

    def __init__(
        self,
        conn,
        config: LLMConfig | None = None,
        verbose: bool = False,
    ):
        """
        Args:
            conn: Database connection (mssql_python.Connection)
            config: LLM configuration (uses defaults if None)
            verbose: If True, print progress to console
        """
        self.conn = conn
        self.config = config or LLMConfig()
        self.verbose = verbose
        self.console = Console() if verbose else None

        self.planner = PlannerClient(self.config)
        self.narrator = NarratorClient(self.config)

    def query(self, query: str) -> QueryResult:
        """
        Execute a complete query pipeline.

        Args:
            query: Natural language query about drug-AE relationships

        Returns:
            QueryResult with plan, evidence, and narrative
        """
        errors = []

        # Phase 1: Planning
        if self.verbose:
            self.console.print(Panel(query, title="Query"))

        plan = self._plan(query)
        if self.verbose:
            self._print_plan(plan)

        # Phase 2: Execution
        executor = ToolExecutor(self.conn)
        evidence = self._execute(executor, plan)
        errors.extend(evidence.errors)

        if self.verbose:
            self._print_evidence_summary(evidence)

        # Phase 3: Narration
        narrative = self._narrate(query, evidence)

        return QueryResult(
            query=query,
            plan=plan,
            evidence=evidence,
            narrative=narrative,
            errors=errors,
        )

    def query_stream(self, query: str) -> Iterator[str]:
        """
        Execute query with streaming narrative output.

        Args:
            query: Natural language query

        Yields:
            Narrative text chunks as they are generated
        """
        # Plan and execute (non-streaming)
        plan = self._plan(query)
        executor = ToolExecutor(self.conn)
        evidence = self._execute(executor, plan)

        # Stream narration
        evidence_context = evidence.to_narrator_context()
        yield from self.narrator.narrate_stream(query, evidence_context)

    def _plan(self, query: str) -> ToolPlan:
        """Generate tool plan from planner LLM."""
        if self.verbose:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Planning..."),
                console=self.console,
                transient=True,
            ) as progress:
                progress.add_task("plan", total=None)
                plan = self.planner.plan(query)
        else:
            plan = self.planner.plan(query)
        return plan

    def _execute(self, executor: ToolExecutor, plan: ToolPlan) -> EvidencePack:
        """Execute tool plan and accumulate evidence."""
        if self.verbose:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold green]Executing tools..."),
                console=self.console,
            ) as progress:
                task = progress.add_task("execute", total=len(plan.calls))
                for call in plan.calls:
                    executor._execute_call(call)
                    progress.advance(task)
            return executor.evidence
        else:
            return executor.execute_plan(plan)

    def _narrate(self, query: str, evidence: EvidencePack) -> str:
        """Generate narrative summary from evidence."""
        evidence_context = evidence.to_narrator_context()

        if self.verbose:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold magenta]Generating summary..."),
                console=self.console,
                transient=True,
            ) as progress:
                progress.add_task("narrate", total=None)
                narrative = self.narrator.narrate(query, evidence_context)
        else:
            narrative = self.narrator.narrate(query, evidence_context)

        return narrative

    def _print_plan(self, plan: ToolPlan) -> None:
        """Print tool plan to console."""
        table = Table(title="Tool Plan")
        table.add_column("Tool", style="cyan")
        table.add_column("Args", style="green")
        table.add_column("Reason", style="yellow")

        for call in plan.calls:
            args_str = ", ".join(f"{k}={v}" for k, v in call.args.items())
            table.add_row(call.tool.value, args_str, call.reason or "")

        self.console.print(table)

    def _print_evidence_summary(self, evidence: EvidencePack) -> None:
        """Print evidence summary to console."""
        table = Table(title="Evidence Summary")
        table.add_column("Category", style="cyan")
        table.add_column("Count", style="green")

        table.add_row("Drugs", str(len(evidence.drug_keys)))
        table.add_row("Genes", str(len(evidence.gene_keys)))
        table.add_row("Diseases", str(len(evidence.disease_keys)))
        table.add_row("Pathways", str(len(evidence.pathway_keys)))
        table.add_row("Adverse Events", str(len(evidence.ae_keys)))
        table.add_row("Paths", str(len(evidence.paths)))
        table.add_row("FAERS Signals", str(len(evidence.faers_signals)))
        table.add_row("Label Sections", str(len(evidence.label_sections)))
        table.add_row("Errors", str(len(evidence.errors)))

        self.console.print(table)


def ask(
    conn,
    query: str,
    config: LLMConfig | None = None,
    verbose: bool = False,
) -> QueryResult:
    """
    Convenience function for single queries.

    Args:
        conn: Database connection
        query: Natural language query
        config: Optional LLM config
        verbose: Print progress

    Returns:
        QueryResult with narrative and evidence
    """
    orchestrator = Orchestrator(conn, config, verbose)
    return orchestrator.query(query)
