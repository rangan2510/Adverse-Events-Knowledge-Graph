"""One model factory. Everything talks to the same OpenAI-compatible endpoint."""

from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI

from pv_agent.config import get_settings


@lru_cache(maxsize=2)
def build_model(*, streaming: bool = False) -> ChatOpenAI:
    s = get_settings()
    openrouter = "openrouter.ai" in s.llm_base_url
    if openrouter and not s.openrouter_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    extra: dict = {}
    if openrouter:
        # Providers that keep prompts private. Do not add require_parameters: no DeepSeek
        # provider advertises parallel_tool_calls, and the router then 404s with
        # "No endpoints found that can handle the requested parameters".
        extra["provider"] = {"data_collection": "deny"}
        extra["max_tokens"] = s.llm_max_tokens
        if s.llm_model.startswith("deepseek/"):
            extra["reasoning"] = {"effort": "low"}

    return ChatOpenAI(
        model=s.llm_model,
        api_key=s.openrouter_key or "local-no-key",
        base_url=s.llm_base_url,
        temperature=s.llm_temperature,
        max_completion_tokens=None if openrouter else s.llm_max_tokens,
        disabled_params={"parallel_tool_calls": None},
        streaming=streaming,
        timeout=120,
        max_retries=1,
        extra_body=extra,
    )
