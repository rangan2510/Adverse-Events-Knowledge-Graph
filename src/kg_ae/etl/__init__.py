"""
ETL pipeline orchestration.

Coordinates the flow:
1. Download raw data (datasets/*/download.py)
2. Parse to bronze (datasets/*/parse.py)
3. Normalize to silver (datasets/*/normalize.py)
4. Load to gold / SQL Server graph tables

Provides checkpointing and incremental updates.
"""
