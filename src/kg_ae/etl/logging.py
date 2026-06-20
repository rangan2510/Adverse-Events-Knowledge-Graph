"""
Structured logging for the ETL pipeline.

Replaces the old Rich live dashboard with single-line structlog events. Each ETL
step emits one line like::

    [ok]    sider          download   done       1.4s
    [>]     ctd            download   running
    [!]     hpo            parse      error      <reason>

Call :func:`configure_logging` once at process start (the CLI does this), then
get a logger with :func:`get_logger`.
"""

from __future__ import annotations

import logging

import structlog

# Plain-text status markers (no emojis, per project convention).
STATUS_MARKER: dict[str, str] = {
    "pending": "[ ]",
    "running": "[>]",
    "done": "[ok]",
    "skipped": "[-]",
    "error": "[!]",
}


def _render_step(_logger, _name, event_dict: dict) -> str:
    """Render an etl.step event as a compact aligned line; pass others through."""
    if event_dict.get("event") != "etl.step":
        # Default rendering for non-step events.
        parts = [str(event_dict.pop("event", ""))]
        parts += [f"{k}={v}" for k, v in event_dict.items() if k not in ("level",)]
        return " ".join(p for p in parts if p)

    marker = STATUS_MARKER.get(event_dict.get("status", ""), "[?]")
    dataset = event_dict.get("dataset", "")
    phase = event_dict.get("phase", "")
    status = event_dict.get("status", "")
    line = f"{marker:6} {dataset:14} {phase:10} {status}"
    if (duration := event_dict.get("duration")) is not None:
        line += f"   {duration:.1f}s"
    if (detail := event_dict.get("detail")) is not None:
        line += f"   {detail}"
    return line


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for compact, single-line ETL output."""
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            _render_step,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "kg_ae.etl"):
    """Return a structlog logger."""
    return structlog.get_logger(name)
