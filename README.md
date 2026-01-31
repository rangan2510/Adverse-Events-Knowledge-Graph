# Drug-AE Knowledge Graph

Pharmacovigilance knowledge graph linking drugs to adverse events through mechanistic pathways:
**Drug → Gene → Pathway → Disease → Adverse Event**

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- SQL Server 2025 (localhost, sa/password1$, database: `kg_ae`)

## Setup

```bash
uv sync                    # Install dependencies
uv run kg-ae init-db       # Create database schema
```

## ETL Pipeline

Each data source follows: **download → parse → normalize → load**

```bash
# SIDER: Drug → Adverse Event
uv run python -c "from kg_ae.datasets.sider import *; SIDERDownloader().download(); SIDERParser().parse(); SIDERNormalizer().normalize(); SIDERLoader().load()"

# DrugCentral: Drug → Gene
uv run python -c "from kg_ae.datasets.drugcentral import *; DrugCentralDownloader().download(); DrugCentralParser().parse(); DrugCentralNormalizer().normalize(); DrugCentralLoader().load()"

# Reactome: Gene → Pathway
uv run python -c "from kg_ae.datasets.reactome import *; ReactomeDownloader().download(); ReactomeParser().parse(); ReactomeNormalizer().normalize(); ReactomeLoader().load()"

# Open Targets: Gene → Disease
uv run python -c "from kg_ae.datasets.opentargets import *; OpenTargetsDownloader().download(); OpenTargetsParser().parse(); OpenTargetsNormalizer().normalize(); OpenTargetsLoader().load()"
```

## Data Directories

```
data/
  raw/         # Downloaded archives
  bronze/      # Parsed to Parquet (source-shaped)
  silver/      # Normalized (canonical IDs)
```

## Graph Statistics

| Entity | Count | Source |
|--------|-------|--------|
| Drugs | 5,528 | SIDER, DrugCentral |
| Genes | 1,970 | DrugCentral |
| Pathways | 2,848 | Reactome |
| Diseases | 28,392 | Open Targets |
| Adverse Events | 4,251 | SIDER |
| Claims | 253,137 | All sources |

## Example Query

```sql
-- Trace mechanistic path: Drug → Gene → Disease
SELECT d.preferred_name, g.symbol, dis.label, c2.strength_score
FROM kg.Drug d, kg.HasClaim hc1, kg.Claim c1, kg.ClaimGene cg, kg.Gene g,
     kg.HasClaim hc2, kg.Claim c2, kg.ClaimDisease cd, kg.Disease dis
WHERE MATCH(d-(hc1)->c1-(cg)->g)
  AND MATCH(g-(hc2)->c2-(cd)->dis)
  AND d.preferred_name = 'atorvastatin'
ORDER BY c2.strength_score DESC
```

## Project Plan

See [docs/milestones.md](docs/milestones.md) for architecture and roadmap.
