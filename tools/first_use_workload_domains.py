"""Closed vocabularies, bounds and the one refusal type of the first-use workload.

Every value here is a constant of the ``cloe-first-use-*-v1`` evidence formats
(ADR 0180, contract sections 6 and 9.2). The formats are checkout-derived
observations: they carry no graph, publication or resource authority and no
product module may import them.
"""

from __future__ import annotations

import re

MAX_COUNTER = 2**63 - 1
MAX_DEPTH = 6

SCHEMA_CENSUS = "cloe-first-use-census-v1"
SCHEMA_INTENT = "cloe-first-use-intent-v1"
SCHEMA_OBSERVATION = "cloe-first-use-observation-v1"
SCHEMA_INDEX = "cloe-first-use-bundle-v1"
SCHEMA_VERDICT = "cloe-first-use-verdict-v1"

MAX_OBSERVATION_BYTES = 8192
MAX_REPORT_MEMBER_BYTES = 16385
MAX_PLAN_MEMBER_BYTES = 4097
MAX_CONTROL_BYTES = 65536
MAX_CENSUS_BYTES = 786432
MAX_CENSUS_ENTRIES = 1024
MAX_OBSERVATIONS = 24
MAX_BUNDLE_MEMBERS = 128
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
MAX_LOCATION_REFS = 32
MAX_REF_BYTES = 96
MAX_REL_BYTES = 255
MAX_LEFTOVERS = 32

ALIASES: tuple[str, ...] = ("core", "companion", "feeds", "mailbox")
UNRESOLVED_ALIAS = "unresolved"
SCENARIOS: tuple[str, ...] = ("local", "server", "mixed")
BACKENDS: tuple[str, ...] = ("sqlite", "postgresql", "mixed")
FACT_BACKENDS: tuple[str, ...] = ("sqlite", "postgresql")

RESULTS: tuple[str, ...] = ("pass", "expected_refusal", "failure", "skipped", "unavailable")
EXPECTATIONS: tuple[str, ...] = ("pass", "expected_refusal")
REASONS: tuple[str, ...] = (
    "not_reached", "runtime_unavailable", "witness_failed", "call_failed", "cleanup_failed",
    "stale_input", "unexpected_refusal", "unexpected_return", "unbounded",
)
REFUSAL_CODES: tuple[str, ...] = (
    "sealing-budget-exceeded:planned_read_bytes",
    "resource_budget_exceeded",
    "local_value_error",
    "graph_privacy_not_authorized",
    "retention_not_authorized",
)

ACTIONS: tuple[str, ...] = (
    "census_verify", "sqlite_init", "migrate", "sealing_plan",
    "refresh_cold", "refresh_repeat", "refresh_generation", "refresh_recovery",
    "replay_refresh", "sqlite_initial", "postgres_initial",
    "planned_refusal", "missing_refusal", "privacy_refusal",
    "pack_current", "pack_stale", "pack_mixed", "pack_subset", "stale_investigation",
    "lexical_build", "lexical_query", "lexical_revoke",
    "snapshot_equivalence", "cleanup",
)
REFRESH_ACTIONS = frozenset({
    "refresh_cold", "refresh_repeat", "refresh_generation", "refresh_recovery",
    "replay_refresh", "sqlite_initial", "postgres_initial",
})
REFUSAL_ACTIONS = frozenset({"planned_refusal", "missing_refusal", "privacy_refusal"})
PACK_ACTIONS = frozenset({
    "pack_current", "pack_stale", "pack_mixed", "pack_subset", "stale_investigation",
})
LEXICAL_ACTIONS = frozenset({"lexical_build", "lexical_query", "lexical_revoke"})
INIT_ACTIONS = frozenset({"sqlite_init", "migrate"})

CATEGORIES: tuple[str, ...] = (
    "unreadable", "unsafe_input", "too_large", "not_canonical", "malformed",
    "invalid_domain", "stale_input", "intent_mismatch", "candidate_mismatch",
    "cross_attempt", "cross_backend", "out_of_order", "missing_step",
    "partial_bundle", "tampered_member", "unbounded", "witness_missing",
    "witness_mismatch", "report_mismatch", "pin_not_preserved", "unexpected_failure",
)
INCOMPLETE_CATEGORIES = frozenset({"missing_step", "partial_bundle", "witness_missing"})
OUTCOMES: tuple[str, ...] = ("accepted", "rejected", "incomplete")

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
PREFIXED_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
OBSERVATION_NAME = re.compile(r"observation-([0-9]{2})-([0-9])\.json\Z")
REPORT_NAME = re.compile(r"report-([0-9]{2})-([0-9])\.json\Z")
PLAN_NAME = re.compile(r"plan-([0-9]{2})-([0-9])\.json\Z")
CONTROL_NAMES: tuple[str, ...] = ("index.json", "verdict.json")
INTENT_NAME = "intent.json"
REPORTS_DIR = "reports"
PLANS_DIR = "plans"


class WorkloadError(ValueError):
    """A closed, path-free refusal category for workload evidence."""

    def __init__(self, category: str) -> None:
        if category not in CATEGORIES:
            category = "invalid_domain"
        self.category = category
        super().__init__(f"first-use-workload: {category}")


def observation_name(step: int, sub: int) -> str:
    return f"observation-{step:02d}-{sub}.json"


def report_name(step: int, sub: int) -> str:
    return f"{REPORTS_DIR}/report-{step:02d}-{sub}.json"


def plan_name(step: int, sub: int) -> str:
    return f"{PLANS_DIR}/plan-{step:02d}-{sub}.json"


def outcome_for(categories: set[str] | frozenset[str]) -> str:
    """Rejecting categories outrank incompleteness; no category means acceptance."""
    if categories - INCOMPLETE_CATEGORIES:
        return "rejected"
    if categories:
        return "incomplete"
    return "accepted"


__all__ = [
    "ACTIONS", "ALIASES", "BACKENDS", "CATEGORIES", "CONTROL_NAMES", "EXPECTATIONS",
    "FACT_BACKENDS", "HEX32", "HEX40", "HEX64", "INCOMPLETE_CATEGORIES", "INIT_ACTIONS",
    "INTENT_NAME", "LEXICAL_ACTIONS", "MAX_BUNDLE_BYTES", "MAX_BUNDLE_MEMBERS",
    "MAX_CENSUS_BYTES", "MAX_CENSUS_ENTRIES", "MAX_CONTROL_BYTES", "MAX_COUNTER", "MAX_DEPTH",
    "MAX_LEFTOVERS", "MAX_LOCATION_REFS", "MAX_OBSERVATIONS", "MAX_OBSERVATION_BYTES",
    "MAX_PLAN_MEMBER_BYTES", "MAX_REF_BYTES", "MAX_REL_BYTES", "MAX_REPORT_MEMBER_BYTES",
    "OBSERVATION_NAME", "OUTCOMES", "PACK_ACTIONS", "PLANS_DIR", "PLAN_NAME", "PREFIXED_SHA256",
    "REASONS", "REFRESH_ACTIONS", "REFUSAL_ACTIONS", "REFUSAL_CODES", "REPORTS_DIR",
    "REPORT_NAME", "RESULTS", "SCENARIOS", "SCHEMA_CENSUS", "SCHEMA_INDEX", "SCHEMA_INTENT",
    "SCHEMA_OBSERVATION", "SCHEMA_VERDICT", "UNRESOLVED_ALIAS", "WorkloadError",
    "observation_name", "outcome_for", "plan_name", "report_name",
]
