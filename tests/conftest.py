"""Pytest configuration and fixtures."""

import pytest

from kg_ae.config import settings


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-db",
        action="store_true",
        default=False,
        help="(legacy) Force-run graph-backed tests even if the graph is missing",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "db: mark test as requiring the built JSON graph")


def pytest_collection_modifyitems(config, items):
    """Skip graph-backed tests only when the JSON graph has not been built.

    The 'db' marker is legacy naming; tests now run against data/graph/*.json
    rather than SQL Server. They run automatically when the graph exists.
    """
    graph_built = (settings.graph_dir / "nodes.json").exists()
    if config.getoption("--run-db") or graph_built:
        return

    skip_db = pytest.mark.skip(reason="JSON graph not built (run `uv run kg-ae build-graph`)")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip_db)
