# LLM Setup Guide

## Overview

Two-phase LLM architecture using llama.cpp:
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
# Custom GPU layers (default: 35)
.\scripts\start_llm_servers.ps1 -GpuLayers 40

# Run benchmark first
.\scripts\start_llm_servers.ps1 -BenchmarkFirst

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
plan = planner.get_plan("What are metformin's cardiac risks?")

# Generate summary (after executing tools)
summary = narrator.summarize(evidence_pack)
```
