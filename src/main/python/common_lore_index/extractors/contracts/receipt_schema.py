"""Versioned extractor run receipt: separate declarations and observations.

A receipt is audit evidence. It never signs itself, never carries its own
digest, and no field in it can represent parent verification success: the
closed verification vocabulary is ``unverified`` or ``refused`` only, because
verification is live parent state that serialized data cannot carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common_lore_index.extractors.contracts.vocabulary import (
    ADMISSION_FACTS,
    CAPABILITY_VOCABULARY_VERSION,
    DIALECT_PATTERN,
    INSTALLED_FACTS,
    PIPELINE_STAGES,
    PROVENANCE_VALUES,
    ContractError,
    EffectVector,
    require_capabilities,
    require_int,
    require_member,
    require_pattern,
    require_sequence,
    require_sha256,
    require_sorted_members,
    require_token,
)

RECEIPT_SCHEMA = "cloe-extractor-run-receipt-v1"
RECEIPT_STATES = frozenset({"declared", "incomplete", "complete", "refused", "unavailable"})
TERMINAL_STATES = frozenset({"complete", "refused", "unavailable"})
STATE_TRANSITIONS = {
    "declared": frozenset({"incomplete", "complete", "refused", "unavailable"}),
    "incomplete": frozenset({"incomplete", "complete"}),
}
REFUSAL_CODES = frozenset(
    {
        "dependency_unavailable",
        "dialect_unsupported",
        "inadmissible_effects",
        "resource_bound_exceeded",
        "witness_unavailable",
        "policy_refused",
    }
)
ATTEMPT_OUTCOMES = frozenset(
    {
        "succeeded",
        "dependency_unavailable",
        "dialect_unsupported",
        "resource_bound_exceeded",
        "inadmissible",
        "parse_rejected",
        "crashed",
    }
)
COMPLETENESS_VALUES = frozenset({"complete", "partial", "truncated", "none"})
RESOURCE_EVENTS = frozenset(
    {"input_bound", "output_bound", "time_bound", "memory_bound", "process_bound", "diagnostic_bound"}
)
CLEANUP_FACTS = frozenset({"proven", "incomplete", "not_applicable", "unknown"})
VERIFICATION_FACTS = frozenset({"unverified", "refused"})
MAX_ATTEMPTS = 64
EXIT_STATUS_RANGE = (-255, 255)

RECEIPT_FIELDS = frozenset(
    {"schema", "capability_vocabulary", "state", "producer", "consumer_boundary",
     "run_id", "source_sha256", "declared", "observed", "refusal"}
)
DECLARED_FIELDS = frozenset(
    {"stage", "language_dialect", "runtime_identity", "capabilities", "effects",
     "provenance", "invocation_mode", "dependency_sha256", "profile_sha256"}
)
OBSERVED_FIELDS = frozenset(
    {"installed", "admitted", "artifact_sha256", "invocation_mode", "attempts",
     "resource_events", "exit_status", "cleanup", "verification"}
)
ATTEMPT_FIELDS = frozenset({"input_sha256", "outcome", "exercised", "achieved", "completeness"})


def _exact_object(payload: object, fields: frozenset[str], code: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or type(payload) is not dict or set(payload) != fields:
        raise ContractError(code)
    return payload


def _optional_sha256(value: object, *, code: str) -> str | None:
    return None if value is None else require_sha256(value, code=code)


def _optional_token(value: object, *, code: str) -> str | None:
    return None if value is None else require_token(value, code=code)


@dataclass(frozen=True)
class Declaration:
    """Producer expectations; never promoted to an observed fact."""

    stage: str
    language_dialect: str
    runtime_identity: str | None
    capabilities: tuple[str, ...]
    effects: EffectVector
    provenance: str
    invocation_mode: str
    dependency_sha256: str | None
    profile_sha256: str

    def __post_init__(self) -> None:
        require_member(self.stage, PIPELINE_STAGES, code="invalid_declared")
        require_pattern(self.language_dialect, DIALECT_PATTERN, code="invalid_declared")
        _optional_token(self.runtime_identity, code="invalid_declared")
        object.__setattr__(
            self, "capabilities", require_capabilities(self.capabilities, code="invalid_capability")
        )
        if type(self.effects) is not EffectVector:
            raise ContractError("invalid_effect")
        require_member(self.provenance, PROVENANCE_VALUES, code="invalid_declared")
        require_token(self.invocation_mode, code="invalid_declared")
        _optional_sha256(self.dependency_sha256, code="invalid_digest")
        require_sha256(self.profile_sha256, code="invalid_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage, "language_dialect": self.language_dialect,
            "runtime_identity": self.runtime_identity, "capabilities": list(self.capabilities),
            "effects": self.effects.to_dict(), "provenance": self.provenance,
            "invocation_mode": self.invocation_mode, "dependency_sha256": self.dependency_sha256,
            "profile_sha256": self.profile_sha256,
        }

    @classmethod
    def from_mapping(cls, payload: object) -> Declaration:
        data = _exact_object(payload, DECLARED_FIELDS, "invalid_declared")
        return cls(**{**data, "effects": EffectVector.from_mapping(data["effects"])})


@dataclass(frozen=True)
class Attempt:
    """One terminal outcome for one selected input (ADR 0050 D12)."""

    input_sha256: str
    outcome: str
    exercised: tuple[str, ...]
    achieved: tuple[str, ...]
    completeness: str

    def __post_init__(self) -> None:
        require_sha256(self.input_sha256, code="invalid_digest")
        require_member(self.outcome, ATTEMPT_OUTCOMES, code="invalid_attempt")
        object.__setattr__(self, "exercised", require_capabilities(self.exercised, code="invalid_capability"))
        object.__setattr__(self, "achieved", require_capabilities(self.achieved, code="invalid_capability"))
        require_member(self.completeness, COMPLETENESS_VALUES, code="invalid_attempt")
        if not set(self.achieved) <= set(self.exercised):
            raise ContractError("achieved_without_exercise")
        if self.achieved and self.outcome != "succeeded":
            raise ContractError("achieved_without_success")
        if "syntax.tree" in self.achieved and self.completeness != "complete":
            raise ContractError("incomplete_tree_claim")
        if "syntax.error_tolerant" in self.achieved and self.completeness == "none":
            raise ContractError("undeclared_completeness")

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_sha256": self.input_sha256, "outcome": self.outcome,
            "exercised": list(self.exercised), "achieved": list(self.achieved),
            "completeness": self.completeness,
        }

    @classmethod
    def from_mapping(cls, payload: object) -> Attempt:
        return cls(**_exact_object(payload, ATTEMPT_FIELDS, "invalid_attempt"))


@dataclass(frozen=True)
class ObservedFacts:
    """Facts a boundary witnessed; distinct from every declared field."""

    installed: str
    admitted: str
    artifact_sha256: str | None
    invocation_mode: str | None
    attempts: tuple[Attempt, ...]
    resource_events: tuple[str, ...]
    exit_status: int | None
    cleanup: str
    verification: str

    def __post_init__(self) -> None:
        require_member(self.installed, INSTALLED_FACTS, code="invalid_observed")
        require_member(self.admitted, ADMISSION_FACTS, code="invalid_observed")
        _optional_sha256(self.artifact_sha256, code="invalid_digest")
        _optional_token(self.invocation_mode, code="invalid_observed")
        attempts = require_sequence(self.attempts, code="invalid_attempt", maximum=MAX_ATTEMPTS)
        if any(type(item) is not Attempt for item in attempts):
            raise ContractError("invalid_attempt")
        object.__setattr__(self, "attempts", attempts)
        inputs = [item.input_sha256 for item in self.attempts]
        if len(inputs) != len(set(inputs)):
            raise ContractError("duplicate_attempt")
        object.__setattr__(
            self,
            "resource_events",
            require_sorted_members(self.resource_events, RESOURCE_EVENTS, code="invalid_observed"),
        )
        if self.exit_status is not None:
            require_int(self.exit_status, code="invalid_observed",
                        minimum=EXIT_STATUS_RANGE[0], maximum=EXIT_STATUS_RANGE[1])
        require_member(self.cleanup, CLEANUP_FACTS, code="invalid_observed")
        require_member(self.verification, VERIFICATION_FACTS, code="invalid_observed")
        if self.attempts and self.admitted != "admitted":
            raise ContractError("attempt_without_admission")
        if self.admitted == "admitted" and self.installed != "installed":
            raise ContractError("admission_without_installation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "installed": self.installed, "admitted": self.admitted,
            "artifact_sha256": self.artifact_sha256, "invocation_mode": self.invocation_mode,
            "attempts": [item.to_dict() for item in self.attempts],
            "resource_events": list(self.resource_events), "exit_status": self.exit_status,
            "cleanup": self.cleanup, "verification": self.verification,
        }

    @classmethod
    def from_mapping(cls, payload: object) -> ObservedFacts:
        data = _exact_object(payload, OBSERVED_FIELDS, "invalid_observed")
        attempts = require_sequence(data["attempts"], code="invalid_attempt", maximum=MAX_ATTEMPTS)
        return cls(**{**data, "attempts": tuple(Attempt.from_mapping(item) for item in attempts)})


@dataclass(frozen=True)
class Receipt:
    """A run-scoped receipt naming its producer and its consumer boundary."""

    state: str
    producer: str
    consumer_boundary: str
    run_id: str
    source_sha256: str
    declared: Declaration
    observed: ObservedFacts | None
    refusal: str | None

    def __post_init__(self) -> None:
        require_member(self.state, RECEIPT_STATES, code="invalid_state")
        require_token(self.producer, code="invalid_identity")
        require_token(self.consumer_boundary, code="invalid_identity")
        require_token(self.run_id, code="invalid_identity")
        require_sha256(self.source_sha256, code="invalid_digest")
        if type(self.declared) is not Declaration:
            raise ContractError("invalid_declared")
        if self.observed is not None and type(self.observed) is not ObservedFacts:
            raise ContractError("invalid_observed")
        if self.refusal is not None:
            require_member(self.refusal, REFUSAL_CODES, code="invalid_refusal")
        _check_state(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RECEIPT_SCHEMA, "capability_vocabulary": CAPABILITY_VOCABULARY_VERSION,
            "state": self.state, "producer": self.producer,
            "consumer_boundary": self.consumer_boundary, "run_id": self.run_id,
            "source_sha256": self.source_sha256, "declared": self.declared.to_dict(),
            "observed": None if self.observed is None else self.observed.to_dict(),
            "refusal": self.refusal,
        }

    @classmethod
    def from_mapping(cls, payload: object) -> Receipt:
        data = _exact_object(payload, RECEIPT_FIELDS, "unknown_or_missing_field")
        if data["schema"] != RECEIPT_SCHEMA or type(data["schema"]) is not str:
            raise ContractError("unsupported_schema")
        if data["capability_vocabulary"] != CAPABILITY_VOCABULARY_VERSION:
            raise ContractError("unsupported_vocabulary")
        observed = data["observed"]
        fields = {key: value for key, value in data.items()
                  if key not in ("schema", "capability_vocabulary")}
        return cls(**{
            **fields,
            "declared": Declaration.from_mapping(data["declared"]),
            "observed": None if observed is None else ObservedFacts.from_mapping(observed),
        })


def _check_state(receipt: Receipt) -> None:
    """Keep refused, unavailable, incomplete and complete states distinct."""

    state, observed = receipt.state, receipt.observed
    needs_refusal = state in ("refused", "unavailable")
    if (receipt.refusal is not None) != needs_refusal:
        raise ContractError("invalid_state")
    if state == "declared":
        if observed is not None:
            raise ContractError("invalid_state")
        return
    if observed is None:
        raise ContractError("invalid_state")
    declared = set(receipt.declared.capabilities)
    for attempt in observed.attempts:
        if not set(attempt.exercised) <= declared:
            raise ContractError("undeclared_capability_exercised")
    if state == "unavailable":
        if observed.installed != "unavailable" or receipt.refusal != "dependency_unavailable":
            raise ContractError("invalid_state")
    if state in ("refused", "unavailable") and (observed.admitted == "admitted" or observed.attempts):
        raise ContractError("invalid_state")
    if state in ("incomplete", "complete") and observed.admitted != "admitted":
        raise ContractError("invalid_state")
    if state == "complete" and (
        observed.cleanup not in ("proven", "not_applicable") or observed.exit_status is None
    ):
        raise ContractError("incomplete_terminal_facts")


def check_transition(previous: Receipt, following: Receipt) -> None:
    """Refuse invalid lifecycle transitions and any rewrite of earlier facts."""

    allowed = STATE_TRANSITIONS.get(previous.state, frozenset())
    if following.state not in allowed:
        raise ContractError("invalid_transition")
    identity = ("producer", "consumer_boundary", "run_id", "source_sha256", "declared")
    if any(getattr(previous, name) != getattr(following, name) for name in identity):
        raise ContractError("declaration_rewritten")
    if previous.observed is not None:
        if following.observed is None:
            raise ContractError("observation_rewritten")
        _check_observed_monotonic(previous.observed, following.observed)


def _set_once(earlier: object, later: object, unset: object = None) -> bool:
    return earlier == unset or earlier == later


def _check_observed_monotonic(earlier: ObservedFacts, later: ObservedFacts) -> None:
    """Observed facts only accumulate: nothing recorded may change or disappear.

    Installation and admission are fixed; artifact digest, invocation mode,
    exit status and a known cleanup fact are set once; resource-bound events
    and attempts only grow; a ``refused`` verification fact is sticky.
    """

    if (earlier.installed, earlier.admitted) != (later.installed, later.admitted):
        raise ContractError("observation_rewritten")
    if not (
        _set_once(earlier.artifact_sha256, later.artifact_sha256)
        and _set_once(earlier.invocation_mode, later.invocation_mode)
        and _set_once(earlier.exit_status, later.exit_status)
        and _set_once(earlier.cleanup, later.cleanup, unset="unknown")
        and _set_once(earlier.verification, later.verification, unset="unverified")
    ):
        raise ContractError("observation_rewritten")
    if not set(earlier.resource_events) <= set(later.resource_events):
        raise ContractError("observation_rewritten")
    if later.attempts[: len(earlier.attempts)] != earlier.attempts:
        raise ContractError("observation_rewritten")
