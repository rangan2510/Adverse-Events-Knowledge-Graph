"""Pytest configuration and fixtures."""

import pytest


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-db",
        action="store_true",
        default=False,
        help="Run tests that require database connection",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "db: mark test as requiring database connection")


def pytest_collection_modifyitems(config, items):
    """Skip db tests unless --run-db is provided."""
    if config.getoption("--run-db"):
        # --run-db given: do not skip db tests
        return

    skip_db = pytest.mark.skip(reason="Need --run-db option to run database tests")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip_db)
