from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from repomap_test_support.postgres_harness import (
    DEFAULT_TEST_POSTGRES_PORT,
    DEFAULT_TEST_POSTGRES_RUNTIME,
    postgres_container_session,
)
TOOLS_ROOT = Path(__file__).resolve().parents[4] / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from test_sandbox import active_sandbox  # noqa: E402


_postgres_context = None


def _require_authenticated_sandbox() -> None:
    try:
        authenticated = active_sandbox()
    except RuntimeError as error:
        pytest.exit(
            "ERROR: RepoMap integration tests require the authenticated "
            f"container sandbox ({error})",
            returncode=2,
        )
    if not authenticated:
        pytest.exit(
            "ERROR: RepoMap integration tests require the authenticated "
            "container sandbox",
            returncode=2,
        )


# Import-time enforcement runs on every conftest import (before pytest_sessionstart
# or fixture setup) while allowing unit inspection under non-conftest module names.
if __name__.split(".")[-1] == "conftest":
    _require_authenticated_sandbox()


def pytest_sessionstart(session):
    global _postgres_context
    runtime = os.environ.get(
        "REPOMAP_TEST_PG_CONTAINER_RUNTIME",
        DEFAULT_TEST_POSTGRES_RUNTIME,
    )
    port = int(
        os.environ.get(
            "REPOMAP_TEST_PG_CONTAINER_PORT",
            str(DEFAULT_TEST_POSTGRES_PORT),
        )
    )
    _postgres_context = postgres_container_session(runtime=runtime, port=port)
    try:
        _postgres_context.__enter__()
    except RuntimeError as error:
        _postgres_context = None
        pytest.exit(f"ERROR: {error}", returncode=2)


def pytest_sessionfinish(session, exitstatus):
    global _postgres_context
    context = _postgres_context
    _postgres_context = None
    if context is not None:
        context.__exit__(None, None, None)
