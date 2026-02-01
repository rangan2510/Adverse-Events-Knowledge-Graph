"""
ETL pipeline orchestration.

Coordinates the flow:
1. Download raw data (datasets/*/download.py)
2. Parse to bronze (datasets/*/parse.py)
3. Normalize to silver (datasets/*/normalize.py)
4. Load to gold / SQL Server graph tables

Provides:
- Interactive dashboard with live status
- Dependency-aware execution order
- Selective dataset/tier execution
- Checkpointing and incremental updates

Usage:
    from kg_ae.etl.runner import ETLRunner
    runner = ETLRunner()
    runner.run_interactive()
"""

from kg_ae.etl.runner import ETLRunner

__all__ = ["ETLRunner"]
