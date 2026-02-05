"""
Tool executor for ReAct loop with output truncation.

Key features:
- Executes tool calls and returns structured results
- Truncates large outputs to fit context window
- Tracks resolved entities across iterations
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from rich.console import Console

from ..tools import (
    expand_mechanism,
    find_drug_to_ae_paths,
    get_claim_evidence,
    get_drug_adverse_events,
    get_drug_faers_signals,
    get_drug_profile,
    get_drug_targets,
    get_entity_claims,
    get_gene_diseases,
    get_gene_pathways,
    resolve_adverse_events,
    resolve_diseases,
    resolve_drugs,
    resolve_genes,
)
from .react_schemas import ReActContext, ToolCallRequest, ToolResult

console = Console()

# Maximum items to return per tool (prevents context overflow)
MAX_ITEMS_PER_TOOL = 30

# Tool registry mapping names to functions
TOOL_REGISTRY = {
    # Resolution
    "resolve_drugs": resolve_drugs,
    "resolve_genes": resolve_genes,
    "resolve_diseases": resolve_diseases,
    "resolve_adverse_events": resolve_adverse_events,
    # Adverse events
    "get_drug_adverse_events": get_drug_adverse_events,
    "get_drug_faers_signals": get_drug_faers_signals,
    "get_drug_profile": get_drug_profile,
    # Mechanism
    "get_drug_targets": get_drug_targets,
    "get_gene_pathways": get_gene_pathways,
    "get_gene_diseases": get_gene_diseases,
    "expand_mechanism": expand_mechanism,
    # Paths
    "find_drug_to_ae_paths": find_drug_to_ae_paths,
    # Evidence
    "get_claim_evidence": get_claim_evidence,
    "get_entity_claims": get_entity_claims,
}


def truncate_result(data: Any, max_items: int = MAX_ITEMS_PER_TOOL) -> tuple[Any, bool, int | None]:
    """
    Truncate large results to fit context window.
    
    Returns:
        (truncated_data, was_truncated, original_count)
    """
    if data is None:
        return None, False, None
    
    if isinstance(data, list):
        original_count = len(data)
        if original_count > max_items:
            return data[:max_items], True, original_count
        return data, False, original_count
    
    if isinstance(data, dict):
        # For dicts, check if values are lists and truncate those
        truncated = {}
        was_truncated = False
        for key, val in data.items():
            if isinstance(val, list) and len(val) > max_items:
                truncated[key] = val[:max_items]
                was_truncated = True
            else:
                truncated[key] = val
        return truncated, was_truncated, None
    
    return data, False, None


def serialize_result(data: Any) -> Any:
    """Convert dataclasses and other types to JSON-serializable format."""
    if data is None:
        return None
    
    if hasattr(data, "__dataclass_fields__"):
        return asdict(data)
    
    if isinstance(data, list):
        return [serialize_result(item) for item in data]
    
    if isinstance(data, dict):
        return {k: serialize_result(v) for k, v in data.items()}
    
    return data


class ReActExecutor:
    """
    Executes tool calls for ReAct loop.
    
    Features:
    - Substitutes resolved entity keys
    - Truncates large outputs
    - Returns structured ToolResult objects
    """
    
    def __init__(self, context: ReActContext, verbose: bool = True):
        """
        Args:
            context: ReAct context with resolved entities
            verbose: Print tool execution details
        """
        self.context = context
        self.verbose = verbose
    
    def execute_calls(self, calls: list[ToolCallRequest]) -> list[ToolResult]:
        """
        Execute a list of tool calls.
        
        Args:
            calls: List of ToolCallRequest from planner
            
        Returns:
            List of ToolResult with (possibly truncated) data
        """
        results = []
        
        for call in calls:
            if self.verbose:
                console.print(f"  [dim]Calling[/] {call.tool}({call.args}) - {call.reason}")
            
            result = self._execute_single(call)
            results.append(result)
            
            # Update resolved entities if this was a resolution call
            self._update_resolved(call.tool, result)
        
        return results
    
    def _execute_single(self, call: ToolCallRequest) -> ToolResult:
        """Execute a single tool call."""
        tool_fn = TOOL_REGISTRY.get(call.tool)
        
        if tool_fn is None:
            return ToolResult(
                tool=call.tool,
                args=call.args,
                success=False,
                error=f"Unknown tool: {call.tool}",
            )
        
        # Substitute resolved keys in args
        args = self._substitute_keys(call.args)
        
        try:
            # Execute tool
            raw_result = tool_fn(**args)
            
            # Serialize (convert dataclasses to dicts)
            serialized = serialize_result(raw_result)
            
            # Truncate if needed
            truncated_data, was_truncated, original_count = truncate_result(serialized)
            
            if self.verbose and was_truncated:
                console.print(f"    [yellow]Truncated: {original_count} -> {MAX_ITEMS_PER_TOOL} items[/]")
            
            return ToolResult(
                tool=call.tool,
                args=args,
                success=True,
                data=truncated_data,
                truncated=was_truncated,
                original_count=original_count,
            )
            
        except Exception as e:
            if self.verbose:
                console.print(f"    [red]Error: {e}[/]")
            return ToolResult(
                tool=call.tool,
                args=args,
                success=False,
                error=str(e),
            )
    
    def _substitute_keys(self, args: dict) -> dict:
        """Replace entity names/indices with resolved integer keys."""
        substituted = {}
        
        for key, value in args.items():
            if key == "drug_key":
                substituted[key] = self._resolve_drug_arg(value)
            elif key == "gene_key":
                substituted[key] = self._resolve_gene_arg(value)
            elif key == "disease_key":
                substituted[key] = self._resolve_disease_arg(value)
            elif key == "ae_key":
                substituted[key] = self._resolve_ae_arg(value)
            elif key == "names" and isinstance(value, list):
                # For resolve_drugs, pass through
                substituted[key] = value
            elif key == "symbols" and isinstance(value, list):
                # For resolve_genes, pass through
                substituted[key] = value
            elif key == "terms" and isinstance(value, list):
                # For resolve_diseases/aes, pass through
                substituted[key] = value
            else:
                substituted[key] = value
        
        return substituted
    
    def _resolve_drug_arg(self, value: Any) -> int | None:
        """Resolve drug argument to key."""
        if isinstance(value, int):
            # Already a key or index
            if value < 100:  # Small int = likely index
                keys = list(self.context.resolved_drugs.values())
                if value < len(keys):
                    return keys[value]
            return value
        if isinstance(value, str):
            return self.context.resolved_drugs.get(value.lower())
        return value
    
    def _resolve_gene_arg(self, value: Any) -> int | None:
        """Resolve gene argument to key."""
        if isinstance(value, int):
            if value < 100:
                keys = list(self.context.resolved_genes.values())
                if value < len(keys):
                    return keys[value]
            return value
        if isinstance(value, str):
            return self.context.resolved_genes.get(value.upper())
        return value
    
    def _resolve_disease_arg(self, value: Any) -> int | None:
        """Resolve disease argument to key."""
        if isinstance(value, int):
            if value < 100:
                keys = list(self.context.resolved_diseases.values())
                if value < len(keys):
                    return keys[value]
            return value
        if isinstance(value, str):
            return self.context.resolved_diseases.get(value.lower())
        return value
    
    def _resolve_ae_arg(self, value: Any) -> int | None:
        """Resolve AE argument to key."""
        if isinstance(value, int):
            if value < 100:
                keys = list(self.context.resolved_aes.values())
                if value < len(keys):
                    return keys[value]
            return value
        if isinstance(value, str):
            return self.context.resolved_aes.get(value.lower())
        return value
    
    def _update_resolved(self, tool: str, result: ToolResult) -> None:
        """Update resolved entities from resolution tool results."""
        if not result.success or result.data is None:
            return
        
        if tool == "resolve_drugs" and isinstance(result.data, dict):
            for name, entity in result.data.items():
                if entity is not None and isinstance(entity, dict):
                    key = entity.get("key")
                    if key is not None:
                        self.context.resolved_drugs[name.lower()] = key
        
        elif tool == "resolve_genes" and isinstance(result.data, dict):
            for symbol, entity in result.data.items():
                if entity is not None and isinstance(entity, dict):
                    key = entity.get("key")
                    if key is not None:
                        self.context.resolved_genes[symbol.upper()] = key
        
        elif tool == "resolve_diseases" and isinstance(result.data, dict):
            for term, entity in result.data.items():
                if entity is not None and isinstance(entity, dict):
                    key = entity.get("key")
                    if key is not None:
                        self.context.resolved_diseases[term.lower()] = key
        
        elif tool == "resolve_adverse_events" and isinstance(result.data, dict):
            for term, entity in result.data.items():
                if entity is not None and isinstance(entity, dict):
                    key = entity.get("key")
                    if key is not None:
                        self.context.resolved_aes[term.lower()] = key


def _format_item_compact(item: dict, tool: str) -> str:
    """Format a dict item compactly, prioritizing useful fields by tool type."""
    # Define priority fields by tool type
    priority_fields = {
        "get_drug_adverse_events": ["ae_label", "frequency", "relation"],
        "get_drug_faers_signals": ["ae_label", "count", "prr", "ror"],
        "get_drug_targets": ["gene_symbol", "action", "source"],
        "get_gene_pathways": ["name", "reactome_id"],
        "get_gene_diseases": ["name", "score"],
        "resolve_drugs": ["name", "key", "confidence"],
        "resolve_genes": ["symbol", "key", "confidence"],
    }
    
    # Get priority fields for this tool, or use default
    fields = priority_fields.get(tool, list(item.keys())[:4])
    
    # Build compact string with priority fields first
    parts = []
    for field in fields:
        if field in item and item[field] is not None:
            parts.append(f"{field}={item[field]}")
    
    # Add any remaining fields up to 4 total
    for k, v in item.items():
        if k not in fields and v is not None and len(parts) < 4:
            parts.append(f"{k}={v}")
    
    return ", ".join(parts)


def format_tool_results(results: list[ToolResult]) -> str:
    """Format tool results for LLM context."""
    lines = []
    
    for r in results:
        status = "[OK]" if r.success else "[FAIL]"
        lines.append(f"{status} {r.tool}({r.args})")
        
        if r.success:
            if r.truncated:
                lines.append(f"  (Showing {MAX_ITEMS_PER_TOOL} of {r.original_count} items)")
            
            # Format data compactly
            if r.data is None:
                lines.append("  Result: None")
            elif isinstance(r.data, list):
                if len(r.data) == 0:
                    lines.append("  Result: []")
                else:
                    lines.append(f"  Result ({len(r.data)} items):")
                    # Show actual data with tool-appropriate formatting
                    for i, item in enumerate(r.data[:15]):  # Show first 15
                        if isinstance(item, dict):
                            compact = _format_item_compact(item, r.tool)
                            lines.append(f"    [{i}] {compact}")
                        else:
                            lines.append(f"    [{i}] {item}")
                    if len(r.data) > 15:
                        lines.append(f"    ... and {len(r.data) - 15} more")
            elif isinstance(r.data, dict):
                lines.append("  Result:")
                for k, v in r.data.items():
                    if isinstance(v, list):
                        lines.append(f"    {k}: [{len(v)} items]")
                    else:
                        lines.append(f"    {k}: {v}")
        else:
            lines.append(f"  Error: {r.error}")
    
    return "\n".join(lines)


def format_resolved_entities(context: ReActContext) -> str:
    """Format resolved entities for LLM context."""
    lines = []
    
    if context.resolved_drugs:
        lines.append("Drugs:")
        for name, key in context.resolved_drugs.items():
            lines.append(f"  {name} -> drug_key={key}")
    
    if context.resolved_genes:
        lines.append("Genes:")
        for symbol, key in context.resolved_genes.items():
            lines.append(f"  {symbol} -> gene_key={key}")
    
    if context.resolved_diseases:
        lines.append("Diseases:")
        for term, key in context.resolved_diseases.items():
            lines.append(f"  {term} -> disease_key={key}")
    
    if context.resolved_aes:
        lines.append("Adverse Events:")
        for term, key in context.resolved_aes.items():
            lines.append(f"  {term} -> ae_key={key}")
    
    return "\n".join(lines) if lines else "(No entities resolved yet)"
