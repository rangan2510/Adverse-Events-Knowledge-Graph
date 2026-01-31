# Setup Guide

## Database

SQL Server 2025 required. Configure via environment variables or `.env`:

```env
DB_SERVER=localhost
DB_DATABASE=kg_ae
DB_USER=sa
DB_PASSWORD=password1$
```

Create the database:
```sql
CREATE DATABASE kg_ae;
```

Deploy schema:
```bash
uv run kg-ae init-db
```

## ETL Order

Data sources should be loaded in this order (dependency chain):

1. **SIDER** - establishes Drug and AdverseEvent entities
2. **DrugCentral** - adds Gene entities and Drug→Gene edges  
3. **Reactome** - adds Pathway entities and Gene→Pathway edges
4. **Open Targets** - adds Disease entities and Gene→Disease edges

### Load All

```bash
uv run python scripts/load_all.py
```

### Load Individual Sources

```bash
# SIDER (Drug → Adverse Event)
uv run python -c "from kg_ae.datasets.sider import *; SIDERDownloader().download(); SIDERParser().parse(); SIDERNormalizer().normalize(); SIDERLoader().load()"

# DrugCentral (Drug → Gene)
uv run python -c "from kg_ae.datasets.drugcentral import *; DrugCentralDownloader().download(); DrugCentralParser().parse(); DrugCentralNormalizer().normalize(); DrugCentralLoader().load()"

# Reactome (Gene → Pathway)
uv run python -c "from kg_ae.datasets.reactome import *; ReactomeDownloader().download(); ReactomeParser().parse(); ReactomeNormalizer().normalize(); ReactomeLoader().load()"

# Open Targets (Gene → Disease)
uv run python -c "from kg_ae.datasets.opentargets import *; OpenTargetsDownloader().download(); OpenTargetsParser().parse(); OpenTargetsNormalizer().normalize(); OpenTargetsLoader().load()"
```

## Verify

```bash
uv run python -c "
from kg_ae.db import get_connection
with get_connection() as conn:
    for t in ['Drug','Gene','Pathway','Disease','AdverseEvent','Claim']:
        r = list(conn.execute(f'SELECT COUNT(*) FROM kg.{t}'))
        print(f'{t}: {r[0][0]:,}')
"
```
