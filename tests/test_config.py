"""Tests for configuration module."""

from kg_ae.config import Settings


def test_default_settings():
    """Test that default settings are valid."""
    s = Settings()
    assert s.db_server == "localhost"
    assert s.db_name == "kg_ae"
    assert s.log_level == "INFO"


def test_data_directories():
    """Test that data directory properties work."""
    s = Settings()
    assert s.raw_dir.name == "raw"
    assert s.bronze_dir.name == "bronze"
    assert s.silver_dir.name == "silver"
    assert s.gold_dir.name == "gold"


def test_connection_string_trusted():
    """Test connection string with Windows auth."""
    s = Settings(db_trusted_connection=True)
    conn_str = s.connection_string()
    assert "Trusted_Connection=yes" in conn_str
    assert "localhost" in conn_str


def test_connection_string_sql_auth():
    """Test connection string with SQL auth."""
    s = Settings(
        db_trusted_connection=False,
        db_username="testuser",
        db_password="testpass",
    )
    conn_str = s.connection_string()
    assert "UID=testuser" in conn_str
    assert "PWD=testpass" in conn_str
