from __future__ import annotations

from unittest.mock import patch

import pytest

from repomap_kg.coordinator.protocol import (
    MAX_RETAINED_DIAGNOSTIC_BYTES,
    ProtocolError,
    ProtocolSession,
    retain_stderr,
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

def test_diagnostics_enforce_64_kib_hard_ceiling_and_sanitize_sensitive_text():
    sensitive = (
        b"Traceback (most recent call last):\n"
        b"/private/operator/root/file.py\n"
        b"/opt/repository/private-file.py\n"
        b"password=not-public token=not-public\n"
        b"SELECT * FROM private_table\n"
    )
    retained, total, truncated = retain_stderr(
        [sensitive, b"x" * MAX_RETAINED_DIAGNOSTIC_BYTES],
        max_bytes=MAX_RETAINED_DIAGNOSTIC_BYTES,
    )
    assert total > MAX_RETAINED_DIAGNOSTIC_BYTES
    assert truncated is True
    assert len(retained.encode()) <= MAX_RETAINED_DIAGNOSTIC_BYTES
    for prohibited in ("Traceback", "/private/", "/opt/", "password", "token=", "SELECT"):
        assert prohibited not in retained
    with pytest.raises(ValueError, match="hard ceiling"):
        retain_stderr([], max_bytes=MAX_RETAINED_DIAGNOSTIC_BYTES + 1)


def test_diagnostics_redact_generic_absolute_paths():
    retained, _, _ = retain_stderr(
        [b"worker failed near /opt/repository/private-file.py\n"], max_bytes=256)
    assert "/opt/" not in retained


def test_diagnostics_redact_credential_header_and_colon_forms():
    retained, _, _ = retain_stderr(
        [b"Authorization: Bearer not-public\napi_key: not-public\n"],
        max_bytes=256,
    )
    assert "Bearer" not in retained
    assert "api_key" not in retained


def test_protocol_errors_are_bounded_payload_free_and_traceback_free():
    private_value = "/private/operator/path?password=not-public"
    with pytest.raises(ProtocolError) as caught:
        ProtocolSession(IDENTITY).accept_worker({**HELLO, "extra": private_value})
    rendered = str(caught.value)
    assert len(rendered.encode()) <= 160
    assert private_value not in rendered
    assert "Traceback" not in rendered


def test_runner_reports_process_boundary_failure_without_fallback():
    from repomap_kg.coordinator import protocol
    from repomap_test_support.synthetic_worker_adapter import (
        run_synthetic_worker,
    )

    with patch.object(
        protocol,
        "launch_managed_process",
        side_effect=protocol.ProcessBoundaryError("job assignment failed"),
    ):
        with pytest.raises(ProtocolError, match="worker_launch_failed"):
            run_synthetic_worker("success", IDENTITY, {})
