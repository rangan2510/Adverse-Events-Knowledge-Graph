"""
LLM clients for planner and narrator models.

Uses Instructor for structured output from planner,
standard OpenAI client for narrator free text.
"""

from __future__ import annotations

import instructor
from openai import OpenAI

from .config import LLMConfig
from .prompts import format_narrator_messages, format_planner_messages
from .schemas import ToolPlan


class PlannerClient:
    """
    Client for the planner LLM.

    Supports local (Phi-4-mini via llama.cpp) or Groq Cloud (gpt-oss-20b).
    Uses Instructor to enforce ToolPlan JSON schema.
    Returns structured ToolPlan objects guaranteed to match schema.
    """

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self._raw_client = OpenAI(
            base_url=self.config.get_planner_url(),
            api_key=self.config.get_api_key(),
        )
        # Wrap with instructor for structured output
        # JSON mode for Groq, JSON_SCHEMA for local llama.cpp
        mode = (
            instructor.Mode.JSON
            if self.config.provider == "groq"
            else instructor.Mode.JSON_SCHEMA
        )
        self._client = instructor.from_openai(self._raw_client, mode=mode)

    def plan(self, query: str) -> ToolPlan:
        """
        Generate a tool execution plan for the given query.

        Args:
            query: User query about drug-AE relationships

        Returns:
            ToolPlan with list of tool calls to execute
        """
        messages = format_planner_messages(query)

        plan = self._client.chat.completions.create(
            model=self.config.get_planner_model(),
            messages=messages,
            response_model=ToolPlan,
            temperature=self.config.get_planner_temperature(),
            max_tokens=self.config.get_planner_max_tokens(),
            max_retries=2,
        )
        return plan

    def plan_with_context(self, query: str, resolved_context: str) -> ToolPlan:
        """
        Generate follow-up plan after entity resolution.

        Args:
            query: Original user query
            resolved_context: Formatted string of resolved entities with their keys

        Returns:
            ToolPlan with calls using resolved integer keys
        """
        messages = format_planner_messages(query)
        # Add resolved context as assistant turn + user follow-up
        messages.append({
            "role": "assistant",
            "content": (
                '{"calls": [{"tool": "resolve_drugs", "args": {"names": [...]}, '
                '"reason": "resolve entities"}], "stop_conditions": {}}'
            )
        })
        messages.append({
            "role": "user",
            "content": (
                f"Resolution results:\n{resolved_context}\n\n"
                "Now plan the remaining tool calls using the resolved keys."
            )
        })

        plan = self._client.chat.completions.create(
            model=self.config.get_planner_model(),
            messages=messages,
            response_model=ToolPlan,
            temperature=self.config.get_planner_temperature(),
            max_tokens=self.config.get_planner_max_tokens(),
            max_retries=2,
        )
        return plan

    def generate_structured(self, messages: list[dict], response_model):
        """
        Generate structured output from custom messages.

        Args:
            messages: Chat messages list (typically from format_planner_messages)
            response_model: Pydantic model class to enforce (typically ToolPlan)

        Returns:
            Instance of response_model
        """
        result = self._client.chat.completions.create(
            model=self.config.get_planner_model(),
            messages=messages,
            response_model=response_model,
            temperature=self.config.get_planner_temperature(),
            max_tokens=self.config.get_planner_max_tokens(),
            max_retries=2,
        )
        return result


class NarratorClient:
    """
    Client for the narrator LLM.

    Supports local (Phi-4 via llama.cpp) or Groq Cloud (gpt-oss-20b).
    Provides both free-form text and structured output (for sufficiency evaluation).
    """

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self._raw_client = OpenAI(
            base_url=self.config.get_narrator_url(),
            api_key=self.config.get_api_key(),
        )
        # Wrap with instructor for structured output when needed
        # JSON mode for Groq, JSON_SCHEMA for local llama.cpp
        mode = (
            instructor.Mode.JSON
            if self.config.provider == "groq"
            else instructor.Mode.JSON_SCHEMA
        )
        self._instructor_client = instructor.from_openai(self._raw_client, mode=mode)
        # Keep raw client for text generation
        self._client = self._raw_client

    def generate_text(self, messages: list[dict]) -> str:
        """
        Generate free-form text response.

        Args:
            messages: Chat messages list

        Returns:
            Generated text
        """
        response = self._client.chat.completions.create(
            model=self.config.get_narrator_model(),
            messages=messages,
            temperature=self.config.get_narrator_temperature(),
            max_tokens=self.config.get_narrator_max_tokens(),
        )
        return response.choices[0].message.content or ""

    def generate_structured(self, messages: list[dict], response_model):
        """
        Generate structured output matching Pydantic model.

        Args:
            messages: Chat messages list
            response_model: Pydantic model class to enforce

        Returns:
            Instance of response_model
        """
        result = self._instructor_client.chat.completions.create(
            model=self.config.get_narrator_model(),
            messages=messages,
            response_model=response_model,
            temperature=self.config.get_narrator_temperature(),
            max_tokens=self.config.get_narrator_max_tokens(),
            max_retries=2,
        )
        return result

    def narrate(self, query: str, evidence_context: str) -> str:
        """
        Generate a narrative summary from evidence.

        Args:
            query: Original user query
            evidence_context: Formatted evidence from EvidencePack.to_narrator_context()

        Returns:
            Free-form text summary addressing the query
        """
        messages = format_narrator_messages(query, evidence_context)
        return self.generate_text(messages)

    def narrate_stream(self, query: str, evidence_context: str):
        """
        Generate narrative with streaming output.

        Args:
            query: Original user query
            evidence_context: Formatted evidence

        Yields:
            Text chunks as they are generated
        """
        messages = format_narrator_messages(query, evidence_context)

        stream = self._client.chat.completions.create(
            model=self.config.get_narrator_model(),
            messages=messages,
            temperature=self.config.get_narrator_temperature(),
            max_tokens=self.config.get_narrator_max_tokens(),
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
