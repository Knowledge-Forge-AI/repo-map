from __future__ import annotations

import hashlib
import json
from typing import cast

import pytest

from repomap_kg.coordinator import _control_submission as subject
from repomap_kg.coordinator.contracts import JobRequest
from repomap_kg.coordinator.limits import CoordinatorLimits
from repomap_kg.storage.authority import RequestId
from repomap_test_support.control_db_fakes import ScriptedCursor, connect_with


def request(*, priority: str = "manual") -> JobRequest:
    return JobRequest(
        schema_version=1,
        job_kind="refresh_graph",
        graph_id="synthetic-example-graph",
        request_id=RequestId("request-001"),
        idempotency_key="request-key",
        priority=priority,
        operation_options=(("reason", "operator-request"),),
        source_generation="sg1:abc123",
        config_generation="cg1:def456",
        extractor_generation="eg1:ghi789",
        canonicalizer_generation="kg1:jkl012",
    )


def fingerprint(value: JobRequest) -> str:
    payload = json.dumps(
        value.semantic_payload(), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def test_submit_replays_matching_idempotent_request(monkeypatch) -> None:
    value = request()
    cursor = ScriptedCursor(
        rows=[
            {
                "job_id": "existing-job",
                "state": "queued",
                "request_fingerprint": fingerprint(value),
            }
        ]
    )
    monkeypatch.setattr(subject, "require_transaction_admission", lambda *_: None)

    result = subject.submit(
        connect_with(cursor), value, requester="operator", limits=CoordinatorLimits()
    )

    assert (result.job_id, result.state, result.replayed) == (
        "existing-job",
        "queued",
        True,
    )


def test_submit_rejects_idempotency_conflict(monkeypatch) -> None:
    cursor = ScriptedCursor(
        rows=[
            {
                "job_id": "existing-job",
                "state": "queued",
                "request_fingerprint": "different",
            }
        ]
    )
    monkeypatch.setattr(subject, "require_transaction_admission", lambda *_: None)

    with pytest.raises(ValueError, match="idempotency conflict"):
        subject.submit(
            connect_with(cursor),
            request(),
            requester="operator",
            limits=CoordinatorLimits(),
        )


@pytest.mark.parametrize(("priority", "expected_priority"), [("manual", 100), ("automatic", 50)])
def test_submit_inserts_new_request(monkeypatch, priority, expected_priority) -> None:
    rows: list[dict[str, object] | None] = [None, {"job_count": 0}]
    if priority == "manual":
        rows.append({"job_count": 0})
    rows.append({"job_id": "new-job", "state": "queued"})
    cursor = ScriptedCursor(rows=rows)
    monkeypatch.setattr(subject, "require_transaction_admission", lambda *_: None)

    result = subject.submit(
        connect_with(cursor),
        request(priority=priority),
        requester="operator",
        limits=CoordinatorLimits(),
    )

    assert (result.job_id, result.state, result.replayed) == (
        "new-job",
        "queued",
        False,
    )
    insert_parameters = cursor.executions[-1][1]
    assert isinstance(insert_parameters, (list, tuple))
    assert insert_parameters[9] == expected_priority


def test_admission_rejects_global_limit() -> None:
    cursor = ScriptedCursor(rows=[{"job_count": 1}])
    limits = CoordinatorLimits(max_nonterminal_jobs=1)

    with pytest.raises(ValueError, match="nonterminal job limit"):
        subject._enforce_admission(cursor, request(), limits)


def test_admission_rejects_manual_graph_limit() -> None:
    cursor = ScriptedCursor(rows=[{"job_count": 0}, {"job_count": 1}])
    limits = CoordinatorLimits(max_queued_manual_jobs_per_graph=1)

    with pytest.raises(ValueError, match="manual queue limit"):
        subject._enforce_admission(cursor, request(), limits)


def test_admission_skips_manual_limit_for_automatic_request() -> None:
    cursor = ScriptedCursor(rows=[{"job_count": 0}])

    subject._enforce_admission(cursor, request(priority="automatic"), CoordinatorLimits())

    assert len(cursor.executions) == 1


def test_find_existing_returns_database_row() -> None:
    row = {"job_id": "job", "state": "queued", "request_fingerprint": "hash"}
    cursor = ScriptedCursor(rows=[row])

    assert subject._find_existing(cursor, "operator", request(), "digest") == row


def test_validate_request_rejects_wrong_type() -> None:
    def _invalid_job_request(value: object) -> JobRequest:
        """Narrow runtime-invalid JobRequest builder for negative controls."""
        return cast(JobRequest, value)

    with pytest.raises(TypeError, match="validated JobRequest"):
        subject.validate_request(_invalid_job_request(object()))


def test_validate_request_rejects_noncanonical_instance(monkeypatch) -> None:
    monkeypatch.setattr(subject, "normalize_request", lambda *_args, **_kwargs: request())

    with pytest.raises(ValueError, match="canonically normalized"):
        subject.validate_request(request(priority="automatic"))


@pytest.mark.parametrize("value", ["contains space", "UPPER", "", 7])
def test_safe_category_rejects_non_public_values(value) -> None:
    with pytest.raises(ValueError, match="public-safe category"):
        subject._safe_category(value, "field")


def test_safe_category_accepts_public_slug() -> None:
    assert subject._safe_category("operator-request", "field") == "operator-request"


def test_validate_request_missing_reason_option() -> None:
    bad_req = JobRequest(
        schema_version=1,
        job_kind="refresh_graph",
        graph_id="synthetic-example-graph",
        request_id=RequestId("request-001"),
        idempotency_key="request-key",
        priority="manual",
        operation_options=(),
        source_generation="sg1:abc123",
        config_generation="cg1:def456",
        extractor_generation="eg1:ghi789",
        canonicalizer_generation="kg1:jkl012",
    )
    with pytest.raises(ValueError, match="unsupported operation_options"):
        subject.validate_request(bad_req)


def test_validate_request_invalid_reason_option() -> None:
    bad_req = JobRequest(
        schema_version=1,
        job_kind="refresh_graph",
        graph_id="synthetic-example-graph",
        request_id=RequestId("request-001"),
        idempotency_key="request-key",
        priority="manual",
        operation_options=(("reason", "INVALID REASON"),),
        source_generation="sg1:abc123",
        config_generation="cg1:def456",
        extractor_generation="eg1:ghi789",
        canonicalizer_generation="kg1:jkl012",
    )
    with pytest.raises(ValueError, match="operation_options reason must be a public-safe category"):
        subject.validate_request(bad_req)


def test_submit_rejects_invalid_requester() -> None:
    cursor = ScriptedCursor()
    with pytest.raises(ValueError, match="requester must be a public-safe category"):
        subject.submit(
            connect_with(cursor),
            request(),
            requester="INVALID REQUESTER",
            limits=CoordinatorLimits(),
        )
