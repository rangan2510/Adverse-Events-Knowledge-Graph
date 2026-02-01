# LLM Tool Functions API Reference

This document describes the deterministic tools available for the LLM orchestrator to query the Drug-AE Knowledge Graph. All tools return structured data (never prose) and are designed to be called synchronously.

## Table of Contents

- [Entity Resolution](#entity-resolution)
  - [resolve_drugs](#resolve_drugs)
  - [resolve_genes](#resolve_genes)
  - [resolve_diseases](#resolve_diseases)
  - [resolve_adverse_events](#resolve_adverse_events)
- [Mechanism Expansion](#mechanism-expansion)
  - [get_drug_targets](#get_drug_targets)
  - [get_gene_pathways](#get_gene_pathways)
  - [get_gene_diseases](#get_gene_diseases)
  - [get_disease_genes](#get_disease_genes)
  - [get_gene_interactors](#get_gene_interactors)
  - [expand_mechanism](#expand_mechanism)
  - [expand_gene_context](#expand_gene_context)
- [Adverse Events](#adverse-events)
  - [get_drug_adverse_events](#get_drug_adverse_events)
  - [get_drug_profile](#get_drug_profile)
  - [get_drug_label_sections](#get_drug_label_sections)
  - [get_drug_faers_signals](#get_drug_faers_signals)
- [Evidence and Provenance](#evidence-and-provenance)
  - [get_claim_evidence](#get_claim_evidence)
  - [get_entity_claims](#get_entity_claims)
- [Path Finding](#path-finding)
  - [find_drug_to_ae_paths](#find_drug_to_ae_paths)
  - [explain_paths](#explain_paths)
  - [score_paths](#score_paths)
  - [score_paths_with_evidence](#score_paths_with_evidence)
- [Subgraph Extraction](#subgraph-extraction)
  - [build_subgraph](#build_subgraph)
  - [score_edges](#score_edges)
- [Data Classes](#data-classes)

---

## Entity Resolution

Tools for resolving user-provided names to canonical database keys.

### resolve_drugs

Resolve drug names to canonical `drug_key` identifiers.

```python
def resolve_drugs(names: list[str]) -> dict[str, ResolvedEntity | None]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `names` | `list[str]` | List of drug names to resolve |

**Returns:** `dict[str, ResolvedEntity | None]` - Mapping of input name to resolved entity or None

**Behavior:**
1. Tries exact match on `preferred_name` (confidence: 1.0)
2. Falls back to partial LIKE match (confidence: 0.8)
3. Prefers drugs with `drugcentral_id` for richer data

**Example:**
```python
from kg_ae.tools import resolve_drugs

results = resolve_drugs(["aspirin", "atorvastatin", "unknown_drug"])
# {
#   "aspirin": ResolvedEntity(key=123, name="aspirin", source="preferred_name", confidence=1.0),
#   "atorvastatin": ResolvedEntity(key=456, name="atorvastatin", source="preferred_name", confidence=1.0),
#   "unknown_drug": None
# }
```

---

### resolve_genes

Resolve gene symbols to canonical `gene_key` identifiers.

```python
def resolve_genes(symbols: list[str]) -> dict[str, ResolvedEntity | None]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `symbols` | `list[str]` | List of gene symbols (e.g., "TP53", "BRCA1") |

**Returns:** `dict[str, ResolvedEntity | None]` - Mapping of input symbol to resolved entity or None

**Behavior:**
- Case-insensitive exact match on `symbol` column
- Confidence is always 1.0 for matches

**Example:**
```python
from kg_ae.tools import resolve_genes

results = resolve_genes(["TP53", "BRCA1", "CYP3A4"])
```

---

### resolve_diseases

Resolve disease terms to canonical `disease_key` identifiers.

```python
def resolve_diseases(terms: list[str]) -> dict[str, ResolvedEntity | None]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `terms` | `list[str]` | List of disease terms |

**Returns:** `dict[str, ResolvedEntity | None]` - Mapping of input term to resolved entity or None

**Behavior:**
1. Exact match on `label` (confidence: 1.0)
2. Partial LIKE match (confidence: 0.7)

**Example:**
```python
from kg_ae.tools import resolve_diseases

results = resolve_diseases(["breast cancer", "diabetes mellitus"])
```

---

### resolve_adverse_events

Resolve adverse event terms to canonical `ae_key` identifiers.

```python
def resolve_adverse_events(terms: list[str]) -> dict[str, ResolvedEntity | None]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `terms` | `list[str]` | List of AE terms (e.g., "myopathy", "hepatotoxicity") |

**Returns:** `dict[str, ResolvedEntity | None]` - Mapping of input term to resolved entity or None

**Behavior:**
1. Exact match on `ae_label` (confidence: 1.0)
2. Exact match on `ae_code` (confidence: 1.0)
3. Partial LIKE match on `ae_label` (confidence: 0.7)

**Example:**
```python
from kg_ae.tools import resolve_adverse_events

results = resolve_adverse_events(["myopathy", "rhabdomyolysis", "nausea"])
```

---

## Mechanism Expansion

Tools for exploring drug mechanisms: targets, pathways, and disease associations.

### get_drug_targets

Get all gene targets for a drug.

```python
def get_drug_targets(drug_key: int) -> list[DrugTarget]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `drug_key` | `int` | The drug's primary key |

**Returns:** `list[DrugTarget]` - List of drug-gene target relationships

**Graph Traversal:**
```
Drug -(HasClaim)-> Claim -(ClaimGene)-> Gene
```

**Example:**
```python
from kg_ae.tools import resolve_drugs, get_drug_targets

drug = resolve_drugs(["atorvastatin"])["atorvastatin"]
targets = get_drug_targets(drug.key)
# Returns: [DrugTarget(gene_symbol="HMGCR", relation="inhibitor", ...), ...]
```

---

### get_gene_pathways

Get all pathways containing a gene.

```python
def get_gene_pathways(gene_key: int) -> list[GenePathway]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `gene_key` | `int` | The gene's primary key |

**Returns:** `list[GenePathway]` - List of pathway memberships

**Graph Traversal:**
```
Gene -(HasClaim)-> Claim -(ClaimPathway)-> Pathway
```

**Example:**
```python
from kg_ae.tools import get_gene_pathways

pathways = get_gene_pathways(gene_key=123)
# Returns: [GenePathway(pathway_label="Cholesterol biosynthesis", reactome_id="R-HSA-191273", ...)]
```

---

### get_gene_diseases

Get disease associations for a gene.

```python
def get_gene_diseases(gene_key: int, min_score: float = 0.0) -> list[GeneDisease]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `gene_key` | `int` | The gene's primary key |
| `min_score` | `float` | Minimum association score (0-1), default 0.0 |

**Returns:** `list[GeneDisease]` - List sorted by score descending

**Graph Traversal:**
```
Gene -(HasClaim)-> Claim -(ClaimDisease)-> Disease
```

**Example:**
```python
from kg_ae.tools import get_gene_diseases

diseases = get_gene_diseases(gene_key=123, min_score=0.5)
```

---

### get_disease_genes

Get genes associated with a disease (reverse lookup).

```python
def get_disease_genes(
    disease_key: int,
    sources: list[str] | None = None,
    min_score: float = 0.0,
    limit: int = 100,
) -> list[DiseaseGene]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `disease_key` | `int` | The disease's primary key |
| `sources` | `list[str] \| None` | Filter by source: `["opentargets", "ctd", "clingen"]` |
| `min_score` | `float` | Minimum association score (0-1) |
| `limit` | `int` | Maximum results to return |

**Returns:** `list[DiseaseGene]` - List sorted by score descending

**Graph Traversal:**
```
Gene -(HasClaim)-> Claim -(ClaimDisease)-> Disease
(filter by disease_key to find associated genes)
```

**Example:**
```python
from kg_ae.tools import resolve_diseases, get_disease_genes

disease = resolve_diseases(["breast cancer"])["breast cancer"]
genes = get_disease_genes(disease.key, sources=["opentargets"], min_score=0.7)
# Returns: [DiseaseGene(gene_symbol="BRCA1", score=1.0, ...), ...]
```

---

### get_gene_interactors

Get protein-protein interactions from STRING database.

```python
def get_gene_interactors(
    gene_key: int,
    min_score: float = 0.4,
    limit: int = 50,
) -> list[GeneInteractor]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `gene_key` | `int` | The gene's primary key |
| `min_score` | `float` | Minimum STRING combined score (0-1), default 0.4 |
| `limit` | `int` | Maximum interactors to return |

**Returns:** `list[GeneInteractor]` - List sorted by score descending

**Data Source:** STRING database via `GENE_GENE_STRING` claims

**Example:**
```python
from kg_ae.tools import get_gene_interactors

interactors = get_gene_interactors(gene_key=123, min_score=0.7)
# Returns: [GeneInteractor(interactor_symbol="MDM2", score=0.99, ...), ...]
```

---

### expand_mechanism

Get complete mechanistic expansion for a drug: targets + their pathways.

```python
def expand_mechanism(drug_key: int) -> dict
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `drug_key` | `int` | The drug's primary key |

**Returns:** `dict` with keys:
- `targets`: `list[DrugTarget]`
- `pathways`: `list[GenePathway]` (deduplicated across all targets)

**Example:**
```python
from kg_ae.tools import expand_mechanism

mechanism = expand_mechanism(drug_key=456)
print(f"Drug targets {len(mechanism['targets'])} genes in {len(mechanism['pathways'])} pathways")
```

---

### expand_gene_context

Expand context for multiple genes: pathways + disease associations.

```python
def expand_gene_context(gene_keys: list[int], min_disease_score: float = 0.3) -> dict
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `gene_keys` | `list[int]` | List of gene primary keys |
| `min_disease_score` | `float` | Minimum disease association score |

**Returns:** `dict` with keys:
- `pathways`: `dict[gene_key, list[GenePathway]]`
- `diseases`: `dict[gene_key, list[GeneDisease]]`

---

## Adverse Events

Tools for retrieving drug adverse event data from SIDER, FDA labels, and FAERS.

### get_drug_adverse_events

Get known adverse events for a drug.

```python
def get_drug_adverse_events(
    drug_key: int,
    min_frequency: float | None = None,
    limit: int = 100,
) -> list[DrugAdverseEvent]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `drug_key` | `int` | The drug's primary key |
| `min_frequency` | `float \| None` | Minimum frequency threshold (0-1) |
| `limit` | `int` | Maximum results |

**Returns:** `list[DrugAdverseEvent]` - Sorted by frequency descending

**Graph Traversal:**
```
Drug -(HasClaim)-> Claim -(ClaimAdverseEvent)-> AdverseEvent
```

**Example:**
```python
from kg_ae.tools import get_drug_adverse_events

aes = get_drug_adverse_events(drug_key=456, min_frequency=0.01, limit=20)
for ae in aes:
    print(f"{ae.ae_label}: {ae.frequency:.1%}")
```

---

### get_drug_profile

Get complete profile for a drug: info, targets, and top adverse events.

```python
def get_drug_profile(drug_key: int) -> dict
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `drug_key` | `int` | The drug's primary key |

**Returns:** `dict` with keys:
- `drug`: Basic drug info (name, IDs)
- `targets`: List of gene targets
- `adverse_events`: Top 20 AEs

**Example:**
```python
from kg_ae.tools import get_drug_profile

profile = get_drug_profile(drug_key=456)
print(f"Drug: {profile['drug']['preferred_name']}")
print(f"Targets: {len(profile['targets'])} genes")
print(f"Known AEs: {len(profile['adverse_events'])}")
```

---

### get_drug_label_sections

Get FDA drug label sections (adverse reactions, warnings, etc.).

```python
def get_drug_label_sections(
    drug_key: int,
    sections: list[str] | None = None,
) -> list[DrugLabelSection]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `drug_key` | `int` | The drug's primary key |
| `sections` | `list[str] \| None` | Specific sections to retrieve, or None for all |

**Available Sections:**
- `adverse_reactions`
- `warnings`
- `contraindications`
- `drug_interactions`
- `boxed_warning`

**Returns:** `list[DrugLabelSection]`

**Example:**
```python
from kg_ae.tools import get_drug_label_sections

sections = get_drug_label_sections(drug_key=456, sections=["adverse_reactions", "warnings"])
for s in sections:
    print(f"--- {s.section_name} ---")
    print(s.content[:500])
```

---

### get_drug_faers_signals

Get FAERS disproportionality signals for a drug.

```python
def get_drug_faers_signals(
    drug_key: int,
    top_k: int = 200,
    min_count: int = 1,
    min_prr: float | None = None,
) -> list[FAERSSignal]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `drug_key` | `int` | The drug's primary key |
| `top_k` | `int` | Maximum signals to return |
| `min_count` | `int` | Minimum report count threshold |
| `min_prr` | `float \| None` | Minimum PRR threshold |

**Returns:** `list[FAERSSignal]` with metrics:
- `prr`: Proportional Reporting Ratio
- `ror`: Reporting Odds Ratio
- `chi2`: Chi-squared statistic
- `count`: Number of reports

**Example:**
```python
from kg_ae.tools import get_drug_faers_signals

signals = get_drug_faers_signals(drug_key=456, min_count=5, min_prr=2.0)
for sig in signals[:10]:
    print(f"{sig.ae_label}: PRR={sig.prr:.2f}, count={sig.count}")
```

---

## Evidence and Provenance

Tools for retrieving provenance and supporting evidence for claims.

### get_claim_evidence

Get full evidence trail for a claim. This is the audit backbone.

```python
def get_claim_evidence(claim_key: int) -> ClaimDetail | None
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_key` | `int` | The claim's primary key |

**Returns:** `ClaimDetail` with:
- Claim metadata (type, score, polarity, statement)
- All linked `Evidence` records with payloads

**Graph Traversal:**
```
Claim -(SupportedBy)-> Evidence
```

**Example:**
```python
from kg_ae.tools import get_claim_evidence

claim = get_claim_evidence(claim_key=789)
print(f"Claim type: {claim.claim_type}")
print(f"Evidence records: {len(claim.evidence)}")
for ev in claim.evidence:
    print(f"  - {ev.evidence_type}: {ev.source_record_id}")
```

---

### get_entity_claims

Get all claims for an entity (drug, gene, disease, etc.).

```python
def get_entity_claims(
    entity_type: str,
    entity_key: int,
    claim_types: list[str] | None = None,
    limit: int = 100,
) -> list[ClaimDetail]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `entity_type` | `str` | One of: `"Drug"`, `"Gene"`, `"Disease"`, `"Pathway"`, `"AdverseEvent"` |
| `entity_key` | `int` | The entity's primary key |
| `claim_types` | `list[str] \| None` | Filter by claim types |
| `limit` | `int` | Maximum claims to return |

**Returns:** `list[ClaimDetail]` - Each with full evidence

**Example:**
```python
from kg_ae.tools import get_entity_claims

claims = get_entity_claims("Drug", drug_key=456, claim_types=["DRUG_TARGET"])
for claim in claims:
    print(f"{claim.claim_type}: score={claim.strength_score}")
```

---

## Path Finding

Tools for finding and ranking mechanistic paths through the knowledge graph.

### find_drug_to_ae_paths

Find mechanistic paths from a drug to adverse event(s).

```python
def find_drug_to_ae_paths(
    drug_key: int,
    ae_key: int | None = None,
    max_paths: int = 10,
) -> list[MechanisticPath]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `drug_key` | `int` | Starting drug |
| `ae_key` | `int \| None` | Specific AE, or None for all AEs |
| `max_paths` | `int` | Maximum paths to return |

**Returns:** `list[MechanisticPath]` - Sorted by score

**Path Types Found:**
1. `Drug -> AdverseEvent` (direct association)
2. `Drug -> Gene -> Pathway` (mechanistic context)
3. `Drug -> Gene -> Disease` (disease-mediated)

**Example:**
```python
from kg_ae.tools import find_drug_to_ae_paths

paths = find_drug_to_ae_paths(drug_key=456, max_paths=5)
for path in paths:
    print(f"Score: {path.score:.2f}")
    print(f"  {path}")  # Uses __str__ for readable output
```

---

### explain_paths

Generate ranked mechanistic explanations with optional patient context.

```python
def explain_paths(
    drug_key: int,
    ae_key: int | None = None,
    condition_keys: list[int] | None = None,
    top_k: int = 5,
) -> list[dict]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `drug_key` | `int` | The drug to explain |
| `ae_key` | `int \| None` | Optional specific AE |
| `condition_keys` | `list[int] \| None` | Patient conditions (disease_keys) for context boosting |
| `top_k` | `int` | Number of top paths |

**Returns:** `list[dict]` - Path explanations with scores

**Context Boosting:** Paths through patient conditions receive 1.5x score multiplier

---

### score_paths

Score and rank mechanistic paths using a deterministic policy.

```python
def score_paths(
    paths: list[MechanisticPath],
    policy: ScoringPolicy | None = None,
) -> list[MechanisticPath]
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `paths` | `list[MechanisticPath]` | Paths to score |
| `policy` | `ScoringPolicy \| None` | Custom policy, or None for defaults |

**Returns:** `list[MechanisticPath]` - Sorted by score descending

**Scoring Formula:**
```
final_score = base_score * source_weight * length_factor * multi_source_bonus
```

Where:
- `length_factor = length_penalty ^ (num_steps - 1)`
- `multi_source_bonus` applied if evidence_count > 1

---

### score_paths_with_evidence

Score paths and return detailed scoring breakdown for explainability.

```python
def score_paths_with_evidence(
    paths: list[MechanisticPath],
    policy: ScoringPolicy | None = None,
) -> list[dict]
```

**Returns:** `list[dict]` with scoring components:
- `path`: The path data
- `base_score`: Original score
- `length_factor`: Length penalty applied
- `multi_source_bonus`: Bonus if applicable
- `final_score`: Computed score

---

## Subgraph Extraction

Tools for building and exporting subgraphs for visualization.

### build_subgraph

Build a subgraph centered on given drugs.

```python
def build_subgraph(
    drug_keys: list[int],
    include_targets: bool = True,
    include_pathways: bool = True,
    include_diseases: bool = True,
    include_aes: bool = True,
    max_pathways_per_gene: int = 5,
    max_diseases_per_gene: int = 5,
    max_aes_per_drug: int = 10,
    min_disease_score: float = 0.3,
) -> Subgraph
```

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `drug_keys` | `list[int]` | - | Drug primary keys |
| `include_targets` | `bool` | `True` | Include Drug->Gene edges |
| `include_pathways` | `bool` | `True` | Include Gene->Pathway edges |
| `include_diseases` | `bool` | `True` | Include Gene->Disease edges |
| `include_aes` | `bool` | `True` | Include Drug->AE edges |
| `max_pathways_per_gene` | `int` | `5` | Limit pathways per gene |
| `max_diseases_per_gene` | `int` | `5` | Limit diseases per gene |
| `max_aes_per_drug` | `int` | `10` | Limit AEs per drug |
| `min_disease_score` | `float` | `0.3` | Minimum disease association score |

**Returns:** `Subgraph` with export methods:
- `to_dict()`: JSON-serializable dict
- `to_cytoscape()`: Cytoscape.js format

**Example:**
```python
from kg_ae.tools import build_subgraph
import json

graph = build_subgraph(drug_keys=[456, 789], include_pathways=True)

# Export to JSON
with open("subgraph.json", "w") as f:
    json.dump(graph.to_dict(), f)

# Export for Cytoscape visualization
cytoscape_data = graph.to_cytoscape()
```

---

### score_edges

Apply evidence-based scoring to graph edges.

```python
def score_edges(
    graph: Subgraph,
    weights: dict[str, float] | None = None,
) -> Subgraph
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `graph` | `Subgraph` | Input subgraph |
| `weights` | `dict[str, float] \| None` | Custom weights by edge type |

**Default Weights:**
| Edge Type | Weight | Description |
|-----------|--------|-------------|
| `TARGETS` | 1.0 | Curated drug-target |
| `IN_PATHWAY` | 0.9 | Curated pathway membership |
| `ASSOCIATED_WITH` | 0.8 | Gene-disease from Open Targets |
| `CAUSES` | 0.7 | Drug-AE from SIDER |

---

## Data Classes

### ResolvedEntity
```python
@dataclass
class ResolvedEntity:
    key: int           # Database primary key
    name: str          # Canonical name
    source: str        # Match source (e.g., "preferred_name", "symbol")
    confidence: float  # 0.0-1.0
```

### DrugTarget
```python
@dataclass
class DrugTarget:
    drug_key: int
    drug_name: str
    gene_key: int
    gene_symbol: str
    relation: str | None     # e.g., "inhibitor", "agonist"
    effect: str | None       # e.g., "decrease", "increase"
    claim_type: str | None   # e.g., "DRUG_TARGET"
    dataset: str | None      # Source dataset
```

### GenePathway
```python
@dataclass
class GenePathway:
    gene_key: int
    gene_symbol: str
    pathway_key: int
    pathway_label: str
    reactome_id: str | None
```

### GeneDisease
```python
@dataclass
class GeneDisease:
    gene_key: int
    gene_symbol: str
    disease_key: int
    disease_label: str
    score: float | None      # Association score (0-1)
    efo_id: str | None       # EFO ontology ID
```

### DiseaseGene
```python
@dataclass
class DiseaseGene:
    disease_key: int
    disease_label: str
    gene_key: int
    gene_symbol: str
    score: float | None
    source: str | None       # "opentargets", "ctd", "clingen"
```

### GeneInteractor
```python
@dataclass
class GeneInteractor:
    gene_key: int
    gene_symbol: str
    interactor_key: int
    interactor_symbol: str
    score: float             # STRING combined score (0-1)
```

### DrugAdverseEvent
```python
@dataclass
class DrugAdverseEvent:
    drug_key: int
    drug_name: str
    ae_key: int
    ae_label: str
    frequency: float | None  # 0-1 frequency
    relation: str | None     # AE relationship type
    dataset: str | None      # Source dataset
```

### DrugLabelSection
```python
@dataclass
class DrugLabelSection:
    drug_key: int
    drug_name: str
    section_name: str        # e.g., "adverse_reactions"
    content: str             # Section text content
    effective_date: str | None
    brand_name: str | None
```

### FAERSSignal
```python
@dataclass
class FAERSSignal:
    drug_key: int
    drug_name: str
    ae_key: int
    ae_label: str
    prr: float | None        # Proportional Reporting Ratio
    ror: float | None        # Reporting Odds Ratio
    chi2: float | None       # Chi-squared statistic
    count: int               # Number of reports
```

### ClaimEvidence
```python
@dataclass
class ClaimEvidence:
    evidence_key: int
    evidence_type: str
    source_record_id: str | None
    source_url: str | None
    payload: dict | None     # Raw evidence data
    support_strength: float | None
    dataset_key: str | None
```

### ClaimDetail
```python
@dataclass
class ClaimDetail:
    claim_key: int
    claim_type: str
    strength_score: float | None
    polarity: int | None     # 1=positive, -1=negative, 0=neutral
    statement: dict | None   # Claim metadata
    dataset_key: str | None
    evidence: list[ClaimEvidence]
```

### MechanisticPath
```python
@dataclass
class MechanisticPath:
    steps: list[PathStep]    # Ordered path steps
    score: float             # Computed score (0-1)
    evidence_count: int      # Supporting evidence count

    def __str__(self) -> str: ...      # Human-readable path
    def to_dict(self) -> dict: ...     # JSON export
```

### PathStep
```python
@dataclass
class PathStep:
    node_type: str           # "Drug", "Gene", "Pathway", etc.
    node_key: int            # Database primary key
    node_label: str          # Display name
    edge_type: str | None    # Edge leading to this node
```

### ScoringPolicy
```python
@dataclass
class ScoringPolicy:
    source_weights: dict[str, float]  # Weight by data source
    multi_source_bonus: float = 1.2   # Bonus for multiple sources
    min_evidence: int = 1             # Minimum evidence required
    length_penalty: float = 0.95      # Penalty per hop
```

Default source weights:
```python
{
    "drugcentral": 1.0,
    "opentargets": 0.95,
    "chembl": 0.9,
    "reactome": 0.9,
    "gtop": 0.85,
    "clingen": 0.85,
    "sider": 0.8,
    "ctd": 0.7,
    "hpo": 0.7,
    "string": 0.6,
    "faers": 0.5,
    "openfda": 0.5,
}
```

### Subgraph
```python
@dataclass
class Subgraph:
    nodes: list[Node]
    edges: list[Edge]

    def to_dict(self) -> dict: ...         # JSON export
    def to_cytoscape(self) -> dict: ...    # Cytoscape.js format
```

### Node
```python
@dataclass
class Node:
    id: str                  # Unique ID (e.g., "drug:123")
    type: str                # Entity type
    label: str               # Display name
    properties: dict         # Additional properties
```

### Edge
```python
@dataclass
class Edge:
    source: str              # Source node ID
    target: str              # Target node ID
    type: str                # Edge type (e.g., "TARGETS")
    weight: float = 1.0      # Edge weight
    properties: dict         # Additional properties
```

---

## Usage Patterns

### Complete Drug Investigation

```python
from kg_ae.tools import (
    resolve_drugs,
    get_drug_profile,
    expand_mechanism,
    get_drug_faers_signals,
    build_subgraph,
)

# 1. Resolve drug name to key
drug = resolve_drugs(["metformin"])["metformin"]

# 2. Get complete profile
profile = get_drug_profile(drug.key)

# 3. Expand mechanism
mechanism = expand_mechanism(drug.key)

# 4. Check FAERS signals
signals = get_drug_faers_signals(drug.key, min_prr=2.0)

# 5. Build visualization subgraph
graph = build_subgraph([drug.key])
```

### Investigate Drug-AE Relationship

```python
from kg_ae.tools import (
    resolve_drugs,
    resolve_adverse_events,
    find_drug_to_ae_paths,
    explain_paths,
)

# Resolve entities
drug = resolve_drugs(["warfarin"])["warfarin"]
ae = resolve_adverse_events(["bleeding"])["bleeding"]

# Find mechanistic paths
paths = find_drug_to_ae_paths(drug.key, ae.key)

# Get explanations with patient context
patient_conditions = [...]  # disease_keys
explanations = explain_paths(drug.key, ae.key, condition_keys=patient_conditions)
```

### Audit a Specific Claim

```python
from kg_ae.tools import get_entity_claims, get_claim_evidence

# Get all claims for a drug
claims = get_entity_claims("Drug", drug_key=456)

# Dive into specific claim's evidence
for claim in claims:
    detail = get_claim_evidence(claim.claim_key)
    print(f"Claim {claim.claim_type}: {len(detail.evidence)} evidence records")
    for ev in detail.evidence:
        print(f"  Source: {ev.evidence_type} - {ev.source_record_id}")
```
