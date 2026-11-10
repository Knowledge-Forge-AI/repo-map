"""Closed vocabularies, bounds and the one refusal type of the installed-experience proof.

Every value here is a constant of the ``cloe-installed-experience-*-v1`` derived
evidence formats (ADR 0181, contract section 10). The formats are checkout-only
diagnostic observations of an installed candidate: they carry no graph,
publication, packaging or resource authority and no product module imports them.
"""

from __future__ import annotations

import re

SCHEMA_INTENT = "cloe-installed-experience-intent-v1"
SCHEMA_OBSERVATION = "cloe-installed-experience-observation-v1"
SCHEMA_INDEX = "cloe-installed-experience-index-v1"
SCHEMA_VERDICT = "cloe-installed-experience-verdict-v1"
SCHEMA_PROJECTION = "cloe-installed-experience-projection-v1"

MAX_INTENT_BYTES = 16 * 1024
MAX_OBSERVATION_BYTES = 2 * 1024
MAX_INDEX_BYTES = 8 * 1024
MAX_VERDICT_BYTES = 2 * 1024
MAX_PROJECTION_BYTES = 1024
MAX_OWNER_OBSERVATIONS = 16
MAX_RECIPE_OBSERVATIONS = 48
MAX_BUNDLE_FILES = 19
MAX_BUNDLE_BYTES = 128 * 1024
MAX_ALL_BUNDLES_BYTES = 640 * 1024
MAX_FACTS = 12
MAX_TEXT = 128

# The nested layout below ``default_bundle_base``: ``installed-experience/<owner>/``.
BUNDLE_PARENT = "installed-experience"
OWNERS: tuple[str, ...] = ("environment", "local", "mcp", "migration", "server")
# Existing first-use storage tokens; the storage scenario is not an owner claim.
STORAGE_SCENARIO: dict[str, str] = {
    "environment": "local", "local": "local", "mcp": "local", "migration": "local",
    "server": "server",
}

ENV_CLASSES: tuple[str, ...] = (
    "pure-local", "incumbent-local", "provisioned-server", "shared-site", "none",
)
FAMILIES: tuple[str, ...] = ("arch7f_pip", "arch7f_probe", "none")
OUTCOMES: tuple[str, ...] = ("passed", "expected-refusal", "failed", "unknown", "not-reached")
EXPECTATIONS: tuple[str, ...] = ("pass", "refusal")
CLEANUP_STATES: tuple[str, ...] = ("removed", "retained-reported", "not-applicable")
FACT_SOURCES: tuple[str, ...] = (
    "child-stdout", "child-exit", "filesystem", "pip-check", "mcp-reply", "guard-log", "intent",
)
OBSERVED_SOURCES = frozenset(FACT_SOURCES) - {"intent"}
STDERR_CLASSES: tuple[str, ...] = (
    "empty", "legacy-module-notice", "legacy-command-notice", "other", "not-captured",
)
ORIGIN_CLASSES: tuple[str, ...] = (
    "env-purelib", "env-data", "env-bin", "base-stdlib", "base-dynload", "system-site",
    "checkout", "owned-cwd", "other",
)
PROJECTION_REFUSALS: tuple[str, ...] = (
    "projection-requirement-unsupported", "projection-source-missing",
    "projection-source-ambiguous", "projection-unknown-entry", "projection-path-escape",
    "projection-entry-unsafe", "projection-hash-mismatch", "projection-license-missing",
    "projection-drift", "projection-target-occupied", "projection-record-unbounded",
    "projection-cleanup-failed",
)
FAILURE_CODES: tuple[str, ...] = (
    "child-exit-nonzero", "child-signalled", "child-deadline", "fact-unobserved",
    "witness-failed", "call-failed", "prerequisite-failed", "inventory-mismatch",
    "environment-class-mismatch", "origin-checkout", "origin-closure-violated",
    "installed-server-harness-unavailable", "unbounded-output", "protocol-violation",
    "cleanup-failed", "interrupted", *PROJECTION_REFUSALS,
)
CATEGORIES: tuple[str, ...] = (
    "fact-mismatch", "witness-missing", "order-violation", "duplicate", "unexpected-outcome",
    "class-mismatch", "cleanup-missing", "bound-exceeded", "binding-mismatch", "malformed",
    "unsafe-member", "incomplete-step",
)
INCOMPLETE_CATEGORIES = frozenset({"incomplete-step"})
VERDICT_OUTCOMES: tuple[str, ...] = ("accepted", "rejected", "incomplete")

SCENARIO_ID = re.compile(r"[ALMRSX][0-9]{2}\Z")
ACTION = re.compile(r"[a-z][a-z0-9-]{1,47}\Z")
FACT_KEY = re.compile(r"[a-z][a-z0-9_]{1,47}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
OBSERVATION_NAME = re.compile(r"observation-([0-9]{2})-1\.json\Z")
INTENT_NAME = "intent.json"
INDEX_NAME = "index.json"
VERDICT_NAME = "verdict.json"


class InstalledError(ValueError):
    """A closed, path-free refusal category for installed-experience evidence."""

    def __init__(self, category: str) -> None:
        if category not in CATEGORIES and category not in ("unreadable", "too-large"):
            category = "malformed"
        self.category = category
        super().__init__(f"installed-experience: {category}")


def observation_name(seq: int) -> str:
    if not 1 <= seq <= MAX_OWNER_OBSERVATIONS:
        raise InstalledError("bound-exceeded")
    return f"observation-{seq:02d}-1.json"


def outcome_for(categories: set[str] | frozenset[str]) -> str:
    """Rejecting categories outrank incompleteness; no category means acceptance."""
    if categories - INCOMPLETE_CATEGORIES:
        return "rejected"
    if categories:
        return "incomplete"
    return "accepted"


__all__ = [
    "ACTION", "BUNDLE_PARENT", "CATEGORIES", "CLEANUP_STATES", "ENV_CLASSES", "EXPECTATIONS",
    "FACT_KEY", "FACT_SOURCES", "FAILURE_CODES", "FAMILIES", "HEX32", "HEX64",
    "INCOMPLETE_CATEGORIES", "INDEX_NAME", "INTENT_NAME", "InstalledError", "MAX_ALL_BUNDLES_BYTES",
    "MAX_BUNDLE_BYTES", "MAX_BUNDLE_FILES", "MAX_FACTS", "MAX_INDEX_BYTES", "MAX_INTENT_BYTES",
    "MAX_OBSERVATION_BYTES", "MAX_OWNER_OBSERVATIONS", "MAX_PROJECTION_BYTES",
    "MAX_RECIPE_OBSERVATIONS", "MAX_TEXT", "MAX_VERDICT_BYTES", "OBSERVATION_NAME",
    "OBSERVED_SOURCES", "ORIGIN_CLASSES", "OUTCOMES", "OWNERS", "PROJECTION_REFUSALS",
    "SCENARIO_ID", "SCHEMA_INDEX", "SCHEMA_INTENT", "SCHEMA_OBSERVATION", "SCHEMA_PROJECTION",
    "SCHEMA_VERDICT", "STDERR_CLASSES", "STORAGE_SCENARIO", "VERDICT_NAME", "VERDICT_OUTCOMES",
    "observation_name", "outcome_for",
]
