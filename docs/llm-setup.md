# LLM Setup Guide

The agent reaches the LLM over **one OpenAI-compatible endpoint**. The same code
serves both the dev path (OpenRouter) and the airgapped deployment path (a local
server). Only two settings differ between them: `KG_AE_LLM_BASE_URL` and
`KG_AE_LLM_MODEL`. There is no separate "planner" and "narrator" model and no
database — see [docs/compliance.md](compliance.md).

## Configuration

All LLM settings are `KG_AE_*` environment variables (read from `.env`):

```bash
# Provider: "openrouter" (dev) or "local" (deployment)
KG_AE_LLM_PROVIDER=openrouter
KG_AE_LLM_BASE_URL=https://openrouter.ai/api/v1
KG_AE_LLM_MODEL=mistralai/mistral-small-3.2-24b-instruct
KG_AE_LLM_TEMPERATURE=0.1
KG_AE_LLM_MAX_TOKENS=4096

# Self-consistency ensemble (1 = single agent; >1 reconciles N answers)
KG_AE_AGENT_ENSEMBLE_SIZE=3
KG_AE_MAX_ITERATIONS=8
```

The OpenRouter API key is read from `OPENROUTER_API_KEY` (non-prefixed) via
`os.getenv`. Run `uv run kg-ae doctor` to print the active LLM + compliance
posture.

## Dev: OpenRouter

1. Get an API key at [openrouter.ai/keys](https://openrouter.ai/keys).
2. Set `OPENROUTER_API_KEY` in `.env`.
3. Keep the defaults above.

OpenRouter is a stand-in for the local model during development; it is never
used in the airgapped build.

## Deployment: local server (airgapped)

Serve an open-source model over an OpenAI-compatible API on localhost with
Ollama, LM Studio, or vLLM, then point the app at it:

```bash
KG_AE_LLM_PROVIDER=local
KG_AE_LLM_BASE_URL=http://localhost:11434/v1   # Ollama example
KG_AE_LLM_MODEL=mistral-small
KG_AE_AIRGAPPED=true
```

With `KG_AE_AIRGAPPED=true`, `build_chat_model()` refuses any non-localhost LLM
URL (raises `ComplianceError`) and the optional web-search tool is not
registered. **Only open-source models are allowed.**

## Model choice

Only open-weight models are permitted. The agent is a **tool-calling** ReAct
agent, so the model must reliably emit OpenAI-format tool calls. This is the
single most important selection criterion.

### Recommendation

**`mistralai/mistral-small-3.2-24b-instruct`** is the recommended default
(Apache-2.0, EU-friendly, 128K context). It is the version explicitly tuned for
improved function calling and structured output, and in our A/B testing it was
the only candidate that drove the graph tools reliably.

### A/B comparison (recorded 2026-06-20)

`scripts/compare_models.py` runs a fixed query set through several models
(single agent, no ensemble) and records tool usage + latency. Results:

| Model | Tool calling | Verdict |
|-------|--------------|---------|
| `mistral-small-3.2-24b-instruct` | Reliable | Recommended default. Real multi-tool reasoning, grounded answers. |
| `mistral-small-2603` ("Small 4") | Reliable | Excellent insight quality (richest mechanistic + pharmacogenomic detail in testing). Requires the OpenRouter account [privacy/data policy](https://openrouter.ai/settings/privacy) to allow its providers; returns 404 otherwise. |
| `ministral-8b-2512` | Broken | Emits Mistral-native `[TOOL_CALLS]...` as plain text; LangChain cannot parse it, so 0 tools execute. Too small for structured tool calling here. |
| `mistral-large-2512` | n/a | Blocked by the same OpenRouter data policy by default (404). Apache-2.0; viable once access is enabled. |

Both `mistral-small-3.2-24b-instruct` and `mistral-small-2603` are solid
choices. Small 4 gave the most detailed grounded answers in testing; 3.2 is the
conservative default that works without any OpenRouter privacy changes.

To re-run the comparison (override the list as needed):

```powershell
uv run python scripts/compare_models.py
uv run python scripts/compare_models.py --models mistralai/mistral-small-3.2-24b-instruct mistralai/mistral-large-2512
```

You can also override the model for a single query without editing `.env`:

```python
from kg_ae.llm.agent import run_agent
run_agent("Why might atorvastatin cause myopathy?", model="mistralai/mistral-large-2512")
```

For France specifically, Mistral Small is recommended; Gemma
(`google/gemma-3-27b-it`) is an acceptable alternative where tool calling is
reliable.

## How the agent uses the LLM

`run_agent(query, ensemble_size, max_iterations, model)` builds a LangGraph
`create_react_agent` over the deterministic graph tools (see
[tools-api.md](tools-api.md)). The LLM only ever narrates what the tools
returned. "Multiple agents" is a self-consistency ensemble: N independent agents
answer the same query and a final pass reconciles them
(`KG_AE_AGENT_ENSEMBLE_SIZE`).

## Health check

```powershell
uv run kg-ae doctor            # LLM + compliance posture
uv run kg-ae query "What does atorvastatin target?"
```
