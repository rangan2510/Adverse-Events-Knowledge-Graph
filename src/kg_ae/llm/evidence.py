"""
Evidence pack for accumulating tool execution results.

The evidence pack is passed to the narrator LLM as the ONLY source
of information it can use for generating summaries.
"""

from dataclasses import dataclass, field
from typing import Any
import json


@dataclass
class EvidencePack:
    """Evidence accumulated during tool execution."""
    
    # Resolved entities (name -> key)
    drug_keys: dict[str, int] = field(default_factory=dict)
    gene_keys: dict[str, int] = field(default_factory=dict)
    disease_keys: dict[str, int] = field(default_factory=dict)
    ae_keys: dict[str, int] = field(default_factory=dict)
    
    # Entity details (key -> info dict)
    drug_info: dict[int, dict] = field(default_factory=dict)
    gene_info: dict[int, dict] = field(default_factory=dict)
    disease_info: dict[int, dict] = field(default_factory=dict)
    ae_info: dict[int, dict] = field(default_factory=dict)
    
    # Graph data
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    
    # Mechanistic paths
    paths: list[dict] = field(default_factory=list)
    
    # Evidence references
    evidence_ids: set[int] = field(default_factory=set)
    claim_ids: set[int] = field(default_factory=set)
    dataset_ids: set[str] = field(default_factory=set)
    
    # Key statistics
    faers_signals: list[dict] = field(default_factory=list)
    label_sections: list[dict] = field(default_factory=list)
    
    # Tool execution log
    tool_results: list[dict] = field(default_factory=list)
    
    # Errors encountered
    errors: list[str] = field(default_factory=list)
    
    def add_drug(self, name: str, key: int, info: dict | None = None) -> None:
        """Add resolved drug."""
        self.drug_keys[name.lower()] = key
        if info:
            self.drug_info[key] = info
    
    def add_gene(self, symbol: str, key: int, info: dict | None = None) -> None:
        """Add resolved gene."""
        self.gene_keys[symbol.upper()] = key
        if info:
            self.gene_info[key] = info
    
    def add_disease(self, term: str, key: int, info: dict | None = None) -> None:
        """Add resolved disease."""
        self.disease_keys[term.lower()] = key
        if info:
            self.disease_info[key] = info
    
    def add_ae(self, term: str, key: int, info: dict | None = None) -> None:
        """Add resolved adverse event."""
        self.ae_keys[term.lower()] = key
        if info:
            self.ae_info[key] = info
    
    def add_path(self, path: dict) -> None:
        """Add mechanistic path."""
        self.paths.append(path)
    
    def add_faers_signal(self, signal: dict) -> None:
        """Add FAERS disproportionality signal."""
        self.faers_signals.append(signal)
    
    def add_label_section(self, section: dict) -> None:
        """Add drug label section."""
        self.label_sections.append(section)
    
    def log_tool_call(self, tool: str, args: dict, result_summary: dict) -> None:
        """Log a tool execution."""
        self.tool_results.append({
            "tool": tool,
            "args": args,
            "result": result_summary,
        })
    
    def log_error(self, error: str) -> None:
        """Log an error during execution."""
        self.errors.append(error)
    
    def to_narrator_context(self) -> str:
        """
        Format evidence pack for narrator prompt.
        
        Returns a structured text representation that the narrator
        can use to generate its summary.
        """
        sections = []
        
        # Resolved entities
        if self.drug_keys:
            drugs = [f"- {name}: key={key}" for name, key in self.drug_keys.items()]
            sections.append("## Drugs\n" + "\n".join(drugs))
        
        if self.gene_keys:
            genes = [f"- {sym}: key={key}" for sym, key in self.gene_keys.items()]
            sections.append("## Genes\n" + "\n".join(genes))
        
        if self.disease_keys:
            diseases = [f"- {term}: key={key}" for term, key in self.disease_keys.items()]
            sections.append("## Diseases\n" + "\n".join(diseases))
        
        if self.ae_keys:
            aes = [f"- {term}: key={key}" for term, key in self.ae_keys.items()]
            sections.append("## Adverse Events\n" + "\n".join(aes))
        
        # Drug targets
        targets = []
        for drug_key, info in self.drug_info.items():
            if "targets" in info:
                drug_name = info.get("name", f"drug:{drug_key}")
                for t in info["targets"][:10]:  # Limit to top 10
                    targets.append(f"- {drug_name} -> {t['symbol']} ({t.get('relation', 'target')})")
        if targets:
            sections.append("## Drug-Gene Targets\n" + "\n".join(targets))
        
        # Mechanistic paths
        if self.paths:
            path_strs = []
            for i, p in enumerate(self.paths[:10], 1):  # Top 10 paths
                path_str = " -> ".join(
                    f"{s['type']}:{s['label']}" for s in p.get("path", [])
                )
                score = p.get("score", 0)
                path_strs.append(f"{i}. {path_str} (score={score:.3f})")
            sections.append("## Mechanistic Paths\n" + "\n".join(path_strs))
        
        # FAERS signals
        if self.faers_signals:
            signals = []
            for s in self.faers_signals[:20]:  # Top 20 signals
                signals.append(
                    f"- {s.get('ae_label', 'unknown')}: "
                    f"PRR={s.get('prr', 'N/A')}, "
                    f"count={s.get('count', 0)}"
                )
            sections.append("## FAERS Signals\n" + "\n".join(signals))
        
        # Label sections
        if self.label_sections:
            for sec in self.label_sections[:5]:  # Limit sections
                name = sec.get("section_name", "unknown")
                content = sec.get("content", "")[:1000]  # Truncate long content
                sections.append(f"## Label: {name}\n{content}")
        
        # Evidence summary
        sections.append(
            f"## Evidence Summary\n"
            f"- Evidence records: {len(self.evidence_ids)}\n"
            f"- Claims: {len(self.claim_ids)}\n"
            f"- Data sources: {', '.join(self.dataset_ids) if self.dataset_ids else 'none'}"
        )
        
        # Errors
        if self.errors:
            sections.append("## Errors\n" + "\n".join(f"- {e}" for e in self.errors))
        
        return "\n\n".join(sections)
    
    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "drug_keys": self.drug_keys,
            "gene_keys": self.gene_keys,
            "disease_keys": self.disease_keys,
            "ae_keys": self.ae_keys,
            "drug_info": self.drug_info,
            "gene_info": self.gene_info,
            "nodes": self.nodes,
            "edges": self.edges,
            "paths": self.paths,
            "faers_signals": self.faers_signals,
            "label_sections": self.label_sections,
            "evidence_ids": list(self.evidence_ids),
            "claim_ids": list(self.claim_ids),
            "dataset_ids": list(self.dataset_ids),
            "tool_results": self.tool_results,
            "errors": self.errors,
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
