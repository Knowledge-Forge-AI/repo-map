"""Support definitions and readiness contracts for the pgvector test profile."""

from __future__ import annotations

import os
import re
from typing import Any, Callable

CORE_PROFILE = "core"
PGVECTOR_PROFILE = "pgvector"
SUPPORTED_PROFILES = (CORE_PROFILE, PGVECTOR_PROFILE)

ENV_PG_TEST_PROFILE = "REPOMAP_TEST_PG_PROFILE"

PGVECTOR_VERSION = "0.8.7"
PGVECTOR_EXTENSION = "vector"
PGVECTOR_SCHEMA = "repomap_vector"
PGVECTOR_MARKER = "requires_pgvector"
PRESENCE_TEST_NAME = "test_selected_candidate_capability_boundary"

PGVECTOR_TEST_IMAGE = "repomap-test-postgres:16-pgvector087-v1"
PGVECTOR_UPSTREAM_COMMIT = "f37c13f68b57d2c3472b2214fbcff699d6d34876"
PGVECTOR_ARCHIVE_SHA256 = (
    "cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85"
)


def current_pg_test_profile() -> str:
    """Return the currently selected Postgres test profile from the environment."""
    profile = os.environ.get(ENV_PG_TEST_PROFILE, CORE_PROFILE).strip().lower()
    return profile if profile in SUPPORTED_PROFILES else CORE_PROFILE


def is_pgvector_profile_active() -> bool:
    """Return True if the pgvector test profile is explicitly active."""
    return current_pg_test_profile() == PGVECTOR_PROFILE


def resolve_pg_image(profile: str | None = None, *, default_image: str) -> str:
    """Resolve the Postgres container image based on active profile."""
    selected = (profile or current_pg_test_profile()).strip().lower()
    if selected == PGVECTOR_PROFILE:
        image_override = os.environ.get("REPOMAP_TEST_PG_IMAGE", "").strip()
        if re.fullmatch(r"sha256:[0-9a-f]{64}", image_override):
            return image_override
        raise RuntimeError("pgvector profile active but no engine image identity resolved")
    return default_image


def check_pgvector_extension_available(query_scalar_fn: Callable[[str], str]) -> bool:
    """Probe whether vector 0.8.7 is registered in pg_available_extension_versions."""
    sql = (
        "SELECT count(*) FROM pg_available_extension_versions "
        f"WHERE name = '{PGVECTOR_EXTENSION}' AND version = '{PGVECTOR_VERSION}';"
    )
    result = query_scalar_fn(sql)
    if re.fullmatch(r"[01]\r?\n?", result) is None:
        raise RuntimeError(
            "pgvector readiness probe-output error: expected exactly one scalar "
            "catalog count (0 or 1)"
        )
    return result.rstrip("\r\n") == "1"


def verify_pgvector_readiness(query_scalar_fn: Callable[[str], str]) -> None:
    """Verify that vector 0.8.7 is available; fail closed if absent."""
    if not check_pgvector_extension_available(query_scalar_fn):
        raise RuntimeError(
            f"pgvector profile readiness check failed: {PGVECTOR_EXTENSION} "
            f"version {PGVECTOR_VERSION} is not available in test container"
        )


def pgvector_probe_image_id(client: Any, container_id: str | None) -> str:
    """Read only the image identity through the harness's existing Docker owner."""
    if client is not None and container_id is not None:
        try:
            observed = client.containers.get(container_id).attrs.get("Image", "")
            if isinstance(observed, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", observed):
                return observed
        except Exception:
            # Diagnostic readback cannot replace the initiating probe failure.
            pass
    return "unavailable"


def is_presence_test_item(item) -> bool:
    """Determine whether a collected pytest item represents a pgvector presence test."""
    return item.get_closest_marker(PGVECTOR_MARKER) is not None


def pytest_configure(config) -> None:
    """Register pgvector marker declarations with pytest to satisfy strict markers."""
    config.addinivalue_line(
        "markers",
        f"{PGVECTOR_MARKER}: marks tests requiring the pgvector extension profile",
    )


def pytest_collection_modifyitems(session, config, items) -> None:
    """Visibly deselect presence tests when running ordinary core profile."""
    if is_pgvector_profile_active():
        return

    selected = []
    deselected = []
    for item in items:
        if is_presence_test_item(item):
            deselected.append(item)
        else:
            selected.append(item)

    if deselected:
        items[:] = selected
        config.hook.pytest_deselected(items=deselected)


__all__ = (
    "CORE_PROFILE",
    "ENV_PG_TEST_PROFILE",
    "PGVECTOR_ARCHIVE_SHA256",
    "PGVECTOR_EXTENSION",
    "PGVECTOR_MARKER",
    "PGVECTOR_PROFILE",
    "PGVECTOR_SCHEMA",
    "PGVECTOR_TEST_IMAGE",
    "PGVECTOR_UPSTREAM_COMMIT",
    "PGVECTOR_VERSION",
    "PRESENCE_TEST_NAME",
    "SUPPORTED_PROFILES",
    "check_pgvector_extension_available",
    "current_pg_test_profile",
    "is_pgvector_profile_active",
    "is_presence_test_item",
    "pgvector_probe_image_id",
    "pytest_collection_modifyitems",
    "pytest_configure",
    "resolve_pg_image",
    "verify_pgvector_readiness",
)
