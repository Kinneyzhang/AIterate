"""pytest configuration for AIIterate tests."""
import pytest

# Archive contains broken tests for deleted modules — never collect them
collect_ignore = ["archive"]


def pytest_addoption(parser):
    parser.addoption(
        "--live", action="store_true", default=False,
        help="run live integration tests (requires API key and running server)"
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: marks tests that call real AI APIs (skip by default)"
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live"):
        skip_live = pytest.mark.skip(reason="use --live to run live AI tests")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)
