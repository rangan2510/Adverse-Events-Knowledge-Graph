"""
Configuration management for kg_ae.

Uses pydantic-settings for environment variable loading and validation.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="KG_AE_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # SQL Server connection
    db_server: str = Field(default="localhost", description="SQL Server hostname")
    db_name: str = Field(default="kg_ae", description="Database name")
    db_driver: str = Field(
        default="ODBC Driver 18 for SQL Server",
        description="ODBC driver name",
    )
    db_trusted_connection: bool = Field(
        default=True,
        description="Use Windows authentication",
    )
    db_username: str | None = Field(default=None, description="SQL username (if not trusted)")
    db_password: str | None = Field(default=None, description="SQL password (if not trusted)")

    # Data directories
    data_dir: Path = Field(default=Path("data"), description="Root data directory")

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )

    @property
    def raw_dir(self) -> Path:
        """Directory for raw downloaded files."""
        return self.data_dir / "raw"

    @property
    def bronze_dir(self) -> Path:
        """Directory for parsed source-shaped data."""
        return self.data_dir / "bronze"

    @property
    def silver_dir(self) -> Path:
        """Directory for normalized data with canonical IDs."""
        return self.data_dir / "silver"

    @property
    def gold_dir(self) -> Path:
        """Directory for graph-ready edge tables."""
        return self.data_dir / "gold"

    def connection_string(self) -> str:
        """Build connection string for mssql-python.

        Format: SERVER=host;DATABASE=db;UID=user;PWD=pass;...
        Note: mssql-python handles the ODBC driver internally.
        """
        parts = [
            f"SERVER={self.db_server}",
            f"DATABASE={self.db_name}",
        ]
        if self.db_trusted_connection:
            parts.append("Trusted_Connection=yes")
        else:
            if self.db_username:
                parts.append(f"UID={self.db_username}")
            if self.db_password:
                parts.append(f"PWD={self.db_password}")
        # SQL Server 2025 - trust server certificate for local dev
        parts.append("TrustServerCertificate=yes")
        parts.append("Encrypt=yes")
        return ";".join(parts)


# Global settings instance
settings = Settings()
