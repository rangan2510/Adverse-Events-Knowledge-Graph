# Compliance and Airgapped Deployment

This system is intended for use in an EU hospital, where it is most likely a
**high-risk AI system** under the EU AI Act and processes data adjacent to
**GDPR Article 9 special-category health data**. The architecture is built so
that the airgapped hospital build is the *same code* as the development build,
minus any online capability.

## What contains patient data, and what does not

- **The knowledge graph contains no patient data.** It is built entirely from
  public biomedical reference sources (DrugCentral, Reactome, Open Targets,
  SIDER, etc.) and ships as static JSON files in `data/graph/`.
- **The only patient-adjacent input is the query text** a clinician types. The
  rule that matters: query text and any clinical context must never reach an
  external service.

This split lets the offline ETL (which downloads public datasets) use the
internet on a connected staging machine, while runtime inference stays local.

## The two capabilities that touch the network

| Capability | Dev (online) | Hospital (airgapped) |
|------------|--------------|----------------------|
| LLM        | OpenRouter (cloud, stand-in for the local model) | Local server (Ollama / LM Studio / vLLM) on localhost |
| Web search | Tavily tool enabled | Tool not registered |
| Graph tools | JSON graph (local) | JSON graph (local, identical) |

Both online capabilities are gated by a single flag.

## The airgap switch

Set in `.env`:

```ini
KG_AE_AIRGAPPED=true
KG_AE_ALLOW_WEB_SEARCH=false
KG_AE_LLM_BASE_URL=http://localhost:11434/v1
KG_AE_LLM_MODEL=mistral-small
```

When `KG_AE_AIRGAPPED=true`:

- `Settings.web_search_enabled()` returns `false`, so the Tavily tool is not
  registered with the agent at all (`kg_ae.llm.lc_tools.build_tools`).
- `build_chat_model()` calls `enforce_compliance()`, which raises
  `ComplianceError` if `llm_base_url` is not a localhost URL or if web search is
  still enabled. The agent cannot start against a remote endpoint.

Check the active posture at any time:

```powershell
uv run kg-ae doctor
```

## Tavily is never load-bearing

The web-search tool (`tool_web_verify`) is **scoped to entity resolution and
verification only**: mapping a messy term to a canonical drug/gene/disease name
or sanity-checking an identifier. The system prompt forbids treating its output
as mechanistic evidence or as a citation. Only the graph tools provide citable
ground truth. Removing Tavily (airgapped mode) therefore degrades convenience,
not correctness: the agent falls back to graph-only resolution, exactly as in
deployment.

## Recommended open-source models (EU)

Open-weight, Apache-2.0, strong tool-calling, runs locally:

- **Mistral Small 3.x / 4** (recommended default) — French, clean license,
  fits a single 24 GB GPU, trained to say "I don't know" (good for RAG).
- **Gemma 3 / 4 (12B)** — runs in ~16 GB VRAM, native tool use.
- **Phi-4-mini** (MIT) — CPU / low-resource fallback.

For the clinician, **Mistral Small via Ollama or LM Studio** exposes an
OpenAI-compatible endpoint, so only `KG_AE_LLM_BASE_URL` and `KG_AE_LLM_MODEL`
change — no code path differs from development.

## Traceability and human oversight

Every association the agent reports comes from a graph edge that carries its
`dataset`, `source_record_id`, normalized `strength_score`, and raw `meta`
(see `kg_ae.tools.evidence.get_claim_evidence`). This provenance trail supports
the AI Act's accuracy, robustness, and human-oversight obligations: a clinician
can always trace a stated fact back to a curated source record.
