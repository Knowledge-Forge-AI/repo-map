"""SCALE28-FIX12-DIAG1 — no-hidden-psql contract for Psycopg-selected reads.

The phase question is whether a runtime path the operator selected for Psycopg
can execute psql. It can: ``execute_ops_json_readback`` in
``host_then_container`` mode responds to a class-08 psycopg connection failure
by retrying through the container topology, and that retry runs
``<container-runtime> exec -i <container> psql ...``.

The invocation is nested: ``argv[0]`` is the container runtime, so a poison
``psql`` on ``PATH`` is never reached and a PATH-only test reports a clean run.
Detection here inspects the whole argv.

These tests characterize behavior only. No production change is made in this
phase; see docs/status/2026/07/28/00685.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import repomap_kg.runtime.local as runtime_local
import repomap_kg.storage.readback_driver as storage_readback
from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.storage import StorageSchemaError
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG
from repomap_test_support.process_boundary import (
    PsqlInvokedError,
    RecordingProcessBoundary,
    poison_psql_directory,
)


@pytest.fixture(autouse=True)
def _select_psycopg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every case below runs with Psycopg explicitly selected."""
    monkeypatch.setenv(storage_readback.PG_CONNECTOR_ENV, "psycopg")
    monkeypatch.delenv(storage_readback.READBACK_DRIVER_ENV, raising=False)


def _container_internal_config(tmp_path: Path):
    home = tmp_path / "home"
    root = tmp_path / "repo"
    home.mkdir(parents=True)
    root.mkdir()
    (home / "repomap.rpl.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=root, private_root=root / "private")
        + "\n[runtime]\n"
        + 'container_runtime = "docker"\n'
        + "server_host_port = 55880\n"
        + "\n[runtime.postgres]\n"
        + "direct_host_port_enabled = false\n",
        encoding="utf-8",
    )
    return load_ops_config_home(home)


def _psycopg_connection_failure() -> StorageSchemaError:
    """A class-08 psycopg failure: what an unreachable backend looks like."""
    cause_type = type(
        "OperationalError", (Exception,), {"__module__": "psycopg.errors"}
    )
    cause = cause_type("connection failed")
    cause.sqlstate = "08006"
    try:
        raise cause
    except Exception as error:
        try:
            raise StorageSchemaError(
                "psycopg readback failed for operations status"
            ) from error
        except StorageSchemaError as wrapped:
            return wrapped


def _arrange(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Fail the psycopg attempt; let the product's own topology planning run."""
    import repomap_kg.ops.readback as readback
    real_dispatch = readback.execute_json_readback_with_driver

    def dispatch(sql: str, **kwargs: Any):
        if kwargs.get("driver") == "psycopg":
            raise _psycopg_connection_failure()
        return real_dispatch(sql, **kwargs)

    monkeypatch.setattr(readback, "execute_json_readback_with_driver", dispatch)

    class _RunningOwnedContainer:
        exists = True
        owned = True
        status = "running"

    monkeypatch.setattr(
        runtime_local, "inspect_container", lambda *a, **k: _RunningOwnedContainer()
    )
    monkeypatch.setattr(
        readback.shutil, "which", lambda name: f"/usr/local/bin/{name}"
    )

    # PATH poisoning is the weaker of the two detectors and is installed only
    # so its inadequacy is demonstrated rather than assumed: it never fires.
    poison = poison_psql_directory(tmp_path / "poison")
    monkeypatch.setenv("PATH", f"{poison.parent}{os.pathsep}{os.environ['PATH']}")
    return readback, _container_internal_config(tmp_path)


def _read(readback, config, mode: str) -> None:
    readback.execute_ops_json_readback(
        config,
        database="repomap_repo_map",
        sql="SELECT 1",
        label="operations status",
        expected_shape="object",
        mode=mode,
    )


def test_psycopg_selected_success_creates_no_host_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import repomap_kg.ops.readback as readback
    config = _container_internal_config(tmp_path)
    monkeypatch.setattr(
        readback,
        "execute_json_readback_with_driver",
        lambda *_args, **_kwargs: {"status": "ok"},
    )
    boundary = RecordingProcessBoundary().install(monkeypatch)

    result = readback.execute_ops_json_readback(
        config,
        database="repomap_repo_map",
        sql="SELECT 1",
        label="operations status",
        expected_shape="object",
        mode="host_then_container",
    )

    assert result == {"status": "ok"}
    assert boundary.host_process_count == 0
    assert boundary.nested_psql_intent_count == 0


def test_explicit_psql_selected_container_fallback_invokes_psql(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The named compatibility driver retains its visible topology fallback."""
    readback, config = _arrange(monkeypatch, tmp_path)
    monkeypatch.setenv(storage_readback.PG_CONNECTOR_ENV, "psql")
    monkeypatch.setenv(storage_readback.READBACK_DRIVER_ENV, "psql")
    prior_dispatch = readback.execute_json_readback_with_driver

    def dispatch(sql: str, **kwargs: Any):
        if (
            kwargs.get("driver") == "psql"
            and kwargs.get("psql_command") == "psql"
        ):
            raise StorageSchemaError("could not connect to explicit psql host")
        return prior_dispatch(sql, **kwargs)

    monkeypatch.setattr(readback, "execute_json_readback_with_driver", dispatch)
    boundary = RecordingProcessBoundary(fail_closed_on_psql=True)
    boundary.install(monkeypatch)

    with pytest.raises(PsqlInvokedError):
        _read(readback, config, "host_then_container")

    assert boundary.nested_psql_intent_count == 1
    invocation = next(
        i for i in boundary.invocations if i.contains_nested_psql_intent
    )
    assert invocation.host_executable_basename == "docker"
    assert invocation.nested_psql_token_positions[0] > 0
    assert invocation.host_process_class == "container_runtime"
    assert boundary.host_psql_process_count == 0


def test_diag1_host_only_psycopg_failure_never_invokes_psql(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Control: the same failure under host_only stays on the Psycopg category."""
    readback, config = _arrange(monkeypatch, tmp_path)
    boundary = RecordingProcessBoundary(fail_closed_on_psql=True)
    boundary.install(monkeypatch)

    with pytest.raises(StorageSchemaError) as raised:
        _read(readback, config, "host_only")

    assert "psycopg" in str(raised.value)
    assert boundary.nested_psql_intent_count == 0
    assert boundary.host_psql_process_count == 0


def test_diag1_no_psycopg_runtime_path_may_invoke_psql(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A Psycopg failure is fail-closed and retains topology guidance."""
    readback, config = _arrange(monkeypatch, tmp_path)
    boundary = RecordingProcessBoundary(fail_closed_on_psql=False)
    boundary.install(monkeypatch)

    with pytest.raises(StorageSchemaError) as raised:
        _read(readback, config, "host_then_container")

    assert "psycopg connection failed" in str(raised.value)
    assert "Start the local runtime" in str(raised.value)
    assert boundary.host_process_count == 0
    assert boundary.nested_psql_intent_count == 0
