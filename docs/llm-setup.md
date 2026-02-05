# LLM Setup Guide

## Overview

The system supports two LLM providers:

| Provider | Planner | Narrator | Best For |
|----------|---------|----------|----------|
| **Groq Cloud** | llama-3.3-70b-versatile | Same model | Production, fast queries |
| **Local llama.cpp** | Phi-4-mini (3.8B) | Phi-4 (14B) | Offline, no API costs |

Configure in `.env`:
```bash
KG_AE_LLM_PROVIDER=groq   # or "local"
```

---

## Groq Cloud Setup

### 1. Get API Key
1. Sign up at [console.groq.com](https://console.groq.com)
2. Create API key in Settings > API Keys

### 2. Configure .env
```bash
KG_AE_LLM_PROVIDER=groq
GROQ_API_KEY=gsk_your_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_PLANNER_MAX_TOKENS=4096
GROQ_NARRATOR_MAX_TOKENS=8192
GROQ_PLANNER_TEMPERATURE=0.1
GROQ_NARRATOR_TEMPERATURE=0.3
```

### Available Groq Models
| Model | Tokens/Day (Free) | Notes |
|-------|-------------------|-------|
| llama-3.3-70b-versatile | 6,000 TPM | Recommended |
| openai/gpt-oss-20b | 200,000 TPD | Reasoning model, uses internal tokens |

### Rate Limits
Free tier has token limits. Upgrade to Dev Tier for higher limits: [console.groq.com/settings/billing](https://console.groq.com/settings/billing)

---

## Local llama.cpp Setup

Two-phase architecture using local models:
- **Planner** (Phi-4-mini): Generates tool call plans from user queries (3.8B params)
- **Narrator** (Phi-4): Synthesizes evidence into summaries (14B params, better context handling)

## Quick Start

```powershell
# First-time setup (downloads ~15GB, takes ~10min)
.\scripts\setup_llm.ps1

# Start servers (if not running)
.\scripts\start_llm_servers.ps1

# Stop servers
.\scripts\start_llm_servers.ps1 -Stop
```

## Models

| Role | Model | Params | Q4 Size | Port | Purpose |
|------|-------|--------|---------|------|---------|
| Planner | Phi-4-mini-instruct | 3.8B | ~2.3GB | 8081 | Tool planning, JSON output |
| Narrator | Phi-4 | 14B | ~8.5GB | 8082 | Evidence synthesis, narration |

Quantized to Q4_K_M for optimal quality/speed. Requires ~12GB VRAM to run both.

## Requirements

- **llama.cpp**: `winget install ggml.llamacpp`
- **GPU**: 8GB+ VRAM recommended (Vulkan backend for AMD)
- **Disk**: ~5GB for models, ~20GB during setup

## File Locations

```
D:\llm\models\              # Final quantized models (keep these)
  phi4mini.Q4_K_M.gguf      # ~2.3GB
  phi4.Q4_K_M.gguf          # ~8.5GB

external/                   # Deleted automatically after setup
                            # (prevents uv sync from building llama.cpp)
```

## Server Options

```powershell
# Custom GPU layers (default: 99 = all layers)
.\scripts\start_llm_servers.ps1 -GpuLayers 40

# Both models on GPU (needs ~12GB VRAM)
.\scripts\start_llm_servers.ps1 -BothGPU

# Both models on CPU
.\scripts\start_llm_servers.ps1 -BothCPU

# Swap: Narrator on GPU, Planner on CPU
.\scripts\start_llm_servers.ps1 -NarratorGPU

# Start minimized
.\scripts\start_llm_servers.ps1 -Minimized
```

## Health Check

```powershell
curl http://127.0.0.1:8081/health  # Planner
curl http://127.0.0.1:8082/health  # Narrator
```

## Python Usage

```python
from kg_ae.llm import LLMConfig, PlannerClient, NarratorClient

config = LLMConfig()
planner = PlannerClient(config)
narrator = NarratorClient(config)

# Get tool plan
plan = planner.plan("What are metformin's cardiac risks?")

# Generate summary (after executing tools)
summary = narrator.narrate(query, evidence_context)
```
