"""
Base classes for dataset handlers.

All dataset modules should inherit from these base classes to ensure
consistent interface and behavior.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from kg_ae.config import settings
from kg_ae.etl.aria2 import DownloadSpec, fetch_specs
from kg_ae.etl.logging import get_logger

log = get_logger("kg_ae.etl.download")


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
    """Base class for dataset downloaders.

    Two ways to define a downloader:

    1. **Declarative (preferred for plain file URLs):** override
       :meth:`download_specs` to return a list of ``(url, dest)`` specs. The
       default :meth:`download` then batches them through aria2c (parallel,
       resumable, retried) and builds the metadata + cache-skip uniformly.
    2. **Imperative (for paginated APIs / directory listings):** override
       :meth:`download` directly and use :meth:`_fetch_url` for any single
       files that still need fetching.
    """

    source_key: str
    base_url: str = ""
    license_name: str | None = None
    version: str | None = None

    def __init__(self):
        self.raw_dir = settings.raw_dir / self.source_key
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download_specs(self) -> list[DownloadSpec]:
        """Return the files this dataset needs. Override for declarative sources.

        The default returns an empty list; an imperative downloader overriding
        :meth:`download` does not need this.
        """
        return []

    def download(self, force: bool = False) -> list[DatasetMetadata]:
        """Download declared specs via aria2c (or httpx fallback).

        Skips files already on disk unless ``force``. Subclasses with paginated
        APIs or directory listings should override this method instead.
        """
        specs = self.download_specs()
        if not specs:
            return []

        pending = specs if force else [s for s in specs if not s.dest.exists()]
        for s in specs:
            if s not in pending:
                log.info("etl.download.cached", source=self.source_key, file=s.dest.name)
        _downloaded, failed = fetch_specs(pending)
        if failed:
            raise RuntimeError(f"{self.source_key}: failed to download {[s.dest.name for s in failed]}")

        results: list[DatasetMetadata] = []
        for s in specs:
            sha256 = self._compute_sha256(s.dest) if s.dest.exists() else None
            results.append(
                DatasetMetadata(
                    source_key=self.source_key,
                    version=self.version,
                    download_url=s.url,
                    local_path=s.dest,
                    sha256=sha256,
                    downloaded_at=datetime.now(UTC),
                    license_name=self.license_name,
                )
            )
        return results

    def _fetch_url(self, url: str, dest: Path, timeout: float = 600.0) -> None:
        """Fetch a single URL to ``dest`` (aria2c when available, else httpx).

        Used by imperative downloaders. Honors the same aria2c batch helper with
        a single-spec list so behavior is consistent everywhere.
        """
        _downloaded, failed = fetch_specs([DownloadSpec(url=url, dest=dest, source=self.source_key)])
        if failed:
            raise RuntimeError(f"failed to download {url}")

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
