"""
LLM clients for planner and narrator models.

Uses Instructor for structured output from planner,
standard OpenAI client for narrator free text.
"""

from __future__ import annotations

import instructor
from openai import OpenAI

from .config import LLMConfig
from .prompts import format_planner_messages, format_narrator_messages
from .schemas import ToolPlan


class PlannerClient:
    """
    Client for the planner LLM (Phi-4-mini).

    Uses Instructor to enforce ToolPlan JSON schema.
    Returns structured ToolPlan objects guaranteed to match schema.
    """

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self._raw_client = OpenAI(
            base_url=self.config.planner_url,
            api_key="not-needed",  # local llama-server doesn't check
        )
        # Wrap with instructor for structured output (JSON_SCHEMA for llama.cpp)
        self._client = instructor.from_openai(
            self._raw_client, 
            mode=instructor.Mode.JSON_SCHEMA,
        )

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
            model=self.config.planner_model,
            messages=messages,
            response_model=ToolPlan,
            temperature=self.config.planner_temperature,
            max_tokens=self.config.planner_max_tokens,
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
            "content": '{"calls": [{"tool": "resolve_drugs", "args": {"names": [...]}, "reason": "resolve entities"}], "stop_conditions": {}}'
        })
        messages.append({
            "role": "user",
            "content": f"Resolution results:\n{resolved_context}\n\nNow plan the remaining tool calls using the resolved keys."
        })

        plan = self._client.chat.completions.create(
            model=self.config.planner_model,
            messages=messages,
            response_model=ToolPlan,
            temperature=self.config.planner_temperature,
            max_tokens=self.config.planner_max_tokens,
            max_retries=2,
        )
        return plan


class NarratorClient:
    """
    Client for the narrator LLM (MediPhi).

    Returns free-form text summarizing evidence.
    Does NOT use structured output - just streaming text.
    """

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        self._client = OpenAI(
            base_url=self.config.narrator_url,
            api_key="not-needed",
        )

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

        response = self._client.chat.completions.create(
            model=self.config.narrator_model,
            messages=messages,
            temperature=self.config.narrator_temperature,
            max_tokens=self.config.narrator_max_tokens,
        )
        return response.choices[0].message.content or ""

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
            model=self.config.narrator_model,
            messages=messages,
            temperature=self.config.narrator_temperature,
            max_tokens=self.config.narrator_max_tokens,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
