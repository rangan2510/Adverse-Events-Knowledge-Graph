"""Turn the evidence a turn gathered into a relationship view for the terminal.

The answer says what the evidence means. This says where it came from and, more usefully, what
the drugs have in common: a shared metabolising enzyme or a shared reported event is the thing
a reviewer wants to spot immediately.

Rendered as a tree rather than a node-and-edge diagram on purpose. An ASCII layout of a real
three-drug answer measured 302 columns wide at 18 nodes, which no terminal shows usefully. A
tree stays readable and leaves room to mark what overlaps.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree


@dataclass
class Links:
    """What each drug connects to, and which of those connections are shared."""

    targets: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    events: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    labels: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    variants: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    outcome_pathways: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    pairs: list[tuple[str, str, int]] = field(default_factory=list)

    def shared(self, kind: str) -> dict[str, list[str]]:
        """Node -> drugs that share it, for nodes touched by more than one drug."""
        source = self.targets if kind == "targets" else self.events
        owners: dict[str, list[str]] = defaultdict(list)
        for drug, nodes in source.items():
            for n in nodes:
                owners[n].append(drug)
        return {n: d for n, d in owners.items() if len(d) > 1}


# MedDRA terms that describe how a report was filed rather than what happened to the patient.
# They top the FAERS counts for almost every drug, so without this filter the "shared between
# drugs" table fills up with 'off label use' and buries the clinically interesting overlap.
NON_EVENTS = frozenset(
    {
        "off label use",
        "drug ineffective",
        "product use in unapproved indication",
        "product use issue",
        "drug use for unknown indication",
        "no adverse event",
        "therapy cessation",
        "underdose",
        "incorrect dose administered",
        "drug dose omission",
        "condition aggravated",
        "death",
        "completed suicide",
    }
)


def _rows(result: dict, key: str) -> list[dict]:
    block = result.get(key)
    if isinstance(block, dict):
        return block.get("rows") or []
    return block if isinstance(block, list) else []


def collect(evidence: list[dict]) -> Links:
    """Read the relationships straight out of the tool results."""
    links = Links()
    for item in evidence:
        tool, drug, res = item.get("tool"), item.get("drug", ""), item.get("result") or {}
        if not isinstance(res, dict):
            continue

        if tool == "get_mechanism":
            for row in _rows(res, "targets"):
                gene = row.get("gene") or row.get("target")
                if gene and gene not in links.targets[drug]:
                    links.targets[drug].append(gene)
            for row in _rows(res, "dgidb"):
                gene = row.get("gene")
                # Uncurated DGIdb rows are statistical associations, so mark them as such
                # rather than letting them sit beside curated pharmacology unlabelled.
                if gene and row.get("curated") is False:
                    tag = f"{gene} (statistical association only)"
                    if tag not in links.targets[drug]:
                        links.targets[drug].append(tag)
                elif gene and gene not in links.targets[drug]:
                    links.targets[drug].append(gene)

        elif tool == "get_reported_events":
            for key in ("faers_top_reactions", "disproportionality"):
                for row in _rows(res, key):
                    event = (row.get("event") or "").lower()
                    if key == "disproportionality" and not row.get("signal"):
                        continue
                    if event and event not in NON_EVENTS and event not in links.events[drug]:
                        links.events[drug].append(event)

        elif tool in ("get_us_label", "get_eu_label"):
            if res.get("found"):
                origin = "United States label" if tool == "get_us_label" else "European product information"
                product = res.get("product") or drug
                found = [k for k, v in (res.get("sections") or {}).items() if isinstance(v, dict) and "text" in v]
                if found:
                    links.labels[drug].append(f"{origin}: {product} ({', '.join(found)})")

        elif tool == "get_pharmacology":
            # One line per gene: several rows describe the same variant in different studies.
            seen_genes: set[str] = set()
            for row in _rows(res, "pharmacogenomics"):
                gene, level = row.get("gene") or "?", row.get("evidence_level") or "?"
                if gene in seen_genes:
                    continue
                seen_genes.add(gene)
                phenotype = (row.get("phenotype") or "")[:60]
                links.variants[drug].append(f"{gene} (evidence level {level}): {phenotype}")
                if len(seen_genes) >= 6:
                    break
            for row in res.get("adverse_outcome_pathways") or []:
                title = row.get("title") or ""
                state = "under development" if row.get("is_draft") else f"{len(row.get('chain') or [])} linked steps"
                links.outcome_pathways[drug].append(f"{title[:70]} ({state})")

        elif tool == "get_pair_reports":
            # openfda.PairCounts names its fields a/b, not drug_a/drug_b.
            a, b = res.get("a"), res.get("b")
            if a and b:
                links.pairs.append((a, b, int(res.get("reports_both") or 0)))
    return links


# Each drug contributes ~21 FAERS events, so three drugs would print 63 lines. Show the ones
# that overlap with another drug first, then fill up to this many.
MAX_PER_BRANCH = 8


def _branch(tree: Tree, title: str, nodes: list[str], shared: dict[str, list[str]], drug: str) -> None:
    if not nodes:
        return

    def others_of(node: str) -> list[str]:
        return [d for d in shared.get(node.replace(" (statistical association only)", ""), []) if d != drug]

    ranked = sorted(nodes, key=lambda n: (not others_of(n), nodes.index(n)))
    shown, hidden = ranked[:MAX_PER_BRANCH], len(ranked) - MAX_PER_BRANCH

    branch = tree.add(f"[dim]{title}[/dim]")
    for node in shown:
        label = Text(node)
        others = others_of(node)
        if others:
            label.append(f"  also {', '.join(others)}", style="yellow")
        branch.add(label)
    if hidden > 0:
        branch.add(Text(f"+{hidden} more", style="dim"))


def render(links: Links, drugs: list[str]) -> Panel | None:
    """A tree per drug, with overlaps called out. None when there is nothing to show."""
    known = drugs or sorted(set(links.targets) | set(links.events) | set(links.labels))
    if not known:
        return None

    shared_targets, shared_events = links.shared("targets"), links.shared("events")
    tree = Tree("[bold]evidence gathered[/bold]")
    for drug in known:
        node = tree.add(f"[bold cyan]{drug}[/bold cyan]")
        for source in links.labels.get(drug, []):
            node.add(f"[green]{source}[/green]")
        _branch(node, "targets and enzymes", links.targets.get(drug, []), shared_targets, drug)
        _branch(node, "genetic variants linked to toxicity", links.variants.get(drug, []), {}, drug)
        _branch(node, "adverse outcome pathways", links.outcome_pathways.get(drug, []), {}, drug)
        _branch(node, "reported events", links.events.get(drug, []), shared_events, drug)

    parts: list = [tree]

    overlap = {**{k: v for k, v in shared_targets.items()}, **{k: v for k, v in shared_events.items()}}
    if overlap:
        table = Table(title="shared between drugs", title_justify="left", show_edge=False, pad_edge=False)
        table.add_column("node", style="yellow")
        table.add_column("shared by", style="dim")
        for node, owners in sorted(overlap.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            table.add_row(node, ", ".join(sorted(owners)))
        parts.append(table)

    if links.pairs:
        table = Table(
            title="reports naming both drugs (FDA Adverse Event Reporting System)",
            title_justify="left",
            show_edge=False,
            pad_edge=False,
        )
        table.add_column("pair")
        table.add_column("reports", justify="right")
        for a, b, n in links.pairs:
            table.add_row(f"{a} + {b}", f"{n:,}")
        parts.append(table)
        parts.append(Text("Co-reporting is not interaction evidence.", style="dim"))

    return Panel(Group(*parts), title="relationships", title_align="left", border_style="blue")
