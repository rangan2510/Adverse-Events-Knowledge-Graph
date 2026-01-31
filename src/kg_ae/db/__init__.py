"""
Database utilities for SQL Server 2025.

Provides connection management, schema initialization, and bulk loading utilities.
"""

from kg_ae.db.connection import execute, execute_many, get_connection
from kg_ae.db.schema import init_schema

__all__ = ["get_connection", "execute", "execute_many", "init_schema"]
