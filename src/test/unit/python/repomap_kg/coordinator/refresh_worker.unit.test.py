from io import BytesIO, StringIO
import sys
from threading import Event
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

import repomap_kg.coordinator.refresh_worker as refresh_worker
from repomap_kg.coordinator._core_disposition import CoreDispositionMixin
from repomap_kg.coordinator.protocol import encode_jsonl
from repomap_kg.coordinator.refresh_adapter import (
    RefreshConfigurationError,
    _extract_diagnostic_summary,
)
from repomap_kg.coordinator.refresh_worker import (
    _exception_terminal,
    _run_with_heartbeats,
    _write_failure_categories,
)
from repomap_kg.coordinator.semantics import RetryPolicy


def test_refresh_operation_emits_heartbeat_and_stops_owned_task():
    observed = Event()
    calls = []

    def operation():
        assert observed.wait(1)
        return "complete"

    def heartbeat():
        calls.append("heartbeat")
        observed.set()

    assert (
        _run_with_heartbeats(operation, heartbeat, interval_seconds=0.01)
        == "complete"
    )
    count = len(calls)
    assert count >= 1
    assert not observed.wait(0.02) or len(calls) == count


def test_worker_terminal_preserves_unsupported_configuration_diagnostic():
    capability = SimpleNamespace(
        job_id="job-refresh-1",
        attempt=1,
        graph_id="fixture-graph",
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
    )
    start = encode_jsonl(
        {
            "schema_version": 1,
            "message_type": "job_start",
            "job_id": capability.job_id,
            "attempt": capability.attempt,
            "job_kind": "refresh_graph",
            "graph_id": capability.graph_id,
            "source_generation": capability.source_generation,
            "config_generation": capability.config_generation,
        }
    )
    messages: list[dict[str, object]] = []
    fake_stdin = SimpleNamespace(buffer=BytesIO(start))
    with (
        patch.object(refresh_worker, "load_refresh_capability", return_value=capability),
        patch.object(
            refresh_worker,
            "execute_refresh",
            side_effect=RefreshConfigurationError(
                "multi-source-refresh-unsupported"
            ),
        ),
        patch.object(refresh_worker, "_write", side_effect=messages.append),
        patch.object(refresh_worker.sys, "stdin", fake_stdin),
    ):
        assert refresh_worker.main(
            ["--capability", "fixture", "--job-id", capability.job_id, "--attempt", "1"]
        ) == 0

    terminal = messages[-1]
    assert terminal["error_category"] == "configuration"
    assert terminal["diagnostics"] == ["multi-source-refresh-unsupported"]
    assert terminal["publication_state"] == "not_started"


def test_worker_terminal_does_not_publish_unregistered_configuration_text():
    capability = SimpleNamespace(
        graph_id="fixture-graph",
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
    )

    terminal = _exception_terminal(
        capability,
        {"job_id": "job-refresh-1", "attempt": 1},
        started=False,
        diagnostic="refresh configuration failed",
    )

    assert terminal["error_category"] == "configuration"
    assert terminal["diagnostics"] == []


def test_write_failure_categories_formats_and_redacts() -> None:
    result = SimpleNamespace(
        result="failure",
        diagnostics=({"code": "executable-unavailable"},),
        error="connection to server at '127.0.0.1' failed: password authentication failed for user 'secret'",
    )
    captured = StringIO()
    with patch.object(sys, "stderr", captured):
        _write_failure_categories(result)
    output = captured.getvalue().strip()
    assert output.startswith("refresh-failure:")
    parts = output.split(":", 2)
    assert len(parts) == 3
    categories = parts[1].split(",")
    assert "executable-unavailable" in categories
    assert "connection-unavailable" in categories or "authorization-failed" in categories


def test_extract_diagnostic_summary_from_terminal_diagnostics() -> None:
    result = SimpleNamespace(
        terminal={"diagnostics": ["multi-source-refresh-unsupported", "second-diag"]},
        stderr="",
    )
    summary = _extract_diagnostic_summary(result)
    assert summary == "multi-source-refresh-unsupported;second-diag"


def test_extract_diagnostic_summary_from_stderr_refresh_failure() -> None:
    stderr = (
        "some info line\n"
        "refresh-failure:connection-unavailable,schema-unavailable:database relation missing\n"
        "another line\n"
    )
    result = SimpleNamespace(
        terminal={},
        stderr=stderr,
        stderr_truncated=False,
    )
    summary = _extract_diagnostic_summary(result)
    assert summary == "refresh-failure:connection-unavailable,schema-unavailable:database relation missing"


def test_extract_diagnostic_summary_handles_truncation() -> None:
    long_error = "x" * 300
    stderr = f"refresh-failure:unclassified:{long_error}\n"
    result = SimpleNamespace(
        terminal={},
        stderr=stderr,
        stderr_truncated=True,
    )
    summary = _extract_diagnostic_summary(result)
    assert summary is not None
    assert len(summary) <= 256
    assert summary.endswith("...")


def test_extract_diagnostic_summary_fallback_redacts() -> None:
    stderr = "Error: path /private/tmp/secret/token not found\n"
    result = SimpleNamespace(
        terminal={},
        stderr=stderr,
        stderr_truncated=False,
    )
    summary = _extract_diagnostic_summary(result)
    assert summary is not None
    assert len(summary) <= 256
    assert "/private/tmp" not in summary or "secret" not in summary


def test_extract_diagnostic_summary_prefers_stderr_refresh_failure_over_generic_diagnostic() -> None:
    stderr = "refresh-failure:portable-authority-denied:permission denied on path /secret/file\n"
    result = SimpleNamespace(
        terminal={"diagnostics": ["refresh-failed"]},
        stderr=stderr,
        stderr_truncated=False,
    )
    summary = _extract_diagnostic_summary(result)
    assert summary == "refresh-failure:portable-authority-denied:permission denied on path [path]"


def test_extract_diagnostic_summary_preserves_generic_diagnostic_without_refresh_failure() -> None:
    stderr = "some non-failure output\n"
    result = SimpleNamespace(
        terminal={"diagnostics": ["refresh-failed"]},
        stderr=stderr,
        stderr_truncated=False,
    )
    summary = _extract_diagnostic_summary(result)
    assert summary == "refresh-failed"


def test_extract_diagnostic_summary_preserves_specific_terminal_diagnostic() -> None:
    stderr = "refresh-failure:worker-crash:something failed\n"
    result = SimpleNamespace(
        terminal={"diagnostics": ["schema-unavailable"]},
        stderr=stderr,
        stderr_truncated=False,
    )
    summary = _extract_diagnostic_summary(result)
    assert summary == "schema-unavailable"


def test_extract_diagnostic_summary_byte_safe_truncation_multibyte() -> None:
    text = "a" * 254 + "€€"
    stderr = f"refresh-failure:{text}\n"
    result = SimpleNamespace(
        terminal={},
        stderr=stderr,
        stderr_truncated=False,
    )
    summary = _extract_diagnostic_summary(result)
    assert summary is not None
    encoded = summary.encode("utf-8")
    assert len(encoded) <= 256
    assert encoded.decode("utf-8") == summary


def test_extract_diagnostic_summary_from_protocol_error() -> None:
    result = SimpleNamespace(
        terminal={},
        stderr="",
        protocol_error="protocol_violation: unexpected message received from worker",
    )
    summary = _extract_diagnostic_summary(result)
    assert summary == "protocol_violation: unexpected message received from worker"


def test_extract_diagnostic_summary_from_cleanup_error() -> None:
    result = SimpleNamespace(
        terminal={},
        stderr="",
        protocol_error=None,
        cleanup_error="cleanup_error: process group failed to terminate",
    )
    summary = _extract_diagnostic_summary(result)
    assert summary == "cleanup_error: process group failed to terminate"


def test_core_disposition_passes_diagnostic_summary_to_mark_reconciliation() -> None:
    class DummyCoordinator(CoreDispositionMixin):
        def __init__(self) -> None:
            self._store = MagicMock()
            self._store.mark_reconciliation_required.return_value = True
            self._store.mark_attempt_terminated.return_value = True
            self._publication_reader = None
            self._instance_id = "inst-1"
            self._retry_policy = RetryPolicy(2, 1, 1)

        def _require_started(self) -> int:
            return 1

        def _transition(self, *args: object, **kwargs: object) -> bool:
            return True

    coord = DummyCoordinator()
    claim = cast(Any, SimpleNamespace(job_id="job-1", attempt=2, graph_id="graph-1", instance_id="inst-1", fencing_epoch=1))
    terminal = {
        "status": "failed",
        "publication_state": "commit_unknown",
        "_termination_proved": True,
        "_error_category": "publication_unknown",
        "_diagnostic_summary": "refresh-failure:connection-unavailable:failed to connect",
    }
    outcome = coord._dispose_terminal(claim, "running", terminal)
    assert outcome == "reconciliation_required"
    cast(Any, coord._store).mark_reconciliation_required.assert_called_once_with(
        claim,
        expected_state="running",
        category="publication_unknown",
        diagnostic_summary="refresh-failure:connection-unavailable:failed to connect",
    )


def test_ops_refresh_error_is_strictly_preflight_configuration_error() -> None:
    from repomap_kg.ops.report_records import OpsRefreshError
    from repomap_kg.coordinator._refresh_execution import execute_refresh_attempt

    capability = MagicMock()
    capability.config_path.exists.return_value = True
    capability.psql_path.exists.return_value = True
    capability.graph_id = "test-graph"

    with (
        patch("repomap_kg.ops.config.load_ops_config"),
        patch("repomap_kg.runtime.database_role_contract.project_database_role_config"),
        patch("repomap_kg.coordinator._refresh_execution.validate_configured_generations"),
        patch("repomap_kg.ops.refresh.refresh_graph") as mock_refresh,
    ):
        mock_refresh.side_effect = OpsRefreshError("graph 'test-graph' is disabled")
        with pytest.raises(RefreshConfigurationError, match="disabled"):
            execute_refresh_attempt(capability)
