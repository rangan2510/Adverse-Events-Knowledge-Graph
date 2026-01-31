"""Tests for database connection module.

These tests require a live database connection.
Run with: uv run pytest tests/test_db_connection.py --run-db
"""

import pytest

from kg_ae.db import execute, get_connection

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def db_connection():
    """Provide a database connection for tests."""
    with get_connection() as conn:
        yield conn


def test_connection_context_manager():
    """Test that connection context manager works."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 AS test_value")
        row = cursor.fetchone()
        assert row[0] == 1


def test_execute_select():
    """Test execute helper with SELECT."""
    rows = execute("SELECT DB_NAME() AS db_name")
    assert len(rows) == 1
    assert rows[0][0] == "kg_ae"


def test_execute_with_params():
    """Test execute helper with parameters."""
    rows = execute("SELECT ? AS value", (42,))
    assert len(rows) == 1
    assert rows[0][0] == 42


def test_sql_server_version():
    """Test that we're connected to SQL Server 2025."""
    rows = execute("SELECT @@VERSION")
    version_str = rows[0][0]
    assert "Microsoft SQL Server 2025" in version_str
