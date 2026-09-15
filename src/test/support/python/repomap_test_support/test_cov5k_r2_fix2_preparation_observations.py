"""Attempt evidence layer facts, raw boundaries, and observation models."""

from __future__ import annotations

from dataclasses import dataclass

from repomap_test_support.test_cov5k_r2_groupa_contract import (
    canonical_attempt_category,
)


@dataclass(frozen=True, slots=True)
class ScenarioIntentFact:
    intent: str


@dataclass(frozen=True, slots=True)
class ChildLocalExceptionFact:
    status: str
    category: str | None = None
    boundary: str | None = None

    @classmethod
    def not_observable(cls) -> "ChildLocalExceptionFact":
        return cls("not_observable_at_parent_attempt_boundary")

    @classmethod
    def captured(cls, category: str, boundary: str) -> "ChildLocalExceptionFact":
        return cls("captured", category, boundary)


@dataclass(frozen=True, slots=True)
class WireFailureNoticeFact:
    status: str
    category: str | None = None
    boundary: str | None = None
    byte_length: int | None = None
    sha256: str | None = None

    @classmethod
    def not_observable(cls) -> "WireFailureNoticeFact":
        return cls("not_observable_at_parent_attempt_boundary")

    @classmethod
    def sender_closed(cls) -> "WireFailureNoticeFact":
        return cls("observed_sender_closed_without_notice")

    @classmethod
    def captured(
        cls, *, category: str, boundary: str, byte_length: int, sha256: str
    ) -> "WireFailureNoticeFact":
        return cls("captured", category, boundary, byte_length, sha256)


@dataclass(frozen=True, slots=True)
class ParentObservedAttemptFact:
    attempt_id: str
    outcome: str
    category: str
    boundary: str


@dataclass(frozen=True, slots=True)
class PublicProjectionFact:
    outcome: str
    category: str
    boundary: str


@dataclass(frozen=True, slots=True)
class FrozenExpectedFact:
    outcome: str
    category: str
    boundary: str


@dataclass(frozen=True, slots=True)
class AttemptEvidenceLayers:
    intent: ScenarioIntentFact
    child_local: ChildLocalExceptionFact
    wire: WireFailureNoticeFact
    parent: ParentObservedAttemptFact | None
    public_projection: PublicProjectionFact


def validate_attempt_evidence_layers(
    layers: AttemptEvidenceLayers, *, expected: FrozenExpectedFact | None = None
) -> ParentObservedAttemptFact:
    """Validate layers without letting intent, projection, or expectation fill raw facts."""

    parent = layers.parent
    if parent is None:
        raise ValueError("parent observed attempt fact is required")
    if not parent.attempt_id or parent.outcome not in {"success", "failure"}:
        raise ValueError("parent observed attempt fact is invalid")
    if parent.outcome == "success" and (parent.category, parent.boundary) != (
        "none",
        "none",
    ):
        raise ValueError("successful parent attempt carries failure facts")
    if parent.outcome == "failure" and parent.category == "none":
        raise ValueError("failed parent attempt lacks a category")
    if layers.wire.status == "captured" and (
        layers.wire.category,
        layers.wire.boundary,
    ) != (parent.category, parent.boundary):
        raise ValueError("wire and parent facts disagree")
    if layers.child_local.status == "captured" and layers.wire.status == "captured" and (
        layers.child_local.category,
        layers.child_local.boundary,
    ) != (layers.wire.category, layers.wire.boundary):
        raise ValueError("child and wire facts disagree")
    if (
        layers.public_projection.outcome,
        layers.public_projection.category,
        layers.public_projection.boundary,
    ) != (parent.outcome, parent.category, parent.boundary):
        raise ValueError("public projection and parent facts disagree")
    if expected is not None and (
        expected.outcome,
        expected.category,
        expected.boundary,
    ) != (parent.outcome, parent.category, parent.boundary):
        raise ValueError("frozen expected fact differs from parent observation")
    return parent


@dataclass(frozen=True, slots=True)
class AttemptObservation:
    """Public-safe raw and interpreted facts from one real worker attempt."""

    layers: AttemptEvidenceLayers
    interpreted_evidence_origin: str
    canonical_outcome: str
    canonical_category: str
    scenario_contract_category: str
    activation_observed: bool = False

    @property
    def parent(self) -> ParentObservedAttemptFact:
        return validate_attempt_evidence_layers(self.layers)

    @property
    def raw_outcome(self) -> str:
        return self.parent.outcome

    @property
    def raw_category(self) -> str:
        return self.parent.category

    @property
    def raw_boundary(self) -> str:
        return self.parent.boundary

    @property
    def scenario_intent(self) -> str:
        return self.layers.intent.intent


_RAW_CATEGORIES = frozenset({
    "none",
    "resource_unavailable",
    "preparation_timeout",
    "worker_failed",
    "cleanup_limitation",
})
_RAW_BOUNDARIES = frozenset({
    "none",
    "container_rss_read",
    "worker",
    "process_settlement",
})


def _public_raw(value: object, allowed: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unrecognized"


def _observation(
    *,
    attempt_id: str,
    outcome: str,
    category: object,
    boundary: object,
    intent: str,
    activation_observed: bool = False,
) -> AttemptObservation:
    raw_category = _public_raw(category, _RAW_CATEGORIES)
    raw_boundary = _public_raw(boundary, _RAW_BOUNDARIES)
    raw = (outcome, raw_category, raw_boundary)
    canonical = (
        "cleanup"
        if raw == ("failure", "cleanup_limitation", "process_settlement")
        else canonical_attempt_category(*raw)
    )
    expected = "success" if intent == "success" else intent
    contract_category = "matched" if canonical == expected else (
        "scenario_contract_mismatch"
        if outcome == "success"
        else "unexpected_raw_category"
    )
    origin = (
        "worker_result"
        if outcome == "success"
        else "parent_attempt_settlement"
        if canonical == "cleanup"
        else "parent_attempt_deadline"
        if (raw_category, raw_boundary) == ("preparation_timeout", "worker")
        else "worker_failure_notice"
        if canonical != "unexpected_raw_category"
        else "unrecognized"
    )
    layers = AttemptEvidenceLayers(
        intent=ScenarioIntentFact(intent),
        child_local=ChildLocalExceptionFact.not_observable(),
        wire=WireFailureNoticeFact.not_observable(),
        parent=ParentObservedAttemptFact(
            attempt_id, outcome, raw_category, raw_boundary
        ),
        public_projection=PublicProjectionFact(
            outcome, raw_category, raw_boundary
        ),
    )
    validate_attempt_evidence_layers(layers)
    return AttemptObservation(
        layers=layers,
        interpreted_evidence_origin=origin,
        canonical_outcome="success" if canonical == "success" else "failure",
        canonical_category=canonical,
        scenario_contract_category=contract_category,
        activation_observed=activation_observed,
    )
