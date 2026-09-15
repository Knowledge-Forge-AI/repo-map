from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict
import pytest
import repomap_kg.ops.readback as readback
import repomap_kg.runtime.local as runtime_local
import repomap_kg.storage.readback_driver as storage_readback
from repomap_kg.ops.config import OpsConfig, load_ops_config_home
from repomap_kg.storage import StorageSchemaError
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG

class _ReadbackExecutionCall(TypedDict):
    sql: str
    driver: storage_readback.JsonReadbackDriver
    psql_args: Sequence[str]
    psql_command: str
    label: str
    expected_shape: storage_readback.ExpectedJsonShape

class OperationalError(Exception):
    __module__ = "psycopg.errors"
    sqlstate: str | None

class DatabaseError(Exception):
    __module__ = "psycopg.errors"
    sqlstate: str | None

@pytest.fixture(autouse=True)
def _clear_connector_selectors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(storage_readback.PG_CONNECTOR_ENV, raising=False)
    monkeypatch.delenv(storage_readback.READBACK_DRIVER_ENV, raising=False)

def _internal_config(tmp_path: Path) -> OpsConfig:
    home = tmp_path / "home"
    root = tmp_path / "repo"
    home.mkdir()
    root.mkdir()
    (home / "repomap.rpl.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=root, private_root=root / "private")
        .replace('host = "127.0.0.1"', 'host = "postgres"'),
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

def _psycopg_storage_error(
    sqlstate: str | None,
    *,
    operational: bool = False,
) -> StorageSchemaError:
    cause_cls = OperationalError if operational else DatabaseError
    cause = cause_cls("private dsn password=secret")
    cause.sqlstate = sqlstate
    try:
        raise cause
    except Exception as error:
        try:
            raise StorageSchemaError("psycopg readback failed for operations status") from error
        except StorageSchemaError as wrapped:
            return wrapped

@pytest.mark.parametrize(
    "failure",
    (
        OSError("explicit command unavailable"),
        StorageSchemaError("psql failed: syntax error at or near SELECT"),
    ),
)
def test_psycopg96_explicit_command_failure_performs_zero_topology_planning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: BaseException,
) -> None:
    calls: list[_ReadbackExecutionCall] = []
    _forbid_topology(monkeypatch, readback)
    monkeypatch.setattr(
        readback,
        "selected_json_readback_driver",
        lambda: (_ for _ in ()).throw(AssertionError("selector resolved")),
    )
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
        raise failure
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute)
    with pytest.raises(StorageSchemaError):
        readback.execute_ops_json_readback(
            _internal_config(tmp_path),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_then_container",
            psql_command="/opt/bin/psql-wrapper",
        )
    assert len(calls) == 1
    assert calls[0]["driver"] == "psql"
    assert calls[0]["psql_command"] == "/opt/bin/psql-wrapper"

@pytest.mark.parametrize(
    ("driver", "failure"),
    (
        ("psql", OSError("host unavailable")),
        ("psql", StorageSchemaError("could not connect to server")),
        ("psql", StorageSchemaError("psql did not return operations status as JSON")),
        (
            "psql",
            StorageSchemaError(
                "psql did not return operations status as a JSON object"
            ),
        ),
        ("psycopg", _psycopg_storage_error("08006")),
        ("psycopg", _psycopg_storage_error(None, operational=True)),
        ("psycopg", _psycopg_storage_error("28P01")),
        ("psycopg", _psycopg_storage_error("42601")),
    ),
)
def test_psycopg96_host_only_failure_performs_zero_topology_planning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    driver: str,
    failure: BaseException,
) -> None:
    calls: list[str] = []
    _forbid_topology(monkeypatch, readback)
    monkeypatch.setattr(readback, "selected_json_readback_driver", lambda: driver)
    def execute(
        sql: str,
        *,
        driver: storage_readback.JsonReadbackDriver,
        psql_args: Sequence[str],
        psql_command: str,
        label: str,
        expected_shape: storage_readback.ExpectedJsonShape,
    ) -> storage_readback.JsonReadbackPayload:
        calls.append(driver)
        raise failure
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute)
    with pytest.raises(StorageSchemaError) as caught:
        readback.execute_ops_json_readback(
            _internal_config(tmp_path),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_only",
        )
    assert calls == [driver]
    assert "password=secret" not in str(caught.value)

@pytest.mark.parametrize(
    "failure",
    (
        StorageSchemaError('psql failed: FATAL: database "missing" does not exist'),
        StorageSchemaError("psql failed: FATAL: password authentication failed"),
        StorageSchemaError("psql failed: syntax error at or near SELECT"),
        StorageSchemaError("psql did not return operations status as JSON"),
        StorageSchemaError("psql did not return operations status as a JSON object"),
    ),
)
def test_psycopg96_ineligible_topology_mode_failure_performs_zero_planning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: StorageSchemaError,
) -> None:
    calls = 0
    _forbid_topology(monkeypatch, readback)
    monkeypatch.setattr(readback, "selected_json_readback_driver", lambda: "psql")
    def execute(sql: str, *, driver: storage_readback.JsonReadbackDriver, psql_args: Sequence[str], psql_command: str, label: str, expected_shape: storage_readback.ExpectedJsonShape) -> storage_readback.JsonReadbackPayload:
        nonlocal calls
        calls += 1
        raise failure
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute)
    with pytest.raises(StorageSchemaError):
        readback.execute_ops_json_readback(
            _internal_config(tmp_path),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_then_container",
        )
    assert calls == 1

@pytest.mark.parametrize(
    ("pg_selector", "readback_selector", "message"),
    (
        ("unsupported", None, "unsupported"),
        ("psql", "psycopg", "conflicting"),
    ),
)
def test_psycopg96_selector_failure_performs_zero_topology_planning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pg_selector: str,
    readback_selector: str | None,
    message: str,
) -> None:
    _forbid_topology(monkeypatch, readback)
    monkeypatch.setenv(storage_readback.PG_CONNECTOR_ENV, pg_selector)
    if readback_selector is not None:
        monkeypatch.setenv(storage_readback.READBACK_DRIVER_ENV, readback_selector)
    def fail_execute(sql: str, *, driver: storage_readback.JsonReadbackDriver, psql_args: Sequence[str], psql_command: str, label: str, expected_shape: storage_readback.ExpectedJsonShape) -> storage_readback.JsonReadbackPayload:
        raise AssertionError("executed")
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", fail_execute)
    with pytest.raises(StorageSchemaError, match=message):
        readback.execute_ops_json_readback(
            _internal_config(tmp_path),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_then_container",
        )

@pytest.mark.parametrize(
    ("driver_failure", "expected_hint", "expected_counts"),
    (
        (
            ("psql", OSError("host unavailable")),
            "owned-postgres",
            {"runtime_plan": 1, "which": 1, "execute": 1},
        ),
        (
            ("psycopg", _psycopg_storage_error("08006")),
            "repomap-postgres",
            {"runtime_plan": 0, "which": 0, "execute": 1},
        ),
    ),
)
def test_psycopg96_eligible_unavailable_topology_resolves_one_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    driver_failure: tuple[str, BaseException],
    expected_hint: str,
    expected_counts: dict[str, int],
) -> None:
    driver, failure = driver_failure
    counts = {"runtime_plan": 0, "which": 0, "execute": 0}
    plan = SimpleNamespace(
        container_runtime="docker",
        identity=SimpleNamespace(postgres_container="owned-postgres"),
    )
    def runtime_plan(config: OpsConfig) -> SimpleNamespace:
        counts["runtime_plan"] += 1
        return plan
    def which(command: str) -> str | None:
        counts["which"] += 1
        return None
    def execute(sql: str, *, driver: storage_readback.JsonReadbackDriver, psql_args: Sequence[str], psql_command: str, label: str, expected_shape: storage_readback.ExpectedJsonShape) -> storage_readback.JsonReadbackPayload:
        counts["execute"] += 1
        raise failure
    monkeypatch.setattr(readback, "selected_json_readback_driver", lambda: driver)
    monkeypatch.setattr(readback, "_runtime_plan", runtime_plan)
    monkeypatch.setattr(readback.shutil, "which", which)
    def fail_inspect(plan: runtime_local.LocalRuntimePlan, component: str, name: str) -> runtime_local.LocalContainerStatus:
        raise AssertionError("container inspected without runtime")
    monkeypatch.setattr(runtime_local, "inspect_container", fail_inspect)
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute)
    with pytest.raises(StorageSchemaError, match=expected_hint):
        readback.execute_ops_json_readback(
            _internal_config(tmp_path),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_then_container",
        )
    assert counts == expected_counts

@pytest.mark.parametrize(
    "status",
    (
        SimpleNamespace(exists=False, owned=False, status="missing"),
        SimpleNamespace(exists=True, owned=False, status="running"),
        SimpleNamespace(exists=True, owned=True, status="stopped"),
    ),
)
def test_psycopg96_unavailable_container_state_resolves_one_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: SimpleNamespace,
) -> None:
    counts = {"runtime_plan": 0, "which": 0, "inspect": 0, "execute": 0}
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
        return status
    def execute(sql: str, *, driver: storage_readback.JsonReadbackDriver, psql_args: Sequence[str], psql_command: str, label: str, expected_shape: storage_readback.ExpectedJsonShape) -> storage_readback.JsonReadbackPayload:
        counts["execute"] += 1
        raise OSError("host unavailable")
    monkeypatch.setattr(readback, "selected_json_readback_driver", lambda: "psql")
    monkeypatch.setattr(readback, "_runtime_plan", runtime_plan)
    monkeypatch.setattr(readback.shutil, "which", which)
    monkeypatch.setattr(runtime_local, "inspect_container", inspect)
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute)
    with pytest.raises(StorageSchemaError, match="owned-postgres"):
        readback.execute_ops_json_readback(
            _internal_config(tmp_path),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_then_container",
        )
    assert counts == {"runtime_plan": 1, "which": 1, "inspect": 1, "execute": 1}

@pytest.mark.parametrize(
    "container_failure",
    (
        OSError("container psql unavailable"),
        StorageSchemaError("psql did not return operations status as JSON"),
        StorageSchemaError("psql did not return operations status as a JSON object"),
    ),
)
def test_psycopg96_failed_container_attempt_does_not_replan_or_claim_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    container_failure: BaseException,
) -> None:
    counts = {"runtime_plan": 0, "which": 0, "inspect": 0, "execute": 0}
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
    def execute(sql: str, *, driver: storage_readback.JsonReadbackDriver, psql_args: Sequence[str], psql_command: str, label: str, expected_shape: storage_readback.ExpectedJsonShape) -> storage_readback.JsonReadbackPayload:
        counts["execute"] += 1
        if counts["execute"] == 1:
            raise OSError("host unavailable")
        raise container_failure
    monkeypatch.setattr(readback, "selected_json_readback_driver", lambda: "psql")
    monkeypatch.setattr(readback, "_runtime_plan", runtime_plan)
    monkeypatch.setattr(readback.shutil, "which", which)
    monkeypatch.setattr(runtime_local, "inspect_container", inspect)
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute)
    with pytest.raises(StorageSchemaError) as caught:
        readback.execute_ops_json_readback(
            _internal_config(tmp_path),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_then_container",
        )
    assert counts == {"runtime_plan": 1, "which": 1, "inspect": 1, "execute": 2}
    assert "no running RepoMap-owned" not in str(caught.value)
