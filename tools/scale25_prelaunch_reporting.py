"""Closed public-safe reporting for validated protected prelaunch results."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from scale20_prelaunch_handoff import ProtectedPrelaunchResult


PUBLIC_PRELAUNCH_SCHEMA_VERSION = 1
MAX_PUBLIC_PRELAUNCH_BYTES = 4096

_COMPLETE_PHASES = (
    "worker_result",
    "process_rss_attached",
    "resource_limits_validated",
    "ordered_family_handoff_validated",
    "expected_authority_validated",
)
_OUTCOME_CATEGORIES = {
    "accepted": "prelaunch_complete",
    "bounded_stop": "resource_limit_reached",
    "worker_failure": "worker_failed",
    "result_validation_failure": "result_invalid",
    "launch_refusal": "launch_refused",
}
_RESOURCE_STATUSES = frozenset(
    {"accepted", "bounded_stop", "unavailable", "not_evaluated"}
)
_CLEANLINESS_STATUSES = frozenset({"clean", "unproved"})
_EXPECTATION_STATUSES = frozenset({"accepted", "rejected", "not_evaluated"})
_PROJECTION_FIELDS = frozenset(
    {
        "schema_version",
        "outcome",
        "terminal_category",
        "completed_phases",
        "resource_status",
        "process_settled",
        "artifact_cleanup_status",
        "source_cleanliness_status",
        "expectation_status",
    }
)
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_PHASE_PATTERN = re.compile(r"SCALE[1-9][0-9]*\Z")


class PrelaunchReportingError(ValueError):
    """Raised when a prelaunch report is malformed or overclaims authority."""


@dataclass(frozen=True)
class PrelaunchExecutionResult:
    """One validated internal phase result, including private launch authority."""

    outcome: str
    terminal_category: str
    completed_phases: tuple[str, ...]
    resource_status: str
    process_settled: bool
    artifact_cleanup_status: str
    source_cleanliness_status: str
    expectation_status: str
    protected_result: ProtectedPrelaunchResult | None

    def validate(self) -> PrelaunchExecutionResult:
        _validate_common_fields(
            self.outcome,
            self.terminal_category,
            self.completed_phases,
            self.resource_status,
            self.process_settled,
            self.artifact_cleanup_status,
            self.source_cleanliness_status,
            self.expectation_status,
        )
        expects_authority = self.expectation_status == "accepted"
        if expects_authority != isinstance(
            self.protected_result, ProtectedPrelaunchResult
        ):
            raise PrelaunchReportingError("prelaunch expectation is inconsistent")
        if self.protected_result is not None:
            self.protected_result.validate()
        if self.outcome in {"accepted", "launch_refusal"} and not expects_authority:
            raise PrelaunchReportingError("prelaunch expectation is inconsistent")
        if self.outcome not in {"accepted", "launch_refusal"} and expects_authority:
            raise PrelaunchReportingError("prelaunch expectation is inconsistent")
        _require_complete_acceptance(
            self.outcome,
            self.completed_phases,
            self.resource_status,
            self.process_settled,
            self.artifact_cleanup_status,
            self.source_cleanliness_status,
            self.expectation_status,
        )
        return self


@dataclass(frozen=True)
class PublicSafePrelaunchProjection:
    """Immutable bounded phase projection without private launch authority."""

    schema_version: int
    outcome: str
    terminal_category: str
    completed_phases: tuple[str, ...]
    resource_status: str
    process_settled: bool
    artifact_cleanup_status: str
    source_cleanliness_status: str
    expectation_status: str

    @classmethod
    def from_internal(
        cls,
        result: PrelaunchExecutionResult,
    ) -> PublicSafePrelaunchProjection:
        if not isinstance(result, PrelaunchExecutionResult):
            raise PrelaunchReportingError("prelaunch internal result is invalid")
        result.validate()
        projection = cls(
            PUBLIC_PRELAUNCH_SCHEMA_VERSION,
            result.outcome,
            result.terminal_category,
            result.completed_phases,
            result.resource_status,
            result.process_settled,
            result.artifact_cleanup_status,
            result.source_cleanliness_status,
            result.expectation_status,
        )
        validate_projection_agreement(result, projection)
        return projection

    def validate(self) -> PublicSafePrelaunchProjection:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != PUBLIC_PRELAUNCH_SCHEMA_VERSION
        ):
            raise PrelaunchReportingError("prelaunch report schema is unsupported")
        _validate_common_fields(
            self.outcome,
            self.terminal_category,
            self.completed_phases,
            self.resource_status,
            self.process_settled,
            self.artifact_cleanup_status,
            self.source_cleanliness_status,
            self.expectation_status,
        )
        _require_complete_acceptance(
            self.outcome,
            self.completed_phases,
            self.resource_status,
            self.process_settled,
            self.artifact_cleanup_status,
            self.source_cleanliness_status,
            self.expectation_status,
        )
        return self

    def to_payload(self) -> dict[str, object]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "outcome": self.outcome,
            "terminal_category": self.terminal_category,
            "completed_phases": list(self.completed_phases),
            "resource_status": self.resource_status,
            "process_settled": self.process_settled,
            "artifact_cleanup_status": self.artifact_cleanup_status,
            "source_cleanliness_status": self.source_cleanliness_status,
            "expectation_status": self.expectation_status,
        }


def validate_projection_agreement(
    result: PrelaunchExecutionResult,
    projection: PublicSafePrelaunchProjection,
) -> None:
    """Prove that a public projection exactly agrees with its internal result."""

    if not isinstance(result, PrelaunchExecutionResult) or not isinstance(
        projection, PublicSafePrelaunchProjection
    ):
        raise PrelaunchReportingError("prelaunch projection agreement failed")
    try:
        result.validate()
        projection.validate()
    except PrelaunchReportingError as error:
        raise PrelaunchReportingError(
            "prelaunch projection agreement failed"
        ) from error
    fields = (
        "outcome",
        "terminal_category",
        "completed_phases",
        "resource_status",
        "process_settled",
        "artifact_cleanup_status",
        "source_cleanliness_status",
        "expectation_status",
    )
    if any(getattr(result, field) != getattr(projection, field) for field in fields):
        raise PrelaunchReportingError("prelaunch projection agreement failed")


def encode_public_prelaunch_projection(
    projection: PublicSafePrelaunchProjection,
) -> bytes:
    """Serialize one public projection deterministically within its hard bound."""

    if not isinstance(projection, PublicSafePrelaunchProjection):
        raise PrelaunchReportingError("prelaunch report is invalid")
    encoded = json.dumps(
        projection.to_payload(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_PUBLIC_PRELAUNCH_BYTES:
        raise PrelaunchReportingError("prelaunch report is oversized")
    return encoded


def decode_public_prelaunch_projection(
    encoded: bytes | str,
) -> PublicSafePrelaunchProjection:
    """Decode one strict projection, rejecting duplicate and unknown fields."""

    if isinstance(encoded, bytes):
        if len(encoded) > MAX_PUBLIC_PRELAUNCH_BYTES:
            raise PrelaunchReportingError("prelaunch report is oversized")
        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PrelaunchReportingError("prelaunch report is invalid") from error
    elif isinstance(encoded, str):
        text = encoded
        if len(text.encode("utf-8")) > MAX_PUBLIC_PRELAUNCH_BYTES:
            raise PrelaunchReportingError("prelaunch report is oversized")
    else:
        raise PrelaunchReportingError("prelaunch report is invalid")
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise PrelaunchReportingError("prelaunch report is invalid") from error
    if not isinstance(payload, dict) or frozenset(payload) != _PROJECTION_FIELDS:
        raise PrelaunchReportingError("prelaunch report fields are invalid")
    phases = payload["completed_phases"]
    if not isinstance(phases, list) or any(not isinstance(item, str) for item in phases):
        raise PrelaunchReportingError("prelaunch report phases are invalid")
    try:
        projection = PublicSafePrelaunchProjection(
            schema_version=payload["schema_version"],
            outcome=payload["outcome"],
            terminal_category=payload["terminal_category"],
            completed_phases=tuple(phases),
            resource_status=payload["resource_status"],
            process_settled=payload["process_settled"],
            artifact_cleanup_status=payload["artifact_cleanup_status"],
            source_cleanliness_status=payload["source_cleanliness_status"],
            expectation_status=payload["expectation_status"],
        )
    except KeyError as error:
        raise PrelaunchReportingError("prelaunch report fields are invalid") from error
    return projection.validate()


def operational_report_header(
    *,
    phase: str,
    outcome: str,
    primary_commit: str,
) -> str:
    """Return the canonical transient operational-report envelope header."""

    if not isinstance(phase, str) or _PHASE_PATTERN.fullmatch(phase) is None:
        raise PrelaunchReportingError("operational report phase is invalid")
    if outcome not in {"accepted", "bounded_stop", "decision_required"}:
        raise PrelaunchReportingError("operational report outcome is invalid")
    if (
        not isinstance(primary_commit, str)
        or _COMMIT_PATTERN.fullmatch(primary_commit) is None
    ):
        raise PrelaunchReportingError("operational report commit is invalid")
    return (
        "report_schema: operational-report-v1\n"
        f"phase: {phase}\n"
        f"outcome: {outcome}\n"
        f"primary_commit: {primary_commit}\n"
    )


def _validate_common_fields(
    outcome: object,
    terminal_category: object,
    completed_phases: object,
    resource_status: object,
    process_settled: object,
    artifact_cleanup_status: object,
    source_cleanliness_status: object,
    expectation_status: object,
) -> None:
    if not isinstance(outcome, str) or outcome not in _OUTCOME_CATEGORIES:
        raise PrelaunchReportingError("prelaunch outcome is invalid")
    if (
        not isinstance(terminal_category, str)
        or terminal_category != _OUTCOME_CATEGORIES[outcome]
    ):
        raise PrelaunchReportingError("prelaunch terminal category is invalid")
    if (
        not isinstance(completed_phases, tuple)
        or completed_phases != _COMPLETE_PHASES[: len(completed_phases)]
    ):
        raise PrelaunchReportingError("prelaunch completed phases are invalid")
    if (
        not isinstance(resource_status, str)
        or resource_status not in _RESOURCE_STATUSES
    ):
        raise PrelaunchReportingError("prelaunch resource status is invalid")
    if not isinstance(process_settled, bool):
        raise PrelaunchReportingError("prelaunch process settlement is invalid")
    if (
        not isinstance(artifact_cleanup_status, str)
        or artifact_cleanup_status not in _CLEANLINESS_STATUSES
    ):
        raise PrelaunchReportingError("prelaunch artifact cleanup is invalid")
    if (
        not isinstance(source_cleanliness_status, str)
        or source_cleanliness_status not in _CLEANLINESS_STATUSES
    ):
        raise PrelaunchReportingError("prelaunch source cleanliness is invalid")
    if (
        not isinstance(expectation_status, str)
        or expectation_status not in _EXPECTATION_STATUSES
    ):
        raise PrelaunchReportingError("prelaunch expectation status is invalid")


def _require_complete_acceptance(
    outcome: str,
    completed_phases: tuple[str, ...],
    resource_status: str,
    process_settled: bool,
    artifact_cleanup_status: str,
    source_cleanliness_status: str,
    expectation_status: str,
) -> None:
    if outcome != "accepted":
        return
    if (
        completed_phases != _COMPLETE_PHASES
        or resource_status != "accepted"
        or process_settled is not True
        or artifact_cleanup_status != "clean"
        or source_cleanliness_status != "clean"
        or expectation_status != "accepted"
    ):
        raise PrelaunchReportingError("accepted prelaunch result is incomplete")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PrelaunchReportingError("prelaunch report has duplicate fields")
        result[key] = value
    return result


__all__ = [
    "PrelaunchExecutionResult",
    "PrelaunchReportingError",
    "PublicSafePrelaunchProjection",
    "decode_public_prelaunch_projection",
    "encode_public_prelaunch_projection",
    "operational_report_header",
    "validate_projection_agreement",
]
