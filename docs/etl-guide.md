# ETL Pipeline Guide

Interactive pipeline runner for building the Drug-AE Knowledge Graph.

## Quick Start

```bash
# Interactive mode with live dashboard
uv run python -m kg_ae.cli etl

# Run everything in batch mode
uv run python -m kg_ae.cli etl --batch
```

## Live Dashboard

The runner displays a live status table during execution:

```
Tier | Dataset              | Download | Parse | Normalize | Load | Dependencies
-----|----------------------|----------|-------|-----------|------|-------------
  1  | HGNC Gene Nomencl.   |   [ok]   | [ok]  |     -     | [>]  | -
  1  | DrugCentral          |   [ ]    | [ ]   |    [ ]    | [ ]  | -
  2  | Open Targets         |   [ ]    | [ ]   |    [ ]    | [ ]  | hgnc
  ...
```

Status indicators:
- `[ ]` pending
- `[>]` running
- `[ok]` done (shows duration when complete)
- `[!]` failed
- `[-]` skipped (phase not applicable)

## CLI Commands

### Full Pipeline

```bash
# Interactive menu
uv run python -m kg_ae.cli etl

# Batch mode (no prompts)
uv run python -m kg_ae.cli etl --batch

# Force re-download and re-process
uv run python -m kg_ae.cli etl --batch --force
```

### By Dataset

```bash
# Run specific dataset with dependencies
uv run python -m kg_ae.cli etl --dataset sider

# Without dependencies
uv run python -m kg_ae.cli ingest sider
```

### By Tier

```bash
# Tier 1: Foundational (HGNC, DrugCentral)
uv run python -m kg_ae.cli etl --tier 1

# Tier 2: Extensions (Open Targets, Reactome, GtoPdb)
uv run python -m kg_ae.cli etl --tier 2

# Tier 3: Associations (SIDER, openFDA, CTD, STRING, ClinGen, HPO)
uv run python -m kg_ae.cli etl --tier 3

# Tier 4: Advanced (ChEMBL, FAERS)
uv run python -m kg_ae.cli etl --tier 4
```

### Individual Phases

```bash
# Download only
uv run python -m kg_ae.cli download sider

# Parse and load (full ingest)
uv run python -m kg_ae.cli ingest sider --force
```

## Dataset Dependency Graph

```
Tier 1 (Foundational)
  hgnc           (no deps)
  drugcentral    (no deps)

Tier 2 (Extensions)
  opentargets    <- hgnc
  reactome       <- hgnc
  gtop           <- hgnc, drugcentral

Tier 3 (Associations)
  sider          <- drugcentral
  openfda        <- drugcentral
  ctd            <- hgnc, drugcentral
  string         <- hgnc
  clingen        <- hgnc
  hpo            <- hgnc

Tier 4 (Advanced)
  chembl         <- hgnc, drugcentral
  faers          <- drugcentral
```

## Direct Python Usage

### Run Individual Dataset

```python
from kg_ae.etl.runner import ETLRunner

runner = ETLRunner()

# Run single dataset with dependencies
runner.run_dataset("sider", include_deps=True)

# Run without dependencies
runner.run_dataset("sider", include_deps=False)

# Force re-download
runner.run_dataset("sider", force=True)

# Run specific phases only
runner.run_dataset("sider", phases=["download", "parse"])
```

### Run Individual Components

```python
# Download
from kg_ae.datasets.sider import SiderDownloader
SiderDownloader().download(force=False)

# Parse
from kg_ae.datasets.sider import SiderParser
SiderParser().parse()

# Normalize (if applicable)
from kg_ae.datasets.sider import SiderNormalizer
SiderNormalizer().normalize()

# Load
from kg_ae.datasets.sider import SiderLoader
SiderLoader().load()
```

### One-liner for Any Dataset

```bash
# Pattern: download -> parse -> [normalize] -> load
uv run python -c "
from kg_ae.datasets.sider import *
SiderDownloader().download()
SiderParser().parse()
SiderNormalizer().normalize()
SiderLoader().load()
"
```

## Available Datasets

| Key | Name | Phases | Description |
|-----|------|--------|-------------|
| `hgnc` | HGNC Gene Nomenclature | D-P-L | Gene symbols and IDs |
| `drugcentral` | DrugCentral | D-P-N-L | Drug-target interactions |
| `opentargets` | Open Targets Platform | D-P-N-L | Gene-disease associations |
| `reactome` | Reactome Pathways | D-P-N-L | Biological pathways |
| `gtop` | Guide to Pharmacology | D-P-L | Pharmacological targets |
| `sider` | SIDER Drug-ADR | D-P-N-L | Drug side effects |
| `openfda` | openFDA FAERS | D-P-L | Adverse event reports |
| `ctd` | CTD Toxicogenomics | D-P-L | Chemical-gene-disease |
| `string` | STRING PPI | D-P-L | Protein interactions |
| `clingen` | ClinGen Validity | D-P-L | Gene-disease curation |
| `hpo` | Human Phenotype Ontology | D-P-L | Phenotype-disease |
| `chembl` | ChEMBL Bioactivity | D-P-L | Bioactivity data |
| `faers` | FDA FAERS Reports | D-P-L | Raw FAERS data |

Phases: D=Download, P=Parse, N=Normalize, L=Load

## Data Flow

```
data/raw/{dataset}/      <- Download (archives, TSV, JSON)
data/bronze/{dataset}/   <- Parse (Parquet, source-shaped)
data/silver/{dataset}/   <- Normalize (canonical IDs)
SQL Server kg.*          <- Load (graph tables)
```

## Troubleshooting

### Reset Pipeline State

In interactive mode, select option 5 to reset status indicators.

### Force Re-download

```bash
uv run python -m kg_ae.cli etl --dataset sider --force
```

### Check Individual Loader

```python
from kg_ae.datasets.sider import SiderLoader
loader = SiderLoader()
result = loader.load()
print(result)  # {'claims': 123456, ...}
```
