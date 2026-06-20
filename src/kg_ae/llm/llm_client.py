"""
Single OpenAI-compatible LLM client.

Both the development (OpenRouter) and deployment (local Ollama / LM Studio /
vLLM) paths speak the OpenAI-compatible protocol, so there is exactly one code
path. The only differences are ``llm_base_url`` and ``llm_model``.

A compliance guard runs at construction time: when ``airgapped`` is true the
base URL must be local, otherwise we refuse to build the client. This is the
runtime enforcement of the EU hospital "no patient data leaves the building"
requirement.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from kg_ae.config import settings


class ComplianceError(RuntimeError):
    """Raised when the configuration violates airgap/compliance rules."""


def enforce_compliance() -> None:
    """Abort if the current configuration violates compliance rules."""
    errors = settings.validate_compliance()
    if errors:
        raise ComplianceError("Compliance check failed:\n  - " + "\n  - ".join(errors))


def build_chat_model(
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """Build the LangChain chat model from settings.

    Args:
        model: Override the configured model id (for A/B experiments). Must
            still be an open-source model in deployment; defaults to settings.
        temperature: Override sampling temperature.
        max_tokens: Override max output tokens.

    Raises ComplianceError if airgapped mode is violated.
    """
    enforce_compliance()
    return ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.resolved_llm_api_key(),
        model=model or settings.llm_model,
        temperature=settings.llm_temperature if temperature is None else temperature,
        max_tokens=settings.llm_max_tokens if max_tokens is None else max_tokens,
        timeout=120,
    )


def llm_summary() -> str:
    """Human-readable summary of the active LLM configuration."""
    return (
        f"provider={settings.llm_provider} model={settings.llm_model} "
        f"base_url={settings.llm_base_url} airgapped={settings.airgapped} "
        f"web_search={'on' if settings.web_search_enabled() else 'off'}"
    )
