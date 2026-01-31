"""
Base classes for dataset handlers.

All dataset modules should inherit from these base classes to ensure
consistent interface and behavior.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from kg_ae.config import settings


@dataclass
class DatasetMetadata:
    """Metadata about a downloaded dataset."""

    source_key: str
    version: str | None
    download_url: str
    local_path: Path
    sha256: str | None
    downloaded_at: datetime
    license_name: str | None
    row_count: int | None = None


class BaseDownloader(ABC):
    """Base class for dataset downloaders."""

    source_key: str
    base_url: str
    license_name: str | None = None

    def __init__(self):
        self.raw_dir = settings.raw_dir / self.source_key
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def download(self, force: bool = False) -> list[DatasetMetadata]:
        """
        Download raw data files.

        Args:
            force: Re-download even if files exist

        Returns:
            List of metadata for downloaded files
        """
        pass

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _fetch_url(self, url: str, dest: Path, timeout: float = 300.0) -> None:
        """
        Fetch a URL to a local file with retries.

        Args:
            url: URL to fetch
            dest: Destination file path
            timeout: Request timeout in seconds
        """
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            response.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)

    def _compute_sha256(self, path: Path) -> str:
        """Compute SHA256 hash of a file."""
        import hashlib

        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()


class BaseParser(ABC):
    """Base class for dataset parsers (raw → bronze)."""

    source_key: str

    def __init__(self):
        self.raw_dir = settings.raw_dir / self.source_key
        self.bronze_dir = settings.bronze_dir / self.source_key
        self.bronze_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def parse(self) -> dict[str, Path]:
        """
        Parse raw files to bronze (source-shaped Parquet/CSV).

        Returns:
            Dict mapping table names to output file paths
        """
        pass


class BaseNormalizer(ABC):
    """Base class for dataset normalizers (bronze → silver)."""

    source_key: str

    def __init__(self):
        self.bronze_dir = settings.bronze_dir / self.source_key
        self.silver_dir = settings.silver_dir / self.source_key
        self.silver_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def normalize(self) -> dict[str, Path]:
        """
        Normalize bronze data to silver (canonical IDs applied).

        Returns:
            Dict mapping table names to output file paths
        """
        pass


class BaseLoader(ABC):
    """Base class for dataset loaders (silver → SQL Server)."""

    source_key: str
    dataset_name: str
    dataset_version: str | None = None
    license_name: str | None = None

    def __init__(self):
        from kg_ae.db import get_connection, execute

        self.silver_dir = settings.silver_dir / self.source_key
        self.conn = get_connection()
        self._execute = execute

    @abstractmethod
    def load(self) -> dict[str, int]:
        """
        Load silver data into SQL Server graph tables.

        Returns:
            Dict mapping table names to row counts loaded
        """
        pass

    def ensure_dataset(
        self,
        dataset_key: str,
        dataset_name: str,
        dataset_version: str | None = None,
        license_name: str | None = None,
        source_url: str | None = None,
    ) -> int:
        """
        Ensure dataset is registered in kg.Dataset.

        Returns:
            dataset_id for the dataset
        """
        version_key = dataset_version or ""

        # Check if exists
        rows = self._execute(
            "SELECT dataset_id FROM kg.Dataset WHERE dataset_key = ? AND version_key = ?",
            (dataset_key, version_key),
        )
        if rows:
            return rows[0][0]

        # Insert and get the ID using SCOPE_IDENTITY
        from kg_ae.db import get_connection
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO kg.Dataset 
                    (dataset_key, dataset_name, dataset_version, license_name, source_url)
                VALUES (?, ?, ?, ?, ?);
                SELECT SCOPE_IDENTITY();
                """,
                dataset_key, dataset_name, dataset_version, license_name, source_url,
            )
            # Move to the SELECT result set
            cursor.nextset()
            row = cursor.fetchone()
            conn.commit()
            if row and row[0]:
                return int(row[0])

        # Fallback: query for it
        rows = self._execute(
            "SELECT dataset_id FROM kg.Dataset WHERE dataset_key = ? AND version_key = ?",
            (dataset_key, version_key),
        )
        return rows[0][0]
