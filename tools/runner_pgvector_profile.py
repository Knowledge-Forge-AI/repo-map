"""Runner-side profile definition, facts verification, and environment setup for pgvector."""

from __future__ import annotations

import json
from pathlib import Path

CORE_PROFILE = "core"
PGVECTOR_PROFILE = "pgvector"
SUPPORTED_PROFILES = (CORE_PROFILE, PGVECTOR_PROFILE)
DEFAULT_PROFILE = CORE_PROFILE

ENV_PG_TEST_PROFILE = "REPOMAP_TEST_PG_PROFILE"
PGVECTOR_MARKER = "requires_pgvector"

EXPECTED_VERSION = "0.8.7"
EXPECTED_COMMIT = "f37c13f68b57d2c3472b2214fbcff699d6d34876"
EXPECTED_ARCHIVE_SHA256 = (
    "cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85"
)
EXPECTED_LICENSE = "PostgreSQL"
EXPECTED_ABI = "16"

DEFAULT_SOURCE_PATH = Path(__file__).resolve().parent / "pgvector_test_source.json"


def load_pgvector_source_facts(source_path: Path | None = None) -> dict[str, object]:
    """Load and return pgvector source facts, failing closed if unavailable."""
    path = source_path or DEFAULT_SOURCE_PATH
    if not path.is_file():
        raise RuntimeError(
            f"pgvector source fact verification failed closed: {path} is not a regular file"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RuntimeError(
            f"pgvector source fact verification failed closed: could not read {path}: {error}"
        ) from error
    if not isinstance(data, dict):
        raise RuntimeError(
            f"pgvector source fact verification failed closed: {path} root must be a JSON object"
        )
    return data


def verify_pgvector_source_facts(source_path: Path | None = None) -> dict[str, object]:
    """Verify immutable upstream pgvector facts; fail closed on any discrepancy."""
    facts = load_pgvector_source_facts(source_path)

    checks = [
        ("version", facts.get("version"), EXPECTED_VERSION),
        ("commit", facts.get("commit"), EXPECTED_COMMIT),
        ("archive_sha256", facts.get("archive_sha256"), EXPECTED_ARCHIVE_SHA256),
        ("license", facts.get("license"), EXPECTED_LICENSE),
        ("postgres_abi", facts.get("postgres_abi"), EXPECTED_ABI),
    ]

    for name, actual, expected in checks:
        if actual != expected:
            raise RuntimeError(
                f"pgvector source fact verification failed closed: mismatch on {name!r}: "
                f"expected {expected!r}, observed {actual!r}"
            )

    fixes = facts.get("fixes")
    if not isinstance(fixes, list) or not fixes:
        raise RuntimeError(
            "pgvector source fact verification failed closed: missing required fixes list"
        )

    return facts


def validate_profile_choice(profile: str) -> str:
    """Validate that the requested profile is supported; raise on invalid choice."""
    normalized = str(profile).strip().lower()
    if normalized not in SUPPORTED_PROFILES:
        valid = ", ".join(repr(p) for p in SUPPORTED_PROFILES)
        raise RuntimeError(
            f"unsupported pg test profile {profile!r}; choices are: {valid}"
        )
    return normalized


def build_profile_environment(profile: str) -> dict[str, str]:
    """Return environment variables required for running the selected Postgres profile."""
    validated = validate_profile_choice(profile)
    env = {
        ENV_PG_TEST_PROFILE: validated,
    }
    return env


__all__ = (
    "CORE_PROFILE",
    "DEFAULT_PROFILE",
    "DEFAULT_SOURCE_PATH",
    "ENV_PG_TEST_PROFILE",
    "EXPECTED_ABI",
    "EXPECTED_ARCHIVE_SHA256",
    "EXPECTED_COMMIT",
    "EXPECTED_LICENSE",
    "EXPECTED_VERSION",
    "PGVECTOR_MARKER",
    "PGVECTOR_PROFILE",
    "SUPPORTED_PROFILES",
    "build_profile_environment",
    "load_pgvector_source_facts",
    "validate_profile_choice",
    "verify_pgvector_source_facts",
)
