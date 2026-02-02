"""
Configuration for LLM orchestration layer.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class LLMConfig:
    """Configuration for LLM servers and execution."""
    
    # Planner LLM settings (Phi-4-mini-instruct)
    planner_url: str = "http://127.0.0.1:8081/v1"
    planner_model: str = "phi4mini"
    planner_temperature: float = 0.1  # Low temp for deterministic tool planning
    planner_max_tokens: int = 1024  # Allow longer thought + 5 tool calls
    
    # Narrator LLM settings (Phi-4 - larger model for better narration)
    narrator_url: str = "http://127.0.0.1:8082/v1"
    narrator_model: str = "phi4"
    narrator_temperature: float = 0.3  # Slightly higher for natural prose
    narrator_max_tokens: int = 2048
    
    # Execution limits
    max_tool_calls: int = 20  # Maximum tool calls per query
    tool_timeout: int = 30  # Seconds per tool call
    
    # Model paths (for reference)
    models_dir: Path = Path("D:/llm/models")
    planner_model_path: Path = Path("D:/llm/models/phi4mini.Q4_K_M.gguf")
    narrator_model_path: Path = Path("D:/llm/models/phi4.Q4_K_M.gguf")
    
    def validate(self) -> list[str]:
        """Validate configuration, return list of errors."""
        errors = []
        
        if not self.planner_model_path.exists():
            errors.append(f"Planner model not found: {self.planner_model_path}")
        
        if not self.narrator_model_path.exists():
            errors.append(f"Narrator model not found: {self.narrator_model_path}")
        
        return errors


# Default configuration
DEFAULT_CONFIG = LLMConfig()
