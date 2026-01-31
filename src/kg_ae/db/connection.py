"""
SQL Server connection management.

Uses mssql-python (Microsoft's native Python driver) for database access.
https://github.com/microsoft/mssql-python
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import mssql_python
from mssql_python import connect as mssql_connect
from mssql_python.connection import Connection

from kg_ae.config import settings


@contextmanager
def get_connection() -> Generator[Connection, None, None]:
    """
    Get a database connection as a context manager.

    Usage:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
    """
    conn = mssql_connect(settings.connection_string())
    try:
        yield conn
    finally:
        conn.close()


def execute(sql: str, params: tuple | None = None, commit: bool = True) -> list[Any]:
    """
    Execute a SQL query and return all rows.

    Args:
        sql: SQL statement to execute
        params: Optional parameters for parameterized queries
        commit: Whether to commit the transaction (default True for writes)

    Returns:
        List of result rows
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, *params)
        else:
            cursor.execute(sql)
        try:
            rows = cursor.fetchall()
        except mssql_python.ProgrammingError:
            # No results (e.g., INSERT/UPDATE)
            rows = []
        if commit:
            conn.commit()
        return rows


def execute_many(sql: str, params_list: list[tuple]) -> int:
    """
    Execute a SQL statement with multiple parameter sets (batch insert).

    Args:
        sql: SQL statement with parameter placeholders
        params_list: List of parameter tuples

    Returns:
        Number of rows affected
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(sql, params_list)
        conn.commit()
        return cursor.rowcount


def execute_script(sql_script: str) -> None:
    """
    Execute a multi-statement SQL script.

    Splits on 'GO' statements for SQL Server compatibility.
    Handles GO on its own line (with optional whitespace).

    Args:
        sql_script: SQL script with GO separators
    """
    import re

    with get_connection() as conn:
        cursor = conn.cursor()
        # Split on GO statements (case insensitive, on own line)
        # Matches: \nGO\n, \nGO (end of file), GO\n (start of batch)
        batches = re.split(r"(?m)^\s*GO\s*$", sql_script, flags=re.IGNORECASE)
        for batch in batches:
            batch = batch.strip()
            if batch:
                cursor.execute(batch)
        conn.commit()
