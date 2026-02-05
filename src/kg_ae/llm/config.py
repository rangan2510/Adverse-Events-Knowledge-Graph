"""
Configuration for LLM orchestration layer.

Supports two providers:
- "local": llama.cpp servers (Phi-4-mini + Phi-4)
- "groq": Groq Cloud API (gpt-oss-20b with reasoning)

All settings configurable via environment variables.
See .env for full configuration options.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


def _env_float(key: str, default: float) -> float:
    """Get float from environment variable."""
    val = os.getenv(key)
    return float(val) if val else default


def _env_int(key: str, default: int) -> int:
    """Get int from environment variable."""
    val = os.getenv(key)
    return int(val) if val else default


@dataclass
class LLMConfig:
    """Configuration for LLM servers and execution."""
    
    # Provider selection: "local" (llama.cpp) or "groq" (Groq Cloud)
    provider: Literal["local", "groq"] = field(
        default_factory=lambda: os.getenv("KG_AE_LLM_PROVIDER", "local")
    )
    
    # -------------------------------------------------------------------------
    # Groq Cloud settings (gpt-oss-20b is a reasoning model)
    # -------------------------------------------------------------------------
    groq_api_key: str | None = field(
        default_factory=lambda: os.getenv("GROQ_API_KEY")
    )
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = field(
        default_factory=lambda: os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    )
    # Higher tokens for reasoning - gpt-oss uses 100-500 tokens for internal reasoning
    groq_planner_max_tokens: int = field(
        default_factory=lambda: _env_int("GROQ_PLANNER_MAX_TOKENS", 4096)
    )
    groq_narrator_max_tokens: int = field(
        default_factory=lambda: _env_int("GROQ_NARRATOR_MAX_TOKENS", 8192)
    )
    groq_planner_temperature: float = field(
        default_factory=lambda: _env_float("GROQ_PLANNER_TEMPERATURE", 0.1)
    )
    groq_narrator_temperature: float = field(
        default_factory=lambda: _env_float("GROQ_NARRATOR_TEMPERATURE", 0.3)
    )
    
    # -------------------------------------------------------------------------
    # Local llama.cpp settings
    # -------------------------------------------------------------------------
    local_planner_url: str = field(
        default_factory=lambda: os.getenv("LOCAL_PLANNER_URL", "http://127.0.0.1:8081/v1")
    )
    local_planner_model: str = field(
        default_factory=lambda: os.getenv("LOCAL_PLANNER_MODEL", "phi4mini")
    )
    local_planner_max_tokens: int = field(
        default_factory=lambda: _env_int("LOCAL_PLANNER_MAX_TOKENS", 1024)
    )
    local_planner_temperature: float = field(
        default_factory=lambda: _env_float("LOCAL_PLANNER_TEMPERATURE", 0.1)
    )
    
    local_narrator_url: str = field(
        default_factory=lambda: os.getenv("LOCAL_NARRATOR_URL", "http://127.0.0.1:8082/v1")
    )
    local_narrator_model: str = field(
        default_factory=lambda: os.getenv("LOCAL_NARRATOR_MODEL", "phi4")
    )
    local_narrator_max_tokens: int = field(
        default_factory=lambda: _env_int("LOCAL_NARRATOR_MAX_TOKENS", 2048)
    )
    local_narrator_temperature: float = field(
        default_factory=lambda: _env_float("LOCAL_NARRATOR_TEMPERATURE", 0.3)
    )
    
    # -------------------------------------------------------------------------
    # Execution limits
    # -------------------------------------------------------------------------
    max_tool_calls: int = 20
    tool_timeout: int = 30
    
    # Model paths (for local validation only)
    models_dir: Path = Path("D:/llm/models")
    planner_model_path: Path = Path("D:/llm/models/phi4mini.Q4_K_M.gguf")
    narrator_model_path: Path = Path("D:/llm/models/phi4.Q4_K_M.gguf")
    
    # -------------------------------------------------------------------------
    # Getter methods - return provider-appropriate values
    # -------------------------------------------------------------------------
    
    def get_planner_url(self) -> str:
        """Get planner API URL based on provider."""
        return self.groq_base_url if self.provider == "groq" else self.local_planner_url
    
    def get_planner_model(self) -> str:
        """Get planner model name based on provider."""
        return self.groq_model if self.provider == "groq" else self.local_planner_model
    
    def get_planner_max_tokens(self) -> int:
        """Get planner max tokens based on provider."""
        return self.groq_planner_max_tokens if self.provider == "groq" else self.local_planner_max_tokens
    
    def get_planner_temperature(self) -> float:
        """Get planner temperature based on provider."""
        return self.groq_planner_temperature if self.provider == "groq" else self.local_planner_temperature
    
    def get_narrator_url(self) -> str:
        """Get narrator API URL based on provider."""
        return self.groq_base_url if self.provider == "groq" else self.local_narrator_url
    
    def get_narrator_model(self) -> str:
        """Get narrator model name based on provider."""
        return self.groq_model if self.provider == "groq" else self.local_narrator_model
    
    def get_narrator_max_tokens(self) -> int:
        """Get narrator max tokens based on provider."""
        return self.groq_narrator_max_tokens if self.provider == "groq" else self.local_narrator_max_tokens
    
    def get_narrator_temperature(self) -> float:
        """Get narrator temperature based on provider."""
        return self.groq_narrator_temperature if self.provider == "groq" else self.local_narrator_temperature
    
    def get_api_key(self) -> str:
        """Get API key (only needed for Groq)."""
        if self.provider == "groq":
            if not self.groq_api_key:
                raise ValueError("GROQ_API_KEY environment variable not set")
            return self.groq_api_key
        return "not-needed"  # Local llama-server doesn't check
    
    def validate(self) -> list[str]:
        """Validate configuration, return list of errors."""
        errors = []
        
        if self.provider == "groq":
            if not self.groq_api_key:
                errors.append("GROQ_API_KEY not set (required for Groq provider)")
        else:
            if not self.planner_model_path.exists():
                errors.append(f"Planner model not found: {self.planner_model_path}")
            if not self.narrator_model_path.exists():
                errors.append(f"Narrator model not found: {self.narrator_model_path}")
        
        return errors
    
    def summary(self) -> str:
        """Return a summary of current configuration."""
        return (
            f"Provider: {self.provider}\n"
            f"Planner: {self.get_planner_model()} @ {self.get_planner_url()}\n"
            f"  max_tokens={self.get_planner_max_tokens()}, temp={self.get_planner_temperature()}\n"
            f"Narrator: {self.get_narrator_model()} @ {self.get_narrator_url()}\n"
            f"  max_tokens={self.get_narrator_max_tokens()}, temp={self.get_narrator_temperature()}"
        )


# Default configuration
DEFAULT_CONFIG = LLMConfig()
