"""
Configuration management for kg_ae.

Uses pydantic-settings for environment variable loading and validation.

The runtime is file-based and local-first:
- The knowledge graph lives in ``data/graph/*.json`` (no database server).
- The LLM is reached over a single OpenAI-compatible endpoint. In development
  this is OpenRouter; in an airgapped hospital deployment the same code points
  at a local server (Ollama / LM Studio / vLLM) by changing ``llm_base_url``.

Web search (Tavily) is an optional, online-only capability. It is disabled
automatically when ``airgapped`` is true, so the airgapped build is the exact
same code minus one registered tool.
"""

from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env into os.environ so non-prefixed secrets (OPENROUTER_API_KEY,
# TAVILY_API_KEY) are visible to os.getenv fallbacks. Prefixed KG_AE_* vars are
# handled by pydantic-settings below.
load_dotenv()

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="KG_AE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # allow unrelated env vars (HF_TOKEN, etc.)
    )

    # -------------------------------------------------------------------------
    # Data directories
    # -------------------------------------------------------------------------
    data_dir: Path = Field(default=Path("data"), description="Root data directory")

    # -------------------------------------------------------------------------
    # LLM (single OpenAI-compatible endpoint)
    # -------------------------------------------------------------------------
    # Provider is a label only; both paths use the OpenAI-compatible protocol.
    #   "openrouter" -> dev stand-in for the local model (cloud)
    #   "local"      -> Ollama / LM Studio / vLLM on localhost
    llm_provider: Literal["openrouter", "local"] = Field(
        default="openrouter",
        description="LLM provider label (openrouter for dev, local for deployment)",
    )
    llm_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="OpenAI-compatible base URL",
    )
    llm_model: str = Field(
        default="mistralai/mistral-small-3.2-24b-instruct",
        description="Model name (open-source preferred; Mistral/Gemma for EU deployment)",
    )
    llm_api_key: str | None = Field(
        default=None,
        description="API key for the LLM endpoint (falls back to OPENROUTER_API_KEY)",
    )
    llm_temperature: float = Field(default=0.1, description="Sampling temperature")
    llm_max_tokens: int = Field(default=4096, description="Max output tokens")

    # Multi-agent ensemble (self-consistency). 1 = single agent.
    agent_ensemble_size: int = Field(
        default=1,
        ge=1,
        le=7,
        description="Number of agents to run and reconcile per query",
    )
    max_iterations: int = Field(default=8, description="Max ReAct iterations per agent")

    # -------------------------------------------------------------------------
    # Compliance / airgap
    # -------------------------------------------------------------------------
    airgapped: bool = Field(
        default=False,
        description="When true, block all non-localhost network access (LLM + web search)",
    )
    allow_web_search: bool = Field(
        default=True,
        description="Enable the Tavily web-search tool (ignored when airgapped)",
    )
    tavily_api_key: str | None = Field(
        default=None,
        description="Tavily API key (falls back to TAVILY_API_KEY)",
    )

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )

    # -------------------------------------------------------------------------
    # ETL downloads
    # -------------------------------------------------------------------------
    use_aria2: bool = Field(
        default=True,
        description="Use aria2c (multi-connection, resumable) for downloads when available.",
    )
    download_concurrency: int = Field(
        default=4,
        description="Number of datasets to download in parallel during staging.",
    )
    download_timeout: float = Field(
        default=3600.0,
        description="Hard wall-clock ceiling (seconds) for a single aria2c download batch.",
    )

    # -------------------------------------------------------------------------
    # Derived directories
    # -------------------------------------------------------------------------
    @property
    def raw_dir(self) -> Path:
        """Downloaded source files."""
        return self.data_dir / "raw"

    @property
    def bronze_dir(self) -> Path:
        """Parsed source-shaped Parquet."""
        return self.data_dir / "bronze"

    @property
    def silver_dir(self) -> Path:
        """Normalized Parquet with canonical IDs."""
        return self.data_dir / "silver"

    @property
    def graph_dir(self) -> Path:
        """Built JSON graph (nodes.json, edges.json, meta.json)."""
        return self.data_dir / "graph"

    # -------------------------------------------------------------------------
    # Compliance helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def _is_local_url(url: str) -> bool:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        return host in LOCAL_HOSTS

    def web_search_enabled(self) -> bool:
        """Web search is on only when explicitly allowed and not airgapped."""
        return self.allow_web_search and not self.airgapped

    def validate_compliance(self) -> list[str]:
        """Return a list of compliance violations for the current config.

        In airgapped mode the LLM endpoint must be local and web search must be
        off. This is the runtime guardrail for the EU hospital deployment.
        """
        errors: list[str] = []
        if self.airgapped:
            if not self._is_local_url(self.llm_base_url):
                errors.append(f"airgapped=true but llm_base_url is not local: {self.llm_base_url}")
            if self.allow_web_search:
                errors.append("airgapped=true but allow_web_search is true (web search must be off)")
        return errors

    def resolved_llm_api_key(self) -> str:
        """LLM API key from settings or the OPENROUTER_API_KEY env var.

        Local servers usually ignore the key, so a placeholder is returned when
        none is configured.
        """
        import os

        return self.llm_api_key or os.getenv("OPENROUTER_API_KEY") or "not-needed"

    def resolved_tavily_api_key(self) -> str | None:
        """Tavily API key from settings or the TAVILY_API_KEY env var."""
        import os

        return self.tavily_api_key or os.getenv("TAVILY_API_KEY")


# Global settings instance
settings = Settings()
