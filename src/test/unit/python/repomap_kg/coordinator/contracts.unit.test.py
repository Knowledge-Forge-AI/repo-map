from __future__ import annotations

from dataclasses import fields, replace
from collections.abc import MutableMapping
from typing import cast
import pytest
from repomap_kg.coordinator import (
    DEFAULT_LIMITS, HARD_MAX_LIMITS, CoordinatorLimits, JobRequest, JobState, PublicationState,
    is_public_safe_text, normalize_request, project_public_error, project_public_status,
    validate_generation, validate_transition,
)
from repomap_kg.coordinator.contracts import LEGAL_TRANSITIONS, _PUBLIC_ERROR_SUMMARIES
from repomap_kg.storage.authority import RequestId

EXPECTED_PUBLIC_ERROR_SUMMARIES = {
    "cancelled": "operation cancelled", "authorization": "request is unauthorized",
    "cancel_failed": "worker cancellation failed", "configuration": "configuration is invalid",
    "generation_changed": "requested generation changed", "internal": "internal coordinator failure",
    "permanent": "permanent failure", "privacy": "privacy policy violation",
    "protocol": "worker protocol failure", "publication_unknown": "publication outcome is unknown",
    "source_unavailable": "source is unavailable", "source_capture": "source capture failed",
    "storage_unavailable": "storage is unavailable", "superseded": "job was superseded",
    "transient": "transient failure", "transient_database": "transient database failure",
    "worker_crash": "worker crashed", "worker_launch": "worker failed to launch",
    "worker_timeout": "worker timed out",
}


def accepted_request() -> dict[str, object]:
    return {
        "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "synthetic-example-graph",
        "request_id": "request-001", "idempotency_key": "manual-refresh-001", "priority": "manual",
        "operation_options": {"reason": "operator-request"},
    }


def normalize(payload: dict[str, object] | None = None) -> JobRequest:
    return normalize_request(
        accepted_request() if payload is None else payload,
        source_generation="sg1:abc123", config_generation="cg1:def456",
    )


def test_normalize_request_accepts_exact_synthetic_v1_envelope() -> None:
    request = normalize()
    assert request == JobRequest(
        schema_version=1, job_kind="refresh_graph", graph_id="synthetic-example-graph",
        request_id=RequestId("request-001"), idempotency_key="manual-refresh-001",
        priority="manual", operation_options=(("reason", "operator-request"),),
        source_generation="sg1:abc123", config_generation="cg1:def456",
    )
    assert request.semantic_payload() == {
        "config_generation": "cg1:def456", "canonicalizer_generation": "kg1:synthetic",
        "extractor_generation": "eg1:synthetic", "graph_id": "synthetic-example-graph",
        "job_kind": "refresh_graph", "operation_options": {"reason": "operator-request"},
        "priority": "manual", "request_id": "request-001", "schema_version": 1,
        "source_generation": "sg1:abc123",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", "chosen-job"), ("root", "/private/source"), ("database", "private_database"),
        ("command", ["sh", "-c", "unsafe"]), ("sql", "DROP DATABASE example"), ("credential", "secret"),
        ("connector", "arbitrary"), ("source_generation", "sg1:caller-selected"),
        ("config_generation", "cg1:caller-selected"),
    ],
)
def test_normalize_request_rejects_extra_authority_fields(field: str, value: object) -> None:
    payload = accepted_request()
    payload[field] = value
    with pytest.raises(ValueError, match="request fields"):
        normalize(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2), ("job_kind", "backup"), ("graph_id", "configured-real-graph"),
        ("priority", "critical"), ("operation_options", {"worker_mode": "arbitrary"}),
    ],
)
def test_normalize_request_rejects_unsupported_values(field: str, value: object) -> None:
    payload = accepted_request()
    payload[field] = value
    with pytest.raises(ValueError):
        normalize(payload)


def test_normalize_request_rejects_missing_fields_and_oversized_strings() -> None:
    missing = accepted_request()
    missing.pop("request_id")
    with pytest.raises(ValueError, match="request fields"):
        normalize(missing)
    oversized = accepted_request()
    oversized["request_id"] = "x" * (DEFAULT_LIMITS.max_identifier_chars + 1)
    with pytest.raises(ValueError, match="request_id"):
        normalize(oversized)


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", "/private/source"), ("idempotency_key", "password=not-public"),
        ("request_id", "../outside-root"), ("idempotency_key", "token=not-public"),
        ("operation_options", {"reason": "DROP DATABASE example"}),
        ("operation_options", {"reason": "sh -c unsafe-command"}),
        ("operation_options", {"reason": '{"raw_payload":"private"}'}),
    ],
)
def test_normalize_request_rejects_prohibited_content_without_echoing_it(field: str, value: object) -> None:
    payload = accepted_request()
    payload[field] = value
    with pytest.raises(ValueError) as caught:
        normalize(payload)
    assert (str(caught.value), str(value) not in str(caught.value)) == ("request value contains prohibited content", True)


@pytest.mark.parametrize("field", ["request_id", "idempotency_key", "reason"])
@pytest.mark.parametrize("marker", ["database", "backup", "command", "connector"])
def test_normalize_request_rejects_embedded_authority_markers(field: str, marker: str) -> None:
    payload = accepted_request()
    value = f"safe-prefix-{marker}-safe-suffix"
    if field == "reason":
        payload["operation_options"] = {"reason": value}
    else:
        payload[field] = value
    with pytest.raises(ValueError) as caught:
        normalize(payload)
    assert (str(caught.value), value not in str(caught.value)) == ("request value contains prohibited content", True)


def test_normalize_request_rejects_unhashable_priority_with_bounded_error() -> None:
    payload = accepted_request()
    payload["priority"] = ["manual"]
    with pytest.raises(ValueError) as caught:
        normalize(payload)
    assert str(caught.value) == "unsupported priority"


def test_normalize_request_rejects_control_characters() -> None:
    payload = accepted_request()
    payload["request_id"] = "request\x00hidden"
    with pytest.raises(ValueError, match="invalid request_id"):
        normalize(payload)


def test_job_and_publication_state_vocabularies_are_exact() -> None:
    assert {s.value for s in JobState} == {
        "queued", "claimed", "starting", "running", "cancel_requested", "cancelling",
        "succeeded", "failed", "cancelled", "superseded", "quarantined", "reconciliation_required",
    }
    assert {s.value for s in PublicationState} == {
        "not_applicable", "not_started", "prepared", "transaction_started",
        "committed", "rolled_back", "commit_unknown",
    }


@pytest.mark.parametrize(
    "current,target",
    [
        (JobState.QUEUED, JobState.CLAIMED), (JobState.CLAIMED, JobState.STARTING),
        (JobState.STARTING, JobState.RUNNING), (JobState.RUNNING, JobState.SUCCEEDED),
        (JobState.RUNNING, JobState.RECONCILIATION_REQUIRED), (JobState.RECONCILIATION_REQUIRED, JobState.QUEUED),
        (JobState.CANCEL_REQUESTED, JobState.CANCELLING), (JobState.CANCELLING, JobState.CANCELLED),
    ],
)
def test_validate_transition_accepts_central_legal_paths(current: JobState, target: JobState) -> None:
    assert validate_transition(current, target) is target


def test_validate_transition_rejects_illegal_and_terminal_transitions() -> None:
    with pytest.raises(ValueError, match="illegal job transition"):
        validate_transition(JobState.QUEUED, JobState.RUNNING)
    terminals = {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED, JobState.SUPERSEDED, JobState.QUARANTINED}
    for terminal in terminals:
        for target in JobState:
            with pytest.raises(ValueError, match="illegal job transition"):
                validate_transition(terminal, target)


def test_legal_transition_table_is_immutable() -> None:
    with pytest.raises(TypeError):
        invalid_mutable = cast(MutableMapping[JobState, frozenset[JobState]], LEGAL_TRANSITIONS)
        invalid_mutable[JobState.QUEUED] = frozenset()


@pytest.mark.parametrize("token,prefix", [("sg1:abc123", "sg1:"), ("cg1:def456", "cg1:")])
def test_validate_generation_accepts_versioned_opaque_digests(token: str, prefix: str) -> None:
    assert validate_generation(token, prefix) == token


@pytest.mark.parametrize(
    "token,prefix",
    [
        ("abc123", "sg1:"), ("cg1:abc123", "sg1:"), ("sg1:", "sg1:"),
        ("sg1:contains/path", "sg1:"), ("sg1:contains space", "sg1:"),
    ],
)
def test_validate_generation_rejects_wrong_or_unsafe_tokens(token: str, prefix: str) -> None:
    with pytest.raises(ValueError, match="generation"):
        validate_generation(token, prefix)


def test_validate_generation_rejects_unknown_prefixes() -> None:
    with pytest.raises(ValueError, match="invalid generation"):
        validate_generation("sg1:abc123", "unknown:")


def test_public_safe_text_rejects_non_utf8_and_private_content() -> None:
    assert (
        is_public_safe_text("public-safe", maximum=32),
        not is_public_safe_text("bad\ud800", maximum=32),
        not is_public_safe_text("token=secret", maximum=32),
    ) == (True, True, True)


def test_public_projections_are_allowlist_only_and_bounded() -> None:
    private_status = {
        "job_id": "job-001", "request_id": "request-001", "job_kind": "refresh_graph",
        "graph_id": "synthetic-example-graph", "priority": "manual", "state": "running",
        "attempt_count": 1, "phase": "extraction", "files": 7, "source_generation_match": True,
        "root": "/private/source", "database": "private_database", "lease_token": "secret-token",
        "diagnostics": ["private traceback"],
    }
    private_error = {
        "error_category": "worker_crash", "retryable": False,
        "summary": "password=secret /private/source", "raw_error": "password=secret /private/source",
        "traceback": "private traceback",
    }
    assert project_public_status(private_status) == {
        "attempt_count": 1, "files": 7, "graph_id": "synthetic-example-graph",
        "job_id": "job-001", "job_kind": "refresh_graph", "phase": "extraction",
        "priority": "manual", "request_id": "request-001", "source_generation_match": True,
        "state": "running",
    }
    assert project_public_error(private_error) == {"error_category": "worker_crash", "retryable": False, "summary": "worker crashed"}


def test_public_projection_rejects_invalid_counters() -> None:
    with pytest.raises(ValueError, match="attempt_count"):
        project_public_status({"attempt_count": -1})
    with pytest.raises(ValueError, match="files"):
        project_public_status({"files": DEFAULT_LIMITS.max_counter + 1})


def test_public_projection_fails_closed_for_private_identifier_shape() -> None:
    with pytest.raises(ValueError, match="job_id"):
        project_public_status({"job_id": "/private/source"})


def test_public_status_validates_every_allowlisted_value() -> None:
    status = {
        "job_id": "job-001", "request_id": "request-001", "job_kind": "refresh_graph",
        "graph_id": "synthetic-example-graph", "priority": "manual",
        "submitted_at": "2026-07-13T12:00:00Z", "started_at": "2026-07-13T12:00:01Z",
        "finished_at": "2026-07-13T12:00:02Z", "state": "succeeded", "attempt_count": 1,
        "phase": "complete", "files": 3, "observations": 4, "canonical_nodes": 5,
        "canonical_edges": 6, "source_generation_match": True, "config_generation_match": True,
        "extractor_generation_match": False, "canonicalizer_generation_match": False,
    }
    assert project_public_status(status) == status


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", "/private/source"), ("job_id", "token:not-public"), ("request_id", "password=not-public"),
        ("job_kind", "backup"), ("graph_id", "configured-real-graph"), ("priority", "critical"),
        ("submitted_at", "/private/source"), ("started_at", "DROP DATABASE example"),
        ("finished_at", "sh -c unsafe-command"), ("state", "invented"), ("phase", '{"raw_payload":"private"}'),
        ("attempt_count", True), ("files", -1), ("source_generation_match", "yes"),
        ("config_generation_match", 1), ("extractor_generation_match", None),
        ("canonicalizer_generation_match", []),
    ],
)
def test_public_status_rejects_invalid_or_private_allowlisted_values(field: str, value: object) -> None:
    with pytest.raises(ValueError) as caught:
        project_public_status({field: value})
    assert (str(caught.value), str(value) not in str(caught.value)) == (f"invalid public status field: {field}", True)


@pytest.mark.parametrize("field", ["priority", "phase"])
def test_public_status_rejects_unhashable_membership_values(field: str) -> None:
    with pytest.raises(ValueError) as caught:
        project_public_status({field: ["invalid"]})
    assert str(caught.value) == f"invalid public status field: {field}"


@pytest.mark.parametrize(
    "category,summary",
    [
        ("worker_crash", "worker crashed"), ("publication_unknown", "publication outcome is unknown"),
        ("worker_timeout", "worker timed out"), ("authorization", "request is unauthorized"),
    ],
)
def test_public_error_uses_exact_categories_and_fixed_summaries(category: str, summary: str) -> None:
    assert project_public_error(
        {"error_category": category, "retryable": False, "summary": "/private/source password=not-public"}
    ) == {"error_category": category, "retryable": False, "summary": summary}


def test_public_error_category_set_and_summaries_are_exact() -> None:
    assert _PUBLIC_ERROR_SUMMARIES == EXPECTED_PUBLIC_ERROR_SUMMARIES
    for category, summary in EXPECTED_PUBLIC_ERROR_SUMMARIES.items():
        assert project_public_error({"error_category": category}) == {
            "error_category": category, "summary": summary,
        }


def test_public_error_rejects_unknown_category_without_echoing_it() -> None:
    unknown = "private_database_name"
    with pytest.raises(ValueError) as caught:
        project_public_error({"error_category": unknown})
    assert (str(caught.value), unknown not in str(caught.value)) == ("invalid public error category", True)


@pytest.mark.parametrize(
    "error",
    [
        {"error_category": []},
        {"error_category": "worker_timeout", "retryable": 1},
        {"error_category": "worker_timeout", "summary": ["private"]},
    ],
)
def test_public_error_rejects_invalid_allowlisted_value_types(error: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        project_public_error(error)


def test_public_error_rejects_caller_summary_without_category() -> None:
    with pytest.raises(ValueError, match="invalid public error category"):
        project_public_error({"summary": "caller supplied"})


def test_public_error_allows_an_empty_public_projection() -> None:
    assert project_public_error({"private_detail": "not projected"}) == {}


def test_default_limits_are_positive_within_every_hard_maximum() -> None:
    DEFAULT_LIMITS.validate(hard_maxima=HARD_MAX_LIMITS)
    for field in fields(CoordinatorLimits):
        assert 0 < getattr(DEFAULT_LIMITS, field.name) <= getattr(HARD_MAX_LIMITS, field.name), field.name


def test_claim_and_lease_pilot_limits_have_fixed_defaults_and_hard_maxima() -> None:
    assert (DEFAULT_LIMITS.manual_claim_burst, HARD_MAX_LIMITS.manual_claim_burst) == (3, 32)
    assert (DEFAULT_LIMITS.graph_lease_duration_seconds, HARD_MAX_LIMITS.graph_lease_duration_seconds) == (60, 600)
    assert (DEFAULT_LIMITS.lease_renewal_interval_seconds, HARD_MAX_LIMITS.lease_renewal_interval_seconds) == (10, 60)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_running_mutating_workers": 5}, {"max_running_read_operations": 5},
        {"max_in_flight_requests": 2}, {"max_protocol_line_bytes": 8 * 1024},
        {"max_retry_backoff_seconds": 1}, {"cleanup_batch_size": 300},
        {"claim_deadline_seconds": 5}, {"process_deadline_seconds": 5},
        {"lease_renewal_interval_seconds": 60},
    ],
)
def test_every_limit_relationship_is_validated_at_startup(changes: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        replace(DEFAULT_LIMITS, **changes).validate(hard_maxima=HARD_MAX_LIMITS)


@pytest.mark.parametrize("invalid", [0, -1, True])
def test_every_limit_rejects_zero_negative_and_bool(invalid: int) -> None:
    for field in fields(CoordinatorLimits):
        limits = replace(DEFAULT_LIMITS, **{field.name: invalid})
        with pytest.raises(ValueError):
            limits.validate(hard_maxima=HARD_MAX_LIMITS)


def test_every_limit_rejects_values_above_its_hard_maximum() -> None:
    for field in fields(CoordinatorLimits):
        limits = replace(DEFAULT_LIMITS, **{field.name: getattr(HARD_MAX_LIMITS, field.name) + 1})
        with pytest.raises(ValueError):
            limits.validate(hard_maxima=HARD_MAX_LIMITS)


def test_hard_maxima_cannot_be_weaker_than_source_defined_bounds() -> None:
    assert (HARD_MAX_LIMITS.max_protocol_line_bytes, HARD_MAX_LIMITS.max_diagnostic_bytes) == (1024 * 1024, 64 * 1024)
