"""Closed recovery result and early-refusal contract."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest import mock

from common_lore_index.ops import retained_attempt_recovery as recovery
from common_lore_index.ops.config_records import OpsConfig


def _config(*graphs: SimpleNamespace) -> OpsConfig:
    return cast(OpsConfig, SimpleNamespace(graphs=graphs))


def _graph(*, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id="graph-a",
        enabled=enabled,
        readback_unsupported_classification=None,
    )


def test_result_projection_is_closed_and_exit_code_is_positive_only_for_success() -> None:
    ready = recovery.RetainedAttemptRecovery(
        "inspect", "ready", "accepted-proof", "publication-reconciliation",
        "matched", "matched", "not-attempted",
    )
    held = recovery.RetainedAttemptRecovery(
        "settle", "held", "lock-busy", "publication-reconciliation",
        "matched", "matched", "not-attempted",
    )

    assert ready.exit_code == 0
    assert held.exit_code == 1
    assert set(ready.to_jsonable()) == {
        "operation", "result", "reason", "retention_state",
        "artifact_proof", "publication_proof", "metadata_write_state",
    }


def test_unknown_graph_refuses_before_attempt_path_or_database_work() -> None:
    config = _config()
    with mock.patch.object(recovery, "_attempt_root") as root:
        result = recovery.recover_server_retained_attempt(
            config, "missing", "operation-1", 1,
        )

    assert result.to_jsonable() == {
        "operation": "inspect",
        "result": "refused",
        "reason": "graph-unknown",
        "retention_state": "unavailable",
        "artifact_proof": "not-checked",
        "publication_proof": "not-checked",
        "metadata_write_state": "not-attempted",
    }
    root.assert_not_called()


def test_disabled_graph_refuses_before_artifact_or_database_work() -> None:
    config = _config(_graph(enabled=False))
    with mock.patch.object(recovery, "_attempt_root") as root:
        result = recovery.recover_server_retained_attempt(
            config, "graph-a", "operation-1", 1,
        )

    assert result.result == "refused"
    assert result.reason == "graph-disabled"
    root.assert_not_called()


def test_receipt_owner_disagreement_is_held_without_database_proof(
    tmp_path: Path,
) -> None:
    config = _config(_graph())
    record = SimpleNamespace(retention_class="publication-reconciliation")
    receipt = SimpleNamespace(graph_id="graph-a", attempt=1, job_id="other-operation")
    proof = SimpleNamespace(receipt=receipt)

    with mock.patch.object(recovery, "_attempt_root", return_value=tmp_path / "a"), \
        mock.patch.object(recovery, "read_retained_record", return_value=record), \
        mock.patch.object(recovery, "FileSystemArtifactStore"), \
        mock.patch.object(recovery, "read_retained_artifacts", return_value=proof), \
        mock.patch.object(recovery, "_proof") as db_proof:
        result = recovery.recover_server_retained_attempt(
            config, "graph-a", "operation-1", 1,
        )

    assert result.result == "held"
    assert result.reason == "publication-mismatch"
    db_proof.assert_not_called()


def test_inspect_returns_ready_without_metadata_write_when_proof_matches(
    tmp_path: Path,
) -> None:
    config = _config(_graph())
    record = SimpleNamespace(retention_class="publication-reconciliation")
    receipt = SimpleNamespace(graph_id="graph-a", attempt=1, job_id="operation-1")
    proof = SimpleNamespace(receipt=receipt)

    with mock.patch.object(recovery, "_attempt_root", return_value=tmp_path / "a"), \
        mock.patch.object(recovery, "read_retained_record", return_value=record), \
        mock.patch.object(recovery, "FileSystemArtifactStore"), \
        mock.patch.object(recovery, "read_retained_artifacts", return_value=proof), \
        mock.patch.object(recovery, "_proof", return_value=True), \
        mock.patch.object(recovery, "ServerRetentionLock") as lock:
        result = recovery.recover_server_retained_attempt(
            config, "graph-a", "operation-1", 1,
        )

    assert result.result == "ready"
    assert result.exit_code == 0
    lock.assert_not_called()


def test_lock_cleanup_failure_after_install_reports_uncertain_metadata(tmp_path: Path) -> None:
    config = _config(_graph())
    record = SimpleNamespace(retention_class="publication-reconciliation")
    receipt = SimpleNamespace(graph_id="graph-a", attempt=1, job_id="operation-1")
    proof = SimpleNamespace(receipt=receipt)

    class FailingRelease:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            raise OSError("injected release failure after installed metadata")

    def install(*_args, **_kwargs):
        record.retention_class = "terminal-accepted"

    with mock.patch.object(recovery, "_attempt_root", return_value=tmp_path / "a"), \
        mock.patch.object(recovery, "read_retained_record", return_value=record), \
        mock.patch.object(recovery, "FileSystemArtifactStore"), \
        mock.patch.object(recovery, "read_retained_artifacts", return_value=proof), \
        mock.patch.object(recovery, "_proof", return_value=True), \
        mock.patch.object(recovery, "same_record", return_value=True), \
        mock.patch.object(recovery, "install_terminal_accepted", side_effect=install), \
        mock.patch.object(recovery, "ServerRetentionLock", return_value=FailingRelease()):
        result = recovery.recover_server_retained_attempt(
            config, "graph-a", "operation-1", 1, settle=True,
        )
    assert record.retention_class == "terminal-accepted"
    assert result.result == "uncertain"
    assert result.retention_state == "terminal-accepted"
    assert result.metadata_write_state == "uncertain"


def test_record_io_failure_is_a_closed_held_outcome(tmp_path: Path) -> None:
    config = _config(_graph())
    with mock.patch.object(recovery, "_attempt_root", return_value=tmp_path / "a"), \
        mock.patch.object(recovery, "read_retained_record", side_effect=OSError("private injected detail")):
        result = recovery.recover_server_retained_attempt(config, "graph-a", "operation-1", 1)
    assert result.result == "held" and result.reason == "record-unavailable"
    assert "private injected detail" not in str(result.to_jsonable())
    assert result.metadata_write_state == "not-attempted"
