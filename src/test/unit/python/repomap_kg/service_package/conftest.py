"""Controlled executable authority for service-package semantic unit tests.

These tests exercise rendering, adapter semantics, lifecycle ordering and
rollback behaviour. None of them is a host installation-discovery test, so
they state their own interpreter and PostgreSQL client authority instead of
inheriting whatever packaging the runner happens to provide.
"""

from __future__ import annotations

import pytest

from repomap_test_support.executable_authority import controlled_service_authority


@pytest.fixture
def service_authority(tmp_path):
    with controlled_service_authority(tmp_path / "executable-authority") as authority:
        yield authority
