"""Settings. PV_* variables and two API keys, all from the environment or .env."""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PV_", env_file=".env", extra="ignore")

    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "deepseek/deepseek-v4.1-flash"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 4096

    allow_web_search: bool = True
    web_domains: list[str] = [
        "ema.europa.eu",
        "fda.gov",
        "mhra.gov.uk",
        "ansm.sante.fr",
        "bfarm.de",
        "who.int",
        "ebi.ac.uk",
        "nih.gov",
        "europepmc.org",
    ]

    @property
    def openrouter_key(self) -> str | None:
        return os.getenv("OPENROUTER_API_KEY")

    @property
    def tavily_key(self) -> str | None:
        return os.getenv("TAVILY_API_KEY")

    def web_search_enabled(self) -> bool:
        return self.allow_web_search and bool(self.tavily_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
