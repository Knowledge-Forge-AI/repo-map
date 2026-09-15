"""Native Windows evidence for the ASYNC14 coordinator runtime boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from repomap_kg.coordinator.client import CoordinatorClientError, LocalCoordinatorClient
from repomap_kg.coordinator.endpoint import (
    EndpointDescriptorError,
    LoopbackEndpointDescriptor,
    load_endpoint_descriptor,
    write_endpoint_descriptor,
)
from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from repomap_kg.coordinator.local_mode import _resolve_psql_executable
from repomap_kg.coordinator.process_supervision import launch_managed_process
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.transport import LocalRequestDispatcher, LoopbackTcpService
from repomap_kg.coordinator.windows_security import (
    apply_owner_private_acl,
    validate_owner_private_acl,
)
from repomap_test_support.synthetic_worker_adapter import run_synthetic_worker


pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="ASYNC14 native evidence requires Windows"
)


def _dispatcher() -> LocalRequestDispatcher:
    return LocalRequestDispatcher(
        "native-auth-token-123",
        {
            "health": lambda _payload: {"status": "ready"},
            "submit": lambda _payload: {"job_id": "native-job-1"},
            "status": lambda _payload: {"job_id": "native-job-1", "state": "queued"},
            "wait": lambda _payload: {"job_id": "native-job-1", "state": "queued"},
            "cancel": lambda _payload: {"job_id": "native-job-1", "state": "cancelled"},
            "list": lambda _payload: {"jobs": [], "next_cursor": None},
        },
        max_in_flight=8,
    )


def _private_runtime(tmp_path: Path) -> Path:
    runtime = tmp_path / "coordinator"
    runtime.mkdir()
    apply_owner_private_acl(runtime)
    validate_owner_private_acl(runtime)
    return runtime


def test_loopback_descriptor_acl_rotation_frames_and_concurrent_clients(tmp_path: Path):
    runtime = _private_runtime(tmp_path)
    endpoint = runtime / "coordinator.endpoint.json"
    service = LoopbackTcpService(
        endpoint,
        _dispatcher(),
        auth_token="native-auth-token-123",
        instance_id="native-instance-1",
        fencing_epoch=1,
        max_connections=8,
        max_frame_bytes=256,
    )
    with service:
        descriptor = load_endpoint_descriptor(endpoint)
        validate_owner_private_acl(endpoint)
        assert descriptor.host == "127.0.0.1"
        assert descriptor.port > 0
        client = LocalCoordinatorClient(endpoint, endpoint, timeout_seconds=2)
        health = client.health()
        assert health["status"] == "ready"
        assert health["health_schema_version"] == 1
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent_health = list(pool.map(lambda _value: client.health(), range(8)))
        assert all(item["status"] == "ready" for item in concurrent_health)
        assert all(
            item["health_schema_version"] == 1 for item in concurrent_health
        )
        with socket.create_connection((descriptor.host, descriptor.port), timeout=2) as raw:
            raw.sendall(b"not-json\n")
            assert json.loads(raw.makefile("rb").readline())["error_category"] == (
                "invalid_request"
            )
        with socket.create_connection((descriptor.host, descriptor.port), timeout=2) as raw:
            raw.sendall(b"x" * 257 + b"\n")
            assert json.loads(raw.makefile("rb").readline())["error_category"] == (
                "frame_too_large"
            )
        rotated = LoopbackEndpointDescriptor(
            schema_version=1,
            host="127.0.0.1",
            port=descriptor.port,
            instance_id=descriptor.instance_id,
            fencing_epoch=descriptor.fencing_epoch + 1,
            auth_token="rotated-auth-token-123",
        )
        write_endpoint_descriptor(endpoint, rotated)
        with pytest.raises(CoordinatorClientError, match="unauthorized"):
            LocalCoordinatorClient(endpoint, endpoint, timeout_seconds=2).health()
        with pytest.raises(EndpointDescriptorError, match="stale"):
            load_endpoint_descriptor(endpoint, expected_fencing_epoch=1)
    endpoint.unlink(missing_ok=True)


def test_foreground_service_uses_loopback_adapter_and_removes_descriptor(tmp_path: Path):
    runtime = _private_runtime(tmp_path)

    class Coordinator:
        def startup(self, reconcile):
            reconcile()

        def run_once(self):
            return "idle"

        def heartbeat(self):
            return True

        def shutdown(self):
            return None

        def submit(self, operation):
            return operation()

        def request_cancel(self, _job_id):
            return "cancelled"

    class Store:
        def submit(self, _request):
            raise AssertionError("not used")

        def status(self, _job_id):
            raise AssertionError("not used")

        def list_recent_jobs(self, **_kwargs):
            raise AssertionError("not used")

    service = CoordinatorService(Coordinator(), Store(), runtime)
    service.start(lambda: None)
    try:
        assert service.socket_path.name == "coordinator.endpoint.json"
        health = LocalCoordinatorClient(
            service.socket_path, service.token_path, timeout_seconds=2
        ).health()
        assert health["status"] == "ready"
        assert health["health_schema_version"] == 1
    finally:
        service.stop()
    assert not service.socket_path.exists()


def test_job_object_contains_non_cooperative_worker_and_descendant():
    result = run_synthetic_worker(
        "non_cooperative_cancellation",
        {"job_id": "native-job-1", "attempt": 1},
        DEFAULT_LIMITS,
    )

    assert result.supervision_kind == "windows_job_object"
    assert result.terminated is True
    assert result.killed is True
    assert result.process_group_cleaned is True
    assert result.waited is True


def test_foreground_worker_argv_is_exact_and_does_not_use_shell(tmp_path: Path):
    marker = tmp_path / "argv-marker"
    process = launch_managed_process(
        (sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"),
        {
            "PATH": os.environ.get("PATH", ""),
            "SystemRoot": os.environ.get("SystemRoot", ""),
        },
        tmp_path,
    )
    assert process.supervision_kind == "windows_job_object"
    assert isinstance(process.popen, subprocess.Popen)
    assert isinstance(process.popen.args, tuple)
    assert process.popen.args[0] == sys.executable
    assert process.popen.args[1:2] == ("-c",)
    assert process.cleanup(2, 2) is True


def test_windows_psql_contract_requires_explicit_exe_name(tmp_path: Path, monkeypatch):
    psql = tmp_path / "psql.exe"
    psql.write_text("native-test", encoding="utf-8")
    monkeypatch.setattr(
        "repomap_kg.coordinator.local_mode.validate_psql", lambda _path: None
    )
    assert psql.name.lower() == "psql.exe"
    assert _resolve_psql_executable(psql, platform_name="nt") == psql.resolve()
