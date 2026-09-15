from __future__ import annotations

import pytest

from repomap_kg.coordinator.protocol import (
    MAX_JSONL_LINE_BYTES,
    ProtocolError,
    ProtocolSession,
    decode_jsonl,
    encode_jsonl,
)


IDENTITY = {"job_id": "job-public-1", "attempt": 1}
HELLO = {
    "schema_version": 1,
    "message_type": "worker_hello",
    "protocol_versions": [1],
    "worker_generation": "worker-v1",
    "capabilities": ["refresh_graph"],
    "process_nonce": "nonce-public-1",
}
JOB_START = {
    "schema_version": 1,
    "message_type": "job_start",
    **IDENTITY,
    "job_kind": "refresh_graph",
    "graph_id": "synthetic-graph",
    "source_generation": "sg1:synthetic",
    "config_generation": "cg1:synthetic",
}
PROGRESS = {
    "schema_version": 1,
    "message_type": "progress",
    **IDENTITY,
    "completed": 1,
    "total": 2,
    "phase": "discovery",
    "unit": "files",
    "message_category": "files-discovered",
    "heartbeat_at": "2026-07-13T12:00:02Z",
}
HEARTBEAT = {
    "schema_version": 1,
    "message_type": "heartbeat",
    **IDENTITY,
    "heartbeat_at": "2026-07-13T12:00:03Z",
}
CANCEL = {
    "schema_version": 1,
    "message_type": "cancel",
    **IDENTITY,
}
CANCEL_ACK = {
    "schema_version": 1,
    "message_type": "cancel_ack",
    **IDENTITY,
    "status": "accepted",
}


def terminal(message_type: str = "result", **changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "message_type": message_type,
        **IDENTITY,
        "job_kind": "refresh_graph",
        "graph_id": "synthetic-graph",
        "status": "succeeded" if message_type == "result" else "failed",
        "started_at": "2026-07-13T12:00:01Z",
        "finished_at": "2026-07-13T12:00:04Z",
        "phase": "complete",
        "files": 1,
        "observations": 2,
        "canonical_nodes": 3,
        "canonical_edges": 4,
        "warnings": [],
        "diagnostics": [],
        "publication_state": "committed" if message_type == "result" else "not_started",
        "latest_run_identity": "run-public-1" if message_type == "result" else None,
        "source_generation": "sg1:synthetic",
        "config_generation": "cg1:synthetic",
        "extractor_generation": "extractor-v1",
        "canonicalizer_generation": "canonical-v1",
        "retryable": message_type == "error",
        "error_category": None if message_type == "result" else "transient",
    }
    payload.update(changes)
    return payload


def started_session() -> ProtocolSession:
    session = ProtocolSession(IDENTITY)
    session.accept_worker(HELLO)
    session.accept_coordinator(JOB_START)
    return session


def test_jsonl_one_mibibyte_boundary_and_strict_json():
    payload_size = MAX_JSONL_LINE_BYTES - len(b'{"value":""}\n')
    encoded = encode_jsonl({"value": "x" * payload_size})
    assert len(encoded) == MAX_JSONL_LINE_BYTES
    assert decode_jsonl(encoded)["value"] == "x" * payload_size

    for frame in (b"x" * MAX_JSONL_LINE_BYTES + b"\n", b"{}", b"[]\n",
                  b'{"v":1,"v":1}\n', b'{"value":NaN}\n'):
        with pytest.raises(ProtocolError):
            decode_jsonl(frame)


def test_exact_v1_hello_negotiates_before_job_start_and_worker_messages():
    session = ProtocolSession(IDENTITY)
    assert session.accept_worker(HELLO) == HELLO
    assert session.accept_coordinator(JOB_START) == JOB_START
    session.accept_worker(PROGRESS)
    session.accept_worker(HEARTBEAT)
    result = session.accept_worker(terminal())

    assert session.terminal == result
    assert session.negotiated_version == 1


@pytest.mark.parametrize(
    ("direction", "payload", "code"),
    [
        ("worker", {**HELLO, "schema_version": 2}, "unsupported_version"),
        ("worker", {**HELLO, "protocol_versions": [2]}, "negotiation_failed"),
        ("worker", {**HELLO, "protocol_versions": [1, 2]}, "negotiation_failed"),
        ("worker", {**HELLO, "extra": True}, "invalid_fields"),
        ("worker", {"schema_version": 1, "message_type": "unknown"}, "unknown_type"),
        ("worker", {**HELLO, "message_type": "worker_exit"}, "internal_message"),
        ("coordinator", HELLO, "wrong_direction"),
        ("worker", JOB_START, "wrong_direction"),
    ],
)
def test_version_type_fields_internal_event_and_direction_are_strict(
    direction: str, payload: dict[str, object], code: str
):
    session = ProtocolSession(IDENTITY)
    operation = session.accept_worker if direction == "worker" else session.accept_coordinator
    with pytest.raises(ProtocolError, match=code):
        operation(payload)


@pytest.mark.parametrize(
    ("setup", "direction", "payload", "code"),
    [
        ("none", "worker", PROGRESS, "out_of_order"),
        ("none", "worker", terminal(), "out_of_order"),
        ("hello", "worker", PROGRESS, "out_of_order"),
        ("hello", "worker", terminal(), "out_of_order"),
        ("hello", "coordinator", CANCEL, "out_of_order"),
        ("started", "worker", CANCEL_ACK, "out_of_order"),
        ("started", "coordinator", JOB_START, "out_of_order"),
        ("started", "worker", HELLO, "out_of_order"),
    ],
)
def test_all_pre_start_and_cancellation_ordering_edges_are_rejected(
    setup: str, direction: str, payload: dict[str, object], code: str
):
    session = ProtocolSession(IDENTITY)
    if setup in {"hello", "started"}:
        session.accept_worker(HELLO)
    if setup == "started":
        session.accept_coordinator(JOB_START)
    operation = session.accept_worker if direction == "worker" else session.accept_coordinator
    with pytest.raises(ProtocolError, match=code):
        operation(payload)


def test_cancel_ack_and_cancelled_result_follow_cancel_in_order():
    session = started_session()
    session.accept_coordinator(CANCEL)
    session.accept_worker(CANCEL_ACK)
    cancelled = terminal(
        status="cancelled",
        publication_state="rolled_back",
        latest_run_identity=None,
    )
    session.accept_worker(cancelled)
    assert session.terminal == cancelled


@pytest.mark.parametrize("publication_state", ["not_started", "rolled_back"])
def test_cancelled_terminal_accepts_only_proved_safe_publication(
    publication_state: str,
):
    started_session().accept_worker(terminal(
        status="cancelled",
        publication_state=publication_state,
        latest_run_identity=None,
    ))


@pytest.mark.parametrize(
    "publication_state",
    ["not_applicable", "prepared", "transaction_started", "committed",
     "commit_unknown"],
)
def test_cancelled_terminal_rejects_non_safe_or_committed_publication(
    publication_state: str,
):
    latest_run = "run-public-1" if publication_state == "committed" else None
    with pytest.raises(ProtocolError, match="invalid_value"):
        started_session().accept_worker(terminal(
            status="cancelled",
            publication_state=publication_state,
            latest_run_identity=latest_run,
        ))


def test_committed_publication_requires_success_result():
    with pytest.raises(ProtocolError, match="invalid_value"):
        started_session().accept_worker(terminal(
            "error",
            publication_state="committed",
            latest_run_identity="run-public-1",
        ))


def test_cancel_ack_accepts_the_documented_already_complete_spelling():
    session = started_session()
    session.accept_coordinator(CANCEL)
    session.accept_worker({**CANCEL_ACK, "status": "already-complete"})


def test_post_hello_identity_and_single_terminal_are_enforced():
    session = started_session()
    with pytest.raises(ProtocolError, match="identity_mismatch"):
        session.accept_worker({**HEARTBEAT, "attempt": 2})
    session.accept_worker(terminal())
    with pytest.raises(ProtocolError, match="duplicate_terminal"):
        session.accept_worker(terminal())
    with pytest.raises(ProtocolError, match="message_after_terminal"):
        session.accept_worker(HEARTBEAT)


@pytest.mark.parametrize(
    ("field", "value"),
    [("job_id", "job-public-2"), ("attempt", 2), ("job_kind", "other"),
     ("graph_id", "synthetic-other"), ("source_generation", "sg1:other"),
     ("config_generation", "cg1:other")],
)
def test_terminal_identity_is_bound_to_the_accepted_job_start(field: str, value: object):
    with pytest.raises(ProtocolError, match="identity_mismatch"):
        started_session().accept_worker(terminal("result", **{field: value}))


@pytest.mark.parametrize(
    "phase",
    ["waiting", "starting", "preflight", "discovery", "extraction",
     "canonicalization", "storage_prepare", "storage_publish", "verification",
     "cleanup", "complete"],
)
def test_progress_accepts_exact_async1_phase_vocabulary(phase: str):
    started_session().accept_worker({**PROGRESS, "phase": phase})


@pytest.mark.parametrize(
    "changes",
    [{"phase": "publishing"}, {"unit": "percent"},
     {"message_category": "private-detail"},
     {"heartbeat_at": "not-a-timestamp"}],
)
def test_progress_rejects_values_outside_fixed_vocabularies(changes: dict[str, object]):
    with pytest.raises(ProtocolError, match="invalid_value"):
        started_session().accept_worker({**PROGRESS, **changes})


@pytest.mark.parametrize(
    "payload",
    [{**HEARTBEAT, "heartbeat_at": "2026-02-30T12:00:03Z"},
     terminal(started_at="2026-07-13 12:00:01"),
     terminal(finished_at="2026-07-13T11:59:59Z"), terminal(phase="invented")],
)
def test_protocol_timestamps_and_terminal_phase_are_validated(payload: dict[str, object]):
    with pytest.raises(ProtocolError, match="invalid_value"):
        started_session().accept_worker(payload)


@pytest.mark.parametrize(
    ("payload", "direction"),
    [
        ({**HELLO, "worker_generation": "database"}, "worker"),
        ({**HELLO, "worker_generation": "https://private.example/worker"}, "worker"),
        ({**HELLO, "worker_generation": "release/private/worker"}, "worker"),
        ({**HELLO, "process_nonce": "/private/value"}, "worker"),
        ({**JOB_START, "graph_id": "../real-graph"}, "coordinator"),
        ({**JOB_START, "source_generation": "source-generation"}, "coordinator"),
        ({**JOB_START, "config_generation": "cg1:database"}, "coordinator"),
        (terminal(extractor_generation="token=private"), "terminal"),
        (terminal(canonicalizer_generation="/private/value"), "terminal"),
        (terminal(latest_run_identity="backup"), "terminal"),
    ],
)
def test_protocol_rejects_authority_or_private_content_on_string_channels(
    payload: dict[str, object], direction: str,
):
    session = ProtocolSession(IDENTITY)
    if direction == "worker":
        operation = session.accept_worker
    elif direction == "coordinator":
        session.accept_worker(HELLO)
        operation = session.accept_coordinator
    else:
        session.accept_worker(HELLO)
        session.accept_coordinator(JOB_START)
        operation = session.accept_worker
    with pytest.raises(ProtocolError, match="invalid_value"):
        operation(payload)


def test_session_identity_rejects_private_content():
    with pytest.raises(ProtocolError, match="invalid_identity"):
        ProtocolSession({"job_id": "/private/job", "attempt": 1})


@pytest.mark.parametrize(
    "payload",
    [
        terminal(extra=True),
        terminal(files=-1),
        terminal(files=2**100),
        terminal(warnings=["unknown-category"]),
        terminal(publication_state="invented"),
        terminal(error_category="transient"),
        terminal("error", error_category=None),
    ],
)
def test_result_and_error_require_exact_bounded_fields(payload: dict[str, object]):
    with pytest.raises(ProtocolError):
        started_session().accept_worker(payload)


def test_progress_counters_enforce_the_configured_hard_bound():
    with pytest.raises(ProtocolError, match="invalid_value"):
        started_session().accept_worker({**PROGRESS, "completed": 2**100})

    with pytest.raises(ProtocolError, match="invalid_value"):
        started_session().accept_worker(
            {**PROGRESS, "completed": 1, "total": 2**100}
        )


@pytest.mark.parametrize(
    "payload",
    [{**PROGRESS, "phase": []}, {**PROGRESS, "unit": {}},
     {**PROGRESS, "message_category": []}, terminal(publication_state=[]),
     terminal("error", error_category={}), terminal(warnings=[{}])],
)
def test_unhashable_protocol_values_are_bounded_rejections(payload: dict[str, object]):
    with pytest.raises(ProtocolError, match="invalid_value"):
        started_session().accept_worker(payload)
