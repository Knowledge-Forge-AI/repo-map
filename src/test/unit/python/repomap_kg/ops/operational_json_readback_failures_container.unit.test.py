from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict
import pytest
import repomap_kg.ops.readback as readback
import repomap_kg.ops.refresh as refresh
import repomap_kg.runtime.local as runtime_local
import repomap_kg.storage.readback_driver as storage_readback
from repomap_kg.ops.config import OpsConfig, load_ops_config_home
from repomap_kg.storage import StorageSchemaError
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

class _ReadbackExecutionCall(TypedDict):
    sql: str
    driver: storage_readback.JsonReadbackDriver
    psql_args: Sequence[str]
    psql_command: str
    label: str
    expected_shape: storage_readback.ExpectedJsonShape

@pytest.fixture(autouse=True)
def _clear_connector_selectors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(storage_readback.PG_CONNECTOR_ENV, raising=False)
    monkeypatch.delenv(storage_readback.READBACK_DRIVER_ENV, raising=False)

def _loopback_config(
    tmp_path: Path,
    *,
    host: str = "127.0.0.1",
    direct_host_port_enabled: bool,
) -> OpsConfig:
    home = tmp_path / "home"
    root = tmp_path / "repo"
    home.mkdir(parents=True)
    root.mkdir()
    direct_host_port = "true" if direct_host_port_enabled else "false"
    (home / "repomap.rpl.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=root, private_root=root / "private").replace(
            'host = "127.0.0.1"',
            f'host = "{host}"',
        )
        + "\n[runtime]\n"
        + 'container_runtime = "docker"\n'
        + "server_host_port = 55880\n"
        + "\n[runtime.postgres]\n"
        + f"direct_host_port_enabled = {direct_host_port}\n",
        encoding="utf-8",
    )
    return load_ops_config_home(home)

def _forbid_topology(monkeypatch: pytest.MonkeyPatch, readback_target: object = readback) -> None:
    def fail_plan(config: OpsConfig) -> None:
        raise AssertionError("topology planning occurred")
    def fail_exec(config: OpsConfig) -> None:
        raise AssertionError("topology planning occurred")
    def fail_which(cmd: str) -> None:
        raise AssertionError("topology planning occurred")
    def fail_inspect(plan: runtime_local.LocalRuntimePlan, component: str, name: str) -> None:
        raise AssertionError("topology planning occurred")
    monkeypatch.setattr(readback_target, "_runtime_plan", fail_plan)
    monkeypatch.setattr(readback_target, "_container_psql_execution", fail_exec)
    monkeypatch.setattr(readback.shutil, "which", fail_which)
    monkeypatch.setattr(runtime_local, "inspect_container", fail_inspect)

def _forbid_refresh_topology(monkeypatch: pytest.MonkeyPatch, readback_target: object = readback) -> None:
    def fail_plan(config: OpsConfig) -> None:
        raise AssertionError("refresh topology planning occurred")
    def fail_which(cmd: str) -> None:
        raise AssertionError("refresh topology planning occurred")
    def fail_inspect(plan: runtime_local.LocalRuntimePlan, component: str, name: str) -> None:
        raise AssertionError("refresh topology planning occurred")
    monkeypatch.setattr(readback_target, "_runtime_plan", fail_plan)
    monkeypatch.setattr(readback.shutil, "which", fail_which)
    monkeypatch.setattr(runtime_local, "inspect_container", fail_inspect)

@pytest.mark.parametrize("host", _LOOPBACK_HOSTS)
def test_psycopg97_loopback_host_without_direct_port_uses_one_owned_container_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    host: str,
) -> None:
    direct_host_calls: list[_ReadbackExecutionCall] = []

    with monkeypatch.context() as direct_host:
        _forbid_topology(direct_host, readback)
        direct_host.setattr(
            readback,
            "selected_json_readback_driver",
            lambda: "psql",
        )

        def direct_host_execute(
            sql: str,
            *,
            driver: storage_readback.JsonReadbackDriver,
            psql_args: Sequence[str],
            psql_command: str,
            label: str,
            expected_shape: storage_readback.ExpectedJsonShape,
        ) -> storage_readback.JsonReadbackPayload:
            direct_host_calls.append(
                {
                    "sql": sql,
                    "driver": driver,
                    "psql_args": psql_args,
                    "psql_command": psql_command,
                    "label": label,
                    "expected_shape": expected_shape,
                }
            )
            raise OSError("host unavailable")

        direct_host.setattr(
            readback,
            "execute_json_readback_with_driver",
            direct_host_execute,
        )

        with pytest.raises(StorageSchemaError):
            readback.execute_ops_json_readback(
                _loopback_config(
                    tmp_path / "direct-host",
                    host=host,
                    direct_host_port_enabled=True,
                ),
                database="repomap_repo_map",
                sql="SELECT 1",
                label="operations status",
                expected_shape="object",
                mode="host_then_container",
            )

    assert len(direct_host_calls) == 1

    calls: list[_ReadbackExecutionCall] = []
    counts = {"runtime_plan": 0, "which": 0, "inspect": 0}
    plan = SimpleNamespace(
        container_runtime="docker",
        identity=SimpleNamespace(postgres_container="owned-postgres"),
    )

    def runtime_plan(config: OpsConfig) -> SimpleNamespace:
        counts["runtime_plan"] += 1
        return plan

    def which(command: str) -> str | None:
        counts["which"] += 1
        return "/usr/bin/docker"

    def inspect(plan: runtime_local.LocalRuntimePlan, component: str, name: str) -> SimpleNamespace:
        counts["inspect"] += 1
        return SimpleNamespace(exists=True, owned=True, status="running")

    def execute(
        sql: str,
        *,
        driver: storage_readback.JsonReadbackDriver,
        psql_args: Sequence[str],
        psql_command: str,
        label: str,
        expected_shape: storage_readback.ExpectedJsonShape,
    ) -> storage_readback.JsonReadbackPayload:
        calls.append(
            {
                "sql": sql,
                "driver": driver,
                "psql_args": psql_args,
                "psql_command": psql_command,
                "label": label,
                "expected_shape": expected_shape,
            }
        )
        if len(calls) == 1:
            raise OSError("host unavailable")
        return {"connected": True}

    monkeypatch.setattr(readback, "selected_json_readback_driver", lambda: "psql")
    monkeypatch.setattr(readback, "_runtime_plan", runtime_plan)
    monkeypatch.setattr(readback.shutil, "which", which)
    monkeypatch.setattr(runtime_local, "inspect_container", inspect)
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute)

    result = readback.execute_ops_json_readback(
        _loopback_config(
            tmp_path / "container-fallback",
            host=host,
            direct_host_port_enabled=False,
        ),
        database="repomap_repo_map",
        sql="SELECT 1",
        label="operations status",
        expected_shape="object",
        mode="host_then_container",
    )

    assert result == {"connected": True}
    assert counts == {"runtime_plan": 1, "which": 1, "inspect": 1}
    assert len(calls) == 2
    assert calls[0]["psql_command"] == "psql"
    assert list(calls[1]["psql_args"][:4]) == [
        "exec",
        "-i",
        "owned-postgres",
        "psql",
    ]

@pytest.mark.parametrize("host", _LOOPBACK_HOSTS)
def test_psycopg97_refresh_container_execution_is_unavailable_for_loopback_without_direct_port(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    host: str,
) -> None:
    _forbid_refresh_topology(monkeypatch, readback)

    execution = refresh._container_psql_execution(
        _loopback_config(
            tmp_path,
            host=host,
            direct_host_port_enabled=False,
        )
    )

    assert execution is None


