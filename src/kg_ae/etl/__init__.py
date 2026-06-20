"""
ETL pipeline orchestration.

Coordinates the flow:
1. Download raw data (datasets/*/download.py)
2. Parse to bronze (datasets/*/parse.py)
3. Normalize to silver (datasets/*/normalize.py)

The knowledge graph itself is built separately from the silver Parquet by
``kg_ae.graph.build`` (``kg-ae build-graph``), which emits file-based JSON.

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
