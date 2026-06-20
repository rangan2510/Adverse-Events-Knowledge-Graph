"""Tests for the configuration module (file-based, local-first)."""

from kg_ae.config import Settings


def test_default_settings():
    """Default settings are valid."""
    s = Settings()
    assert s.llm_provider in ("openrouter", "local")
    assert s.log_level == "INFO"
    assert s.llm_base_url.startswith("http")


def test_data_directories():
    """Data directory properties resolve under the data dir."""
    s = Settings()
    assert s.raw_dir.name == "raw"
    assert s.bronze_dir.name == "bronze"
    assert s.silver_dir.name == "silver"
    assert s.graph_dir.name == "graph"


def test_web_search_disabled_when_airgapped():
    """Airgapped mode forces web search off regardless of allow flag."""
    s = Settings(airgapped=True, allow_web_search=True)
    assert s.web_search_enabled() is False


def test_web_search_enabled_when_online():
    """Web search is on when allowed and not airgapped."""
    s = Settings(airgapped=False, allow_web_search=True)
    assert s.web_search_enabled() is True


def test_compliance_blocks_remote_llm_when_airgapped():
    """Airgapped mode with a remote LLM endpoint is a compliance violation."""
    s = Settings(
        airgapped=True,
        allow_web_search=False,
        llm_base_url="https://openrouter.ai/api/v1",
    )
    errors = s.validate_compliance()
    assert any("not local" in e for e in errors)


def test_compliance_ok_with_local_llm_airgapped():
    """Airgapped mode with a localhost endpoint and no web search passes."""
    s = Settings(
        airgapped=True,
        allow_web_search=False,
        llm_base_url="http://localhost:11434/v1",
    )
    assert s.validate_compliance() == []


def test_compliance_ok_when_online():
    """Online mode has no compliance constraints."""
    s = Settings(airgapped=False)
    assert s.validate_compliance() == []
