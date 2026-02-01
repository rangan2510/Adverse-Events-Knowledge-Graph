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
uv run python -m kg_ae.cli init-db
```

## ETL Pipeline

The ETL runner handles dependency ordering automatically. See [etl-guide.md](etl-guide.md) for full documentation.

### Interactive Mode (Recommended)

```bash
uv run python -m kg_ae.cli etl
```

Live dashboard shows status for all 13 datasets across 4 tiers:
- Tier 1: HGNC, DrugCentral (foundational)
- Tier 2: Open Targets, Reactome, GtoPdb (extensions)
- Tier 3: SIDER, openFDA, CTD, STRING, ClinGen, HPO (associations)
- Tier 4: ChEMBL, FAERS (advanced)

### Batch Mode

```bash
# Run everything
uv run python -m kg_ae.cli etl --batch

# Run specific tier
uv run python -m kg_ae.cli etl --tier 1

# Run specific dataset (with dependencies)
uv run python -m kg_ae.cli etl --dataset sider

# Force re-download
uv run python -m kg_ae.cli etl --batch --force
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
