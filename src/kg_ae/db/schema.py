"""
Database schema management.

Initializes the kg.* schema in SQL Server 2025 with graph tables.
"""

from pathlib import Path

from kg_ae.db.connection import execute_script

SCHEMA_FILE = Path(__file__).parent.parent.parent.parent / "docs" / "schema.md"


def load_schema_sql(schema_path: Path) -> str:
    """
    Load SQL schema from file.

    The schema.md file is raw SQL with comment headers (not markdown code blocks).
    """
    return schema_path.read_text(encoding="utf-8")


def init_schema() -> None:
    """
    Initialize the database schema from docs/schema.md.

    This creates:
    - kg schema namespace
    - Relational metadata tables (Dataset, IngestRun)
    - NODE tables (Drug, Gene, Disease, Pathway, AdverseEvent, Claim, Evidence)
    - EDGE tables (HasClaim, ClaimGene, ClaimDisease, ClaimPathway, ClaimAdverseEvent, SupportedBy)
    """
    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_FILE}")

    sql = load_schema_sql(SCHEMA_FILE)
    execute_script(sql)


def drop_schema() -> None:
    """
    Drop all kg.* tables (for testing/reset).

    WARNING: This destroys all data!
    """
    drop_sql = """
    -- Drop edges first (dependency order)
    DROP TABLE IF EXISTS kg.SupportedBy;
    DROP TABLE IF EXISTS kg.ClaimAdverseEvent;
    DROP TABLE IF EXISTS kg.ClaimPathway;
    DROP TABLE IF EXISTS kg.ClaimDisease;
    DROP TABLE IF EXISTS kg.ClaimGene;
    DROP TABLE IF EXISTS kg.HasClaim;

    -- Drop nodes
    DROP TABLE IF EXISTS kg.Evidence;
    DROP TABLE IF EXISTS kg.Claim;
    DROP TABLE IF EXISTS kg.AdverseEvent;
    DROP TABLE IF EXISTS kg.Pathway;
    DROP TABLE IF EXISTS kg.Disease;
    DROP TABLE IF EXISTS kg.Gene;
    DROP TABLE IF EXISTS kg.Drug;

    -- Drop relational
    DROP TABLE IF EXISTS kg.IngestRun;
    DROP TABLE IF EXISTS kg.Dataset;
    """
    execute_script(drop_sql)
