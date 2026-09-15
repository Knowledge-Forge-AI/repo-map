from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

from repomap_kg.coordinator.refresh_worker import main as worker_main
from repomap_kg.coordinator.refresh_adapter import _extract_diagnostic_summary
from repomap_kg.coordinator._core_disposition import CoreDispositionMixin


def test_early_capability_bootstrap_failure_emits_structured_stderr() -> None:
    stderr = io.StringIO()
    with patch("sys.stderr", stderr):
        exit_code = worker_main(["--capability", "nonexistent_file.json", "--job-id", "j1", "--attempt", "1"])
    assert exit_code == 2
    output = stderr.getvalue()
    assert output.startswith("refresh-failure:capability-error:")


def test_early_identity_mismatch_failure_emits_structured_stderr() -> None:
    stderr = io.StringIO()
    with patch("repomap_kg.coordinator.refresh_worker.load_refresh_capability") as mock_load:
        mock_cap = MagicMock()
        mock_cap.job_id = "other_job"
        mock_cap.attempt = 1
        mock_load.return_value = mock_cap
        with patch("sys.stderr", stderr):
            exit_code = worker_main(["--capability", "dummy.json", "--job-id", "my_job", "--attempt", "1"])
    assert exit_code == 2
    output = stderr.getvalue()
    assert "refresh-failure:capability-error:" in output or "refresh-failure:worker-error:" in output


def test_protocol_failure_emits_structured_stderr() -> None:
    stderr = io.StringIO()
    with patch("repomap_kg.coordinator.refresh_worker.load_refresh_capability") as mock_load:
        mock_cap = MagicMock()
        mock_cap.job_id = "j1"
        mock_cap.attempt = 1
        mock_load.return_value = mock_cap
        with patch("sys.stdin.buffer.readline", return_value=b"invalid-json\n"):
            with patch("sys.stdout.buffer.write"), patch("sys.stdout.buffer.flush"):
                with patch("sys.stderr", stderr):
                    exit_code = worker_main(["--capability", "dummy.json", "--job-id", "j1", "--attempt", "1"])
    assert exit_code == 2
    output = stderr.getvalue()
    assert output.startswith("refresh-failure:protocol-error:")


def test_unexpected_exception_after_start_emits_redacted_stderr() -> None:
    stderr = io.StringIO()
    with patch("repomap_kg.coordinator.refresh_worker.load_refresh_capability") as mock_load:
        mock_cap = MagicMock()
        mock_cap.job_id = "j1"
        mock_cap.attempt = 1
        mock_cap.graph_id = "g1"
        mock_cap.source_generation = "sg1:source"
        mock_cap.config_generation = "cg1:config"
        mock_cap.extractor_generation = "eg1:synthetic"
        mock_cap.canonicalizer_generation = "kg1:synthetic"
        mock_load.return_value = mock_cap
        with patch("repomap_kg.coordinator.refresh_worker._run_with_heartbeats", side_effect=ValueError("secret password in /secret/path")):
            start_bytes = json.dumps({'schema_version': 1, 'message_type': 'job_start', 'job_id': 'j1', 'attempt': 1, 'job_kind': 'refresh_graph', 'graph_id': 'g1', 'source_generation': 'sg1:source', 'config_generation': 'cg1:config'}).encode() + b"\n"
            with patch("sys.stdin.buffer.readline", return_value=start_bytes):
                with patch("sys.stdout.buffer.write"), patch("sys.stdout.buffer.flush"):
                    with patch("sys.stderr", stderr):
                        exit_code = worker_main(["--capability", "dummy.json", "--job-id", "j1", "--attempt", "1"])
    assert exit_code == 0
    output = stderr.getvalue()
    assert "refresh-failure:worker-error:" in output
    assert "[redacted-password]" in output or "password" in output


def test_supervisor_extracts_and_redacts_stderr_summary() -> None:
    result = MagicMock()
    result.terminal = None
    result.stderr = "refresh-failure:capability-error:file /var/private/secret/cap.json not found\n"
    result.stderr_truncated = False
    result.returncode = 2
    summary = _extract_diagnostic_summary(result)
    assert summary is not None
    assert summary.startswith("refresh-failure:capability-error:")
    assert "/var/private/secret/cap.json" not in summary
    assert "[path]" in summary


def test_supervisor_fallback_to_returncode_when_stderr_empty() -> None:
    result = MagicMock()
    result.terminal = None
    result.stderr = ""
    result.stderr_truncated = False
    result.protocol_error = None
    result.cleanup_error = None
    result.process_timed_out = False
    result.heartbeat_timed_out = False
    result.hello_timed_out = False
    result.returncode = 2
    summary = _extract_diagnostic_summary(result)
    assert summary == "worker_exit:2"


def test_supervisor_persistence_into_job_attempts() -> None:
    class DummyCoordinator(CoreDispositionMixin):
        def __init__(self, store):
            self._store = store
            self._retry_policy = MagicMock()
            self._retry_policy.may_retry.return_value = False
            self._instance_id = "coord-1"
            self._publication_reader = None
            self.transitions = []

        def _require_started(self) -> int:
            return 1

        def _transition(self, claim, expected_state, new_state, publication_state=None, error_category=None, diagnostic_summary=None) -> bool:
            self.transitions.append({
                "diagnostic_summary": diagnostic_summary,
                "error_category": error_category,
                "new_state": new_state,
            })
            return True

        def _release_terminal_lease(self, claim):
            pass

    store = MagicMock()
    coord = DummyCoordinator(store)
    claim = MagicMock()
    claim.attempt = 1
    claim.job_id = "j1"
    terminal = {
        "status": "failed",
        "publication_state": "not_started",
        "error_category": "worker_crash",
        "_termination_proved": True,
        "_diagnostic_summary": "refresh-failure:capability-error:[path] not found",
    }
    coord._dispose_terminal(claim, "running", terminal)
    assert len(coord.transitions) == 1
    assert coord.transitions[0]["diagnostic_summary"] == "refresh-failure:capability-error:[path] not found"
