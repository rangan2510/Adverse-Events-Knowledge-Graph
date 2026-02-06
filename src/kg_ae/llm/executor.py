"""
Tool executor that dispatches tool calls and accumulates evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..tools import (
    # Subgraph
    build_subgraph,
    expand_gene_context,
    expand_mechanism,
    explain_paths,
    # Paths
    find_drug_to_ae_paths,
    # Evidence
    get_claim_evidence,
    get_disease_genes,
    # Adverse events
    get_drug_adverse_events,
    get_drug_faers_signals,
    get_drug_label_sections,
    get_drug_profile,
    # Mechanism
    get_drug_targets,
    get_entity_claims,
    get_gene_diseases,
    get_gene_interactors,
    get_gene_pathways,
    resolve_adverse_events,
    resolve_diseases,
    # Entity resolution
    resolve_drugs,
    resolve_genes,
)
from .evidence import EvidencePack
from .schemas import ResolvedEntities, ToolCall, ToolName, ToolPlan

# Map tool names to actual functions
TOOL_REGISTRY: dict[ToolName, Callable] = {
    # Entity resolution
    ToolName.RESOLVE_DRUGS: resolve_drugs,
    ToolName.RESOLVE_GENES: resolve_genes,
    ToolName.RESOLVE_DISEASES: resolve_diseases,
    ToolName.RESOLVE_ADVERSE_EVENTS: resolve_adverse_events,
    # Mechanism
    ToolName.GET_DRUG_TARGETS: get_drug_targets,
    ToolName.GET_GENE_PATHWAYS: get_gene_pathways,
    ToolName.GET_GENE_DISEASES: get_gene_diseases,
    ToolName.GET_DISEASE_GENES: get_disease_genes,
    ToolName.GET_GENE_INTERACTORS: get_gene_interactors,
    ToolName.EXPAND_MECHANISM: expand_mechanism,
    ToolName.EXPAND_GENE_CONTEXT: expand_gene_context,
    # Adverse events
    ToolName.GET_DRUG_ADVERSE_EVENTS: get_drug_adverse_events,
    ToolName.GET_DRUG_PROFILE: get_drug_profile,
    ToolName.GET_DRUG_LABEL_SECTIONS: get_drug_label_sections,
    ToolName.GET_DRUG_FAERS_SIGNALS: get_drug_faers_signals,
    # Evidence
    ToolName.GET_CLAIM_EVIDENCE: get_claim_evidence,
    ToolName.GET_ENTITY_CLAIMS: get_entity_claims,
    # Paths
    ToolName.FIND_DRUG_TO_AE_PATHS: find_drug_to_ae_paths,
    ToolName.EXPLAIN_PATHS: explain_paths,
    # Subgraph
    ToolName.BUILD_SUBGRAPH: build_subgraph,
}


class ToolExecutor:
    """
    Executes tool calls from a ToolPlan and accumulates evidence.

    The executor:
    1. Handles entity resolution first to get integer keys
    2. Substitutes resolved keys into subsequent calls
    3. Accumulates all results into an EvidencePack
    4. Logs errors but continues execution
    """

    def __init__(self, conn):
        """
        Args:
            conn: Database connection (mssql_python.Connection)
        """
        self.conn = conn
        self.evidence = EvidencePack()
        self.resolved = ResolvedEntities()

    def execute_plan(self, plan: ToolPlan) -> EvidencePack:
        """
        Execute all tool calls in the plan.

        Args:
            plan: ToolPlan from planner LLM

        Returns:
            EvidencePack with accumulated evidence
        """
        for call in plan.calls:
            self._execute_call(call)
        return self.evidence

    def _execute_call(self, call: ToolCall) -> Any:
        """Execute a single tool call and store results."""
        tool_fn = TOOL_REGISTRY.get(call.tool)
        if tool_fn is None:
            error = f"Unknown tool: {call.tool}"
            self.evidence.errors.append(error)
            self.evidence.tool_log.append({
                "tool": call.tool.value,
                "args": call.args,
                "error": error,
            })
            return None

        # Substitute resolved keys in args
        args = self._substitute_keys(call.args)

        try:
            result = tool_fn(**args)
            try:
                self._accumulate_result(call.tool, args, result)
            except Exception:
                pass  # Best-effort accumulation
            self.evidence.tool_log.append({
                "tool": call.tool.value,
                "args": args,
                "success": True,
                "result_summary": self._summarize_result(result),
            })
            return result
        except Exception as e:
            error = f"{call.tool.value}: {e}"
            self.evidence.errors.append(error)
            self.evidence.tool_log.append({
                "tool": call.tool.value,
                "args": args,
                "error": str(e),
            })
            return None

    def _substitute_keys(self, args: dict) -> dict:
        """Replace placeholder references with resolved integer keys."""
        substituted = {}
        for key, value in args.items():
            if key == "drug_key" and isinstance(value, str):
                # Look up resolved drug key
                resolved_key = self.resolved.drug_keys.get(value.lower())
                if resolved_key:
                    substituted[key] = resolved_key
                else:
                    substituted[key] = value  # Pass through, may fail
            elif key == "gene_key" and isinstance(value, str):
                resolved_key = self.resolved.gene_keys.get(value.upper())
                if resolved_key:
                    substituted[key] = resolved_key
                else:
                    substituted[key] = value
            elif key == "disease_key" and isinstance(value, str):
                resolved_key = self.resolved.disease_keys.get(value.lower())
                if resolved_key:
                    substituted[key] = resolved_key
                else:
                    substituted[key] = value
            elif key == "ae_key" and isinstance(value, str):
                resolved_key = self.resolved.ae_keys.get(value.lower())
                if resolved_key:
                    substituted[key] = resolved_key
                else:
                    substituted[key] = value
            elif key == "gene_keys" and isinstance(value, list):
                # Handle list of gene keys
                substituted[key] = [
                    self.resolved.gene_keys.get(v.upper(), v) if isinstance(v, str) else v
                    for v in value
                ]
            elif key == "drug_keys" and isinstance(value, list):
                substituted[key] = [
                    self.resolved.drug_keys.get(v.lower(), v) if isinstance(v, str) else v
                    for v in value
                ]
            elif key == "condition_keys" and isinstance(value, list):
                substituted[key] = [
                    self.resolved.disease_keys.get(v.lower(), v) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                substituted[key] = value
        return substituted

    def _accumulate_result(self, tool: ToolName, args: dict, result: Any) -> None:
        """Store tool result in evidence pack."""
        # Entity resolution results
        # resolve_* tools return dict[str, ResolvedEntity|None]
        # ResolvedEntity has: key, name, source, confidence
        if tool == ToolName.RESOLVE_DRUGS and isinstance(result, dict):
            for input_name, entity in result.items():
                if entity is not None and entity.key:
                    self.resolved.drug_keys[input_name.lower()] = entity.key
                    self.evidence.drug_keys.add(entity.key)
                    self.evidence.entity_info[f"drug:{entity.key}"] = {
                        "name": entity.name,
                        "input": input_name,
                        "confidence": entity.confidence,
                    }

        elif tool == ToolName.RESOLVE_GENES and isinstance(result, dict):
            for input_symbol, entity in result.items():
                if entity is not None and entity.key:
                    self.resolved.gene_keys[input_symbol.upper()] = entity.key
                    self.evidence.gene_keys.add(entity.key)
                    self.evidence.entity_info[f"gene:{entity.key}"] = {
                        "symbol": entity.name,
                        "input": input_symbol,
                        "confidence": entity.confidence,
                    }

        elif tool == ToolName.RESOLVE_DISEASES and isinstance(result, dict):
            for input_term, entity in result.items():
                if entity is not None and entity.key:
                    self.resolved.disease_keys[input_term.lower()] = entity.key
                    self.evidence.disease_keys.add(entity.key)
                    self.evidence.entity_info[f"disease:{entity.key}"] = {
                        "name": entity.name,
                        "input": input_term,
                        "confidence": entity.confidence,
                    }

        elif tool == ToolName.RESOLVE_ADVERSE_EVENTS and isinstance(result, dict):
            for input_term, entity in result.items():
                if entity is not None and entity.key:
                    self.resolved.ae_keys[input_term.lower()] = entity.key
                    self.evidence.ae_keys.add(entity.key)
                    self.evidence.entity_info[f"ae:{entity.key}"] = {
                        "label": entity.name,
                        "input": input_term,
                        "confidence": entity.confidence,
                    }

        # Mechanism results - accumulate into graph
        elif tool == ToolName.GET_DRUG_TARGETS:
            for target in result:
                self.evidence.gene_keys.add(target.gene_key)
                self._add_edge("drug", args["drug_key"], "gene", target.gene_key, "targets", {
                    "activity": target.activity_type,
                    "action": target.action_type,
                    "source": target.source,
                })

        elif tool == ToolName.GET_GENE_PATHWAYS:
            for pw in result:
                self.evidence.pathway_keys.add(pw.pathway_key)
                self._add_edge("gene", args["gene_key"], "pathway", pw.pathway_key, "in_pathway", {
                    "pathway_name": pw.pathway_name,
                    "source": pw.source,
                })

        elif tool == ToolName.GET_GENE_DISEASES:
            for assoc in result:
                self.evidence.disease_keys.add(assoc.disease_key)
                self._add_edge("gene", args["gene_key"], "disease", assoc.disease_key, "associated_with", {
                    "score": assoc.score,
                    "sources": assoc.sources,
                })

        elif tool == ToolName.EXPAND_MECHANISM:
            # Contains targets and their pathways
            for target in result.targets:
                self.evidence.gene_keys.add(target.gene_key)
                self._add_edge("drug", result.drug_key, "gene", target.gene_key, "targets", {
                    "activity": target.activity_type,
                    "source": target.source,
                })
            for pw in result.pathways:
                self.evidence.pathway_keys.add(pw.pathway_key)
                self._add_edge("gene", pw.gene_key, "pathway", pw.pathway_key, "in_pathway", {
                    "pathway_name": pw.pathway_name,
                })

        # Adverse event results
        elif tool == ToolName.GET_DRUG_ADVERSE_EVENTS:
            for ae in result:
                self.evidence.ae_keys.add(ae.ae_key)
                self._add_edge("drug", args["drug_key"], "ae", ae.ae_key, "causes_ae", {
                    "frequency": ae.frequency,
                    "frequency_category": ae.frequency_category,
                    "source": ae.source,
                })

        elif tool == ToolName.GET_DRUG_FAERS_SIGNALS:
            self.evidence.faers_signals.extend([
                {
                    "drug_key": args["drug_key"],
                    "ae_term": sig.ae_term,
                    "count": sig.count,
                    "prr": sig.prr,
                    "ror": sig.ror,
                    "ic025": sig.ic025,
                }
                for sig in result
            ])

        elif tool == ToolName.GET_DRUG_LABEL_SECTIONS:
            for section in result:
                self.evidence.label_sections.append({
                    "drug_key": args["drug_key"],
                    "section": section.section_name,
                    "text": section.text[:2000],  # Truncate for context
                })

        elif tool == ToolName.GET_DRUG_PROFILE:
            # Full profile - extract components
            profile = result
            self.evidence.entity_info[f"drug:{profile.drug_key}"] = {
                "name": profile.drug_name,
                "description": profile.description,
                "mechanism": profile.mechanism_of_action,
            }
            for target in profile.targets:
                self.evidence.gene_keys.add(target.gene_key)
            for ae in profile.adverse_events:
                self.evidence.ae_keys.add(ae.ae_key)

        # Path results
        elif tool in (ToolName.FIND_DRUG_TO_AE_PATHS, ToolName.EXPLAIN_PATHS):
            paths_to_add = result.paths if hasattr(result, "paths") else result
            for path in paths_to_add:
                self.evidence.paths.append({
                    "hops": [
                        {
                            "from_type": hop.from_type,
                            "from_key": hop.from_key,
                            "from_name": hop.from_name,
                            "edge_type": hop.edge_type,
                            "to_type": hop.to_type,
                            "to_key": hop.to_key,
                            "to_name": hop.to_name,
                        }
                        for hop in path.hops
                    ],
                    "total_score": path.total_score,
                })

        # Subgraph results
        elif tool == ToolName.BUILD_SUBGRAPH:
            subgraph = result
            self.evidence.nodes.extend([
                {"type": n.entity_type, "key": n.entity_key, "name": n.name}
                for n in subgraph.nodes
            ])
            self.evidence.edges.extend([
                {
                    "from_type": e.from_type,
                    "from_key": e.from_key,
                    "edge_type": e.edge_type,
                    "to_type": e.to_type,
                    "to_key": e.to_key,
                    "score": e.score,
                }
                for e in subgraph.edges
            ])

    def _add_edge(
        self,
        from_type: str,
        from_key: int,
        to_type: str,
        to_key: int,
        edge_type: str,
        meta: dict,
    ) -> None:
        """Add an edge to the evidence graph."""
        self.evidence.edges.append({
            "from_type": from_type,
            "from_key": from_key,
            "to_type": to_type,
            "to_key": to_key,
            "edge_type": edge_type,
            **meta,
        })

    def _summarize_result(self, result: Any) -> str:
        """Create a short summary of a tool result for logging."""
        if result is None:
            return "null"
        if isinstance(result, list):
            return f"list[{len(result)}]"
        if hasattr(result, "__dataclass_fields__"):
            return f"{type(result).__name__}"
        return str(type(result).__name__)
