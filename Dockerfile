# Drug-AE Knowledge Graph - application image (Option A: OpenRouter default).
#
# The knowledge graph contains only public reference data (no patient data),
# so it is baked into the image. To keep the build context small (~8 MB), we
# copy only the normalized silver Parquet and build the ~317 MB JSON graph
# INSIDE the image with `kg-ae build-graph`.
#
# The LLM is reached over one OpenAI-compatible endpoint. By default this is
# OpenRouter (dev/demo). For an airgapped deployment, point KG_AE_LLM_BASE_URL
# at a local server and set KG_AE_AIRGAPPED=true (built later).

FROM python:3.14-slim AS base

# uv: fast, reproducible installs from uv.lock
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# aria2 provides fast, multi-connection, resumable downloads (used by the ETL
# downloaders when present; falls back to httpx otherwise).
RUN apt-get update \
    && apt-get install -y --no-install-recommends aria2 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 1. Install dependencies first (cached layer keyed on lockfile + metadata).
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 2. Copy the application source and the silver data, then install the project.
COPY src/ ./src/
COPY data/silver/ ./data/silver/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# 3. Build the JSON knowledge graph inside the image (-> /app/data/graph/*.json).
RUN uv run kg-ae build-graph

# Run as a non-root user.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENV PATH="/app/.venv/bin:${PATH}"

# Default: drop into the interactive query prompt and stream answers to console.
# Override the command to run a one-shot query, e.g.:
#   docker run --rm -it --env-file .env kg-ae query "What does atorvastatin target?"
ENTRYPOINT ["kg-ae"]
CMD ["query", "--interactive"]
