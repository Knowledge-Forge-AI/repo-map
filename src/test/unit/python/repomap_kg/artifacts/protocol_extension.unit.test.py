from __future__ import annotations

import pytest

from repomap_kg.coordinator._protocol_core import ProtocolError, ProtocolSession


IDENTITY = {"job_id": "job-1", "attempt": 1}
LEGACY_HELLO = {
    "schema_version": 1,
    "message_type": "worker_hello",
    "protocol_versions": [1],
    "worker_generation": "worker-v1",
    "capabilities": ["refresh_graph"],
    "process_nonce": "nonce-1",
}
PORTABLE_HELLO = {
    **LEGACY_HELLO,
    "capabilities": ["refresh_graph", "portable_snapshot_v1"],
}
LEGACY_START = {
    "schema_version": 1,
    "message_type": "job_start",
    **IDENTITY,
    "job_kind": "refresh_graph",
    "graph_id": "graph-a",
    "source_generation": "sg1:source",
    "config_generation": "cg1:config",
}
EXTENSION = {
    "contract_version": "1.0",
    "required": True,
    "snapshot_manifest": {
        "content_digest": "sha256:" + "a" * 64,
        "size_bytes": 123,
        "media_type": "application/x-repomap-snapshot-manifest-v1+json",
        "record_format": "canonical-json-v1",
        "privacy": "raw_source",
        "locator": {"kind": "object", "value": "objects/a", "store_version": "object-v1"},
    },
}


def reference(media_type: str, record_format: str) -> dict[str, object]:
    return {
        "content_digest": "sha256:" + "b" * 64,
        "size_bytes": 321,
        "media_type": media_type,
        "record_format": record_format,
        "privacy": "canonical_provenance",
        "locator": {"kind": "object", "value": "objects/b", "store_version": "object-v1"},
    }


def terminal(*, outcome: str, completed: bool) -> dict[str, object]:
    return {
        "schema_version": 1,
        "message_type": "result" if outcome in {"completed", "cancelled"} else "error",
        **IDENTITY,
        "job_kind": "refresh_graph",
        "graph_id": "graph-a",
        "status": "succeeded" if outcome == "completed" else ("cancelled" if outcome == "cancelled" else "failed"),
        "started_at": "2026-08-31T12:00:00Z",
        "finished_at": "2026-08-31T12:00:01Z",
        "phase": "complete",
        "files": 0,
        "observations": 0,
        "canonical_nodes": 0,
        "canonical_edges": 0,
        "warnings": [],
        "diagnostics": [],
        "publication_state": "not_started",
        "latest_run_identity": None,
        "source_generation": "sg1:source",
        "config_generation": "cg1:config",
        "extractor_generation": "eg1:extractor",
        "canonicalizer_generation": "kg1:canonicalizer",
        "retryable": False,
        "error_category": None if outcome in {"completed", "cancelled"} else outcome,
        "portable_snapshot": {
            "contract_version": "1.0",
            "outcome": outcome,
            "receipt": reference(
                "application/x-repomap-extraction-receipt-v1+json",
                "canonical-json-v1",
            ),
            "bundle": reference(
                "application/x-repomap-publication-bundle-v1+jsonl",
                "canonical-jsonl-v1",
            ) if completed else None,
        },
    }


def test_legacy_worker_request_and_result_contract_remain_unchanged() -> None:
    session = ProtocolSession(IDENTITY)
    session.accept_worker(LEGACY_HELLO)
    assert session.accept_coordinator(LEGACY_START) == LEGACY_START


def test_required_extension_negotiates_explicitly_without_silent_downgrade() -> None:
    legacy = ProtocolSession(IDENTITY)
    legacy.accept_worker(LEGACY_HELLO)
    with pytest.raises(ProtocolError, match="negotiation_failed"):
        legacy.accept_coordinator({**LEGACY_START, "portable_snapshot": EXTENSION})

    portable = ProtocolSession(IDENTITY)
    portable.accept_worker(PORTABLE_HELLO)
    accepted = portable.accept_coordinator({**LEGACY_START, "portable_snapshot": EXTENSION})
    assert accepted["portable_snapshot"] == EXTENSION


@pytest.mark.parametrize("version", ["2.0", "1.999", 1, None])
def test_unknown_or_malformed_contract_versions_fail_closed(version: object) -> None:
    session = ProtocolSession(IDENTITY)
    session.accept_worker(PORTABLE_HELLO)
    with pytest.raises(ProtocolError, match="unsupported_extension"):
        session.accept_coordinator(
            {**LEGACY_START, "portable_snapshot": {**EXTENSION, "contract_version": version}}
        )


@pytest.mark.parametrize(
    "forbidden",
    [
        {"database_url": "opaque"},
        {"sql": "opaque"},
        {"command": "opaque"},
        {"host_path": "opaque"},
        {"bearer_token": "opaque"},
        {"signed_url": "opaque"},
        {"publication_permission": True},
    ],
)
def test_extension_cannot_represent_authority_or_secret_fields(forbidden: dict[str, object]) -> None:
    session = ProtocolSession(IDENTITY)
    session.accept_worker(PORTABLE_HELLO)
    with pytest.raises(ProtocolError, match="invalid_extension"):
        session.accept_coordinator(
            {**LEGACY_START, "portable_snapshot": {**EXTENSION, **forbidden}}
        )


@pytest.mark.parametrize(
    "outcome,completed",
    [
        ("completed", True),
        ("cancelled", False),
        ("source_changed", False),
        ("unsupported_contract", False),
        ("contract_validation", False),
    ],
)
def test_result_extension_distinguishes_terminal_outcomes_without_publication_authority(
    outcome: str, completed: bool
) -> None:
    session = ProtocolSession(IDENTITY)
    session.accept_worker(PORTABLE_HELLO)
    session.accept_coordinator({**LEGACY_START, "portable_snapshot": EXTENSION})

    accepted = session.accept_worker(terminal(outcome=outcome, completed=completed))

    snapshot_obj = accepted.get("portable_snapshot")
    assert isinstance(snapshot_obj, dict)
    assert snapshot_obj.get("outcome") == outcome
    assert accepted["publication_state"] == "not_started"
    assert accepted["latest_run_identity"] is None


def test_completed_result_requires_bundle_and_noncompleted_result_forbids_it() -> None:
    session = ProtocolSession(IDENTITY)
    session.accept_worker(PORTABLE_HELLO)
    session.accept_coordinator({**LEGACY_START, "portable_snapshot": EXTENSION})
    changed = terminal(outcome="completed", completed=True)
    raw_snapshot = changed.get("portable_snapshot")
    assert isinstance(raw_snapshot, dict)
    snapshot_dict: dict[str, object] = dict(raw_snapshot)
    snapshot_dict["bundle"] = None
    changed["portable_snapshot"] = snapshot_dict

    with pytest.raises(ProtocolError, match="invalid_extension"):
        session.accept_worker(changed)


@pytest.mark.parametrize("outcome", ("cancelled", "semantic_workload"))
def test_current_noncompleted_result_explicitly_versions_receipt_absence(outcome) -> None:
    session = ProtocolSession(IDENTITY)
    session.accept_worker(PORTABLE_HELLO)
    session.accept_coordinator({**LEGACY_START, "portable_snapshot": EXTENSION})
    changed = terminal(outcome=outcome, completed=False)
    raw_snapshot = changed.get("portable_snapshot")
    assert isinstance(raw_snapshot, dict)
    snapshot_dict: dict[str, object] = dict(raw_snapshot)
    snapshot_dict["receipt"] = None
    snapshot_dict["receipt_status"] = "unavailable"
    snapshot_dict["receipt_diagnostic"] = "write_failed"
    changed["portable_snapshot"] = snapshot_dict

    session.accept_worker(changed)


@pytest.mark.parametrize(
    "mutation",
    (
        {"receipt_status": "stored", "receipt_diagnostic": "write_failed"},
        {"receipt_status": "unavailable", "receipt_diagnostic": None},
        {"receipt_status": "unavailable", "receipt_diagnostic": "private/path"},
    ),
)
def test_current_receipt_status_shape_fails_closed_on_inconsistent_or_sensitive_fields(
    mutation,
) -> None:
    session = ProtocolSession(IDENTITY)
    session.accept_worker(PORTABLE_HELLO)
    session.accept_coordinator({**LEGACY_START, "portable_snapshot": EXTENSION})
    changed = terminal(outcome="source_capture", completed=False)
    raw_snapshot = changed.get("portable_snapshot")
    assert isinstance(raw_snapshot, dict)
    snapshot_dict: dict[str, object] = dict(raw_snapshot)
    snapshot_dict["receipt"] = None
    snapshot_dict.update(mutation)
    changed["portable_snapshot"] = snapshot_dict

    with pytest.raises(ProtocolError, match="invalid_extension"):
        session.accept_worker(changed)


@pytest.mark.parametrize(
    "outcome",
    [
        "artifact_missing",
        "artifact_stale",
        "artifact_corrupt",
        "unsupported_capability",
    ],
)
def test_portable_artifact_and_capability_failures_are_protocol_categories(
    outcome: str,
) -> None:
    session = ProtocolSession(IDENTITY)
    session.accept_worker(PORTABLE_HELLO)
    session.accept_coordinator({**LEGACY_START, "portable_snapshot": EXTENSION})

    accepted = session.accept_worker(terminal(outcome=outcome, completed=False))

    assert accepted["error_category"] == outcome


def test_portable_failure_outcome_must_equal_terminal_error_category() -> None:
    session = ProtocolSession(IDENTITY)
    session.accept_worker(PORTABLE_HELLO)
    session.accept_coordinator({**LEGACY_START, "portable_snapshot": EXTENSION})
    changed = terminal(outcome="artifact_corrupt", completed=False)
    changed["error_category"] = "artifact_missing"

    with pytest.raises(ProtocolError, match="invalid_extension"):
        session.accept_worker(changed)


def test_error_terminal_cannot_silently_omit_extension_when_requested() -> None:
    session = ProtocolSession(IDENTITY)
    session.accept_worker(PORTABLE_HELLO)
    session.accept_coordinator({**LEGACY_START, "portable_snapshot": EXTENSION})
    error_without_ext = {
        "schema_version": 1,
        "message_type": "error",
        **IDENTITY,
        "job_kind": "refresh_graph",
        "graph_id": "graph-a",
        "status": "failed",
        "started_at": "2026-08-31T12:00:00Z",
        "finished_at": "2026-08-31T12:00:01Z",
        "phase": "complete",
        "files": 0,
        "observations": 0,
        "canonical_nodes": 0,
        "canonical_edges": 0,
        "warnings": [],
        "diagnostics": [],
        "publication_state": "not_started",
        "latest_run_identity": None,
        "source_generation": "sg1:source",
        "config_generation": "cg1:config",
        "extractor_generation": "eg1:extractor",
        "canonicalizer_generation": "kg1:canonicalizer",
        "retryable": False,
        "error_category": "artifact_missing",
    }
    with pytest.raises(ProtocolError, match="negotiation_failed"):
        session.accept_worker(error_without_ext)
