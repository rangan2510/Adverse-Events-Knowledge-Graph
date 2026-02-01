"""
Pydantic schemas for LLM planner output.

These schemas enforce structured output from the planner LLM.
"""

from enum import Enum
from pydantic import BaseModel, Field


class ToolName(str, Enum):
    """Available tools for the planner to call."""
    # Entity Resolution
    RESOLVE_DRUGS = "resolve_drugs"
    RESOLVE_GENES = "resolve_genes"
    RESOLVE_DISEASES = "resolve_diseases"
    RESOLVE_ADVERSE_EVENTS = "resolve_adverse_events"
    
    # Mechanism
    GET_DRUG_TARGETS = "get_drug_targets"
    GET_GENE_PATHWAYS = "get_gene_pathways"
    GET_GENE_DISEASES = "get_gene_diseases"
    GET_DISEASE_GENES = "get_disease_genes"
    GET_GENE_INTERACTORS = "get_gene_interactors"
    EXPAND_MECHANISM = "expand_mechanism"
    EXPAND_GENE_CONTEXT = "expand_gene_context"
    
    # Adverse Events
    GET_DRUG_ADVERSE_EVENTS = "get_drug_adverse_events"
    GET_DRUG_PROFILE = "get_drug_profile"
    GET_DRUG_LABEL_SECTIONS = "get_drug_label_sections"
    GET_DRUG_FAERS_SIGNALS = "get_drug_faers_signals"
    
    # Evidence
    GET_CLAIM_EVIDENCE = "get_claim_evidence"
    GET_ENTITY_CLAIMS = "get_entity_claims"
    
    # Paths
    FIND_DRUG_TO_AE_PATHS = "find_drug_to_ae_paths"
    EXPLAIN_PATHS = "explain_paths"
    SCORE_PATHS = "score_paths"
    
    # Subgraph
    BUILD_SUBGRAPH = "build_subgraph"


class ToolCall(BaseModel):
    """Single tool call with validated arguments."""
    tool: ToolName = Field(..., description="Tool to call")
    args: dict = Field(default_factory=dict, description="Tool arguments")
    reason: str | None = Field(None, description="Brief reason for this call")
    
    class Config:
        use_enum_values = True


class ToolPlan(BaseModel):
    """Complete execution plan from planner LLM."""
    calls: list[ToolCall] = Field(
        ..., 
        min_length=1,
        description="Ordered list of tool calls to execute"
    )
    stop_conditions: dict = Field(
        default_factory=dict,
        description="Optional conditions to stop early (e.g., max_depth)"
    )
    
    def validate_resolution_first(self) -> bool:
        """Check that entity resolution happens before queries."""
        resolution_tools = {
            ToolName.RESOLVE_DRUGS,
            ToolName.RESOLVE_GENES,
            ToolName.RESOLVE_DISEASES,
            ToolName.RESOLVE_ADVERSE_EVENTS,
        }
        
        if not self.calls:
            return False
            
        # First call should be a resolution tool
        return self.calls[0].tool in resolution_tools


class ResolvedEntities(BaseModel):
    """Tracks resolved entity keys during execution."""
    drugs: dict[str, int | None] = Field(default_factory=dict)
    genes: dict[str, int | None] = Field(default_factory=dict)
    diseases: dict[str, int | None] = Field(default_factory=dict)
    adverse_events: dict[str, int | None] = Field(default_factory=dict)
    
    def get_drug_key(self, name: str) -> int | None:
        """Get resolved drug key by name."""
        return self.drugs.get(name.lower())
    
    def get_gene_key(self, symbol: str) -> int | None:
        """Get resolved gene key by symbol."""
        return self.genes.get(symbol.upper())
    
    def get_disease_key(self, term: str) -> int | None:
        """Get resolved disease key by term."""
        return self.diseases.get(term.lower())
    
    def get_ae_key(self, term: str) -> int | None:
        """Get resolved adverse event key by term."""
        return self.adverse_events.get(term.lower())
