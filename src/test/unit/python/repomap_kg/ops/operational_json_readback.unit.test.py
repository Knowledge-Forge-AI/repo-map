import importlib
import importlib.util
import inspect
from pathlib import Path
from typing import Any, cast

import pytest
import repomap_kg.storage.readback_driver as storage_readback
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.report_records import OpsPsqlExecution
from repomap_kg.storage.errors import StorageSchemaError
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG


class _RecordingConnector:
    def __init__(self, name: str) -> None:
        self.name = name
        self.capabilities = frozenset({storage_readback.JSON_READBACK_CAPABILITY})
        self.calls: list[dict[str, Any]] = []

    def execute_json(self, sql: str, **kwargs: Any) -> dict[str, str]:
        self.calls.append({"sql": sql, **kwargs})
        return {"driver": self.name}


@pytest.fixture(autouse=True)
def _clear_connector_selectors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(storage_readback.PG_CONNECTOR_ENV, raising=False)
    monkeypatch.delenv(storage_readback.READBACK_DRIVER_ENV, raising=False)


def test_psycopg94_storage_driver_exposes_named_driver_seams() -> None:
    assert callable(storage_readback.selected_json_readback_driver)
    assert callable(storage_readback.execute_json_readback_with_driver)


@pytest.mark.parametrize(
    ("pg_connector", "readback_driver", "expected"),
    (
        (None, None, "psycopg"),
        ("psql", None, "psql"),
        (None, "psycopg", "psycopg"),
        ("psql", "psql", "psql"),
    ),
)
def test_psycopg94_selected_driver_preserves_selector_rules(
    monkeypatch: pytest.MonkeyPatch,
    pg_connector: str | None,
    readback_driver: str | None,
    expected: str,
) -> None:
    if pg_connector is not None:
        monkeypatch.setenv(storage_readback.PG_CONNECTOR_ENV, pg_connector)
    if readback_driver is not None:
        monkeypatch.setenv(storage_readback.READBACK_DRIVER_ENV, readback_driver)
    assert storage_readback.selected_json_readback_driver() == expected


def test_psycopg94_named_driver_executes_only_requested_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    psql = _RecordingConnector("psql")
    psycopg = _RecordingConnector("psycopg")
    monkeypatch.setattr(storage_readback, "CONNECTORS", {"psql": psql, "psycopg": psycopg})
    payload = storage_readback.execute_json_readback_with_driver(
        "SELECT json_build_object('ok', true);",
        driver="psql",
        psql_args=("-d", "postgres"),
        psql_command="/bin/psql",
        label="operations status",
        expected_shape="object",
    )
    assert payload == {"driver": "psql"}
    assert len(psql.calls) == 1
    assert psycopg.calls == []


def test_psycopg94_named_driver_rejects_unknown_driver_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _invalid_readback_driver(driver: str) -> storage_readback.JsonReadbackDriver:
        """Narrow runtime-invalid readback driver builder for negative controls."""
        return cast(storage_readback.JsonReadbackDriver, driver)

    connector = _RecordingConnector("psql")
    monkeypatch.setattr(storage_readback, "CONNECTORS", {"psql": connector})
    execute_driver = storage_readback.execute_json_readback_with_driver
    with pytest.raises(StorageSchemaError, match="unsupported storage readback driver"):
        execute_driver(
            "SELECT 1;",
            driver=_invalid_readback_driver("automatic"),
            psql_args=("-d", "postgres"),
            psql_command="psql",
            label="operations status",
            expected_shape="object",
        )
    assert connector.calls == []


def test_psycopg94_operational_adapter_exposes_exact_api() -> None:
    spec = importlib.util.find_spec("repomap_kg.ops.readback")
    assert spec is not None
    import repomap_kg.ops.readback as readback
    assert readback.OpsJsonReadbackMode == inspect.get_annotations(readback.execute_ops_json_readback, eval_str=True)["mode"]
    assert tuple(inspect.signature(readback.execute_ops_json_readback).parameters) == (
        "config", "database", "sql", "label", "expected_shape", "mode", "psql_command",
    )
    assert inspect.signature(readback.execute_ops_json_readback).parameters["psql_command"].default is None


def _config(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    config_path = tmp_path / "repomap.local.toml"
    config_path.write_text(VALID_REFRESH_CONFIG.format(repo_root=root, private_root=root / "private"), encoding="utf-8")
    return load_ops_config(config_path)


def _container_plan(readback):
    plan_exec = OpsPsqlExecution(command="docker", args_prefix=("exec", "-i", "owned-postgres", "psql"), strategy="container")
    return readback._OpsContainerReadbackPlan(execution=plan_exec, unavailable_hint="")


def test_psycopg94_explicit_command_forces_psql_and_bypasses_selectors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import repomap_kg.ops.readback as readback
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv(storage_readback.PG_CONNECTOR_ENV, "unsupported")
    monkeypatch.setattr(
        readback,
        "selected_json_readback_driver",
        lambda: (_ for _ in ()).throw(AssertionError("selector resolved")),
    )
    monkeypatch.setattr(
        readback,
        "_container_psql_execution",
        lambda config: (_ for _ in ()).throw(AssertionError("container inspected")),
    )
    def _fake_exec(sql, **kwargs):
        calls.append({"sql": sql, **kwargs})
        return {"ok": True}

    monkeypatch.setattr(readback, "execute_json_readback_with_driver", _fake_exec)
    payload = readback.execute_ops_json_readback(
        _config(tmp_path),
        database="repomap_repo_map",
        sql="SELECT 1",
        label="operations status",
        expected_shape="object",
        mode="host_then_container",
        psql_command="/opt/bin/psql-wrapper",
    )
    assert payload == {"ok": True}
    assert len(calls) == 1
    assert calls[0]["driver"] == "psql"
    assert calls[0]["psql_command"] == "/opt/bin/psql-wrapper"


def test_psycopg94_host_only_uses_selected_connector_without_container(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import repomap_kg.ops.readback as readback
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(readback, "selected_json_readback_driver", lambda: "psycopg")
    monkeypatch.setattr(
        readback, "_container_psql_execution", lambda config: (_ for _ in ()).throw(AssertionError("container inspected")),
    )
    def _fake_exec_rows(sql, **kwargs):
        calls.append({"sql": sql, **kwargs})
        return []

    monkeypatch.setattr(readback, "execute_json_readback_with_driver", _fake_exec_rows)
    payload = readback.execute_ops_json_readback(
        _config(tmp_path),
        database="repomap_repo_map",
        sql="SELECT '[]'::json",
        label="operations rows",
        expected_shape="array",
        mode="host_only",
    )
    assert payload == []
    assert len(calls) == 1
    assert calls[0]["driver"] == "psycopg"


def test_psycopg94_retryable_host_failure_uses_one_forced_psql_container_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import repomap_kg.ops.readback as readback
    calls: list[dict[str, Any]] = []

    def resolve_container_plan(config, *, allow_loopback_host: bool):
        assert allow_loopback_host is True
        return _container_plan(readback)

    monkeypatch.setattr(readback, "selected_json_readback_driver", lambda: "psql")
    monkeypatch.setattr(readback, "_resolve_container_readback_plan", resolve_container_plan)

    def execute(sql: str, **kwargs: Any):
        calls.append({"sql": sql, **kwargs})
        if len(calls) == 1:
            raise OSError("host command unavailable")
        return {"ok": True}

    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute)
    payload = readback.execute_ops_json_readback(
        _config(tmp_path),
        database="repomap_repo_map",
        sql="SELECT '{}'::json",
        label="operations status",
        expected_shape="object",
        mode="host_then_container",
    )
    assert payload == {"ok": True}
    assert [call["driver"] for call in calls] == ["psql", "psql"]
    assert calls[1]["psql_command"] == "docker"
    assert calls[1]["psql_args"][:4] == ("exec", "-i", "owned-postgres", "psql")


def _psycopg_storage_error(sqlstate: str | None, *, operational: bool = False):
    class_name = "OperationalError" if operational else "DatabaseError"
    cause_type = type(class_name, (Exception,), {"__module__": "psycopg.errors"})
    cause = cause_type("private dsn password=secret")
    cause.sqlstate = sqlstate
    try:
        raise cause
    except Exception as error:
        try:
            raise StorageSchemaError("psycopg readback failed for operations status") from error
        except StorageSchemaError as wrapped:
            return wrapped


@pytest.mark.parametrize(
    ("error", "retryable"),
    (
        (_psycopg_storage_error("08006"), True),
        (_psycopg_storage_error(None, operational=True), True),
        (_psycopg_storage_error("3D000"), False),
        (_psycopg_storage_error("28P01"), False),
        (_psycopg_storage_error("42601"), False),
    ),
)
def test_psycopg94_psycopg_failure_classification_is_structured(
    error: StorageSchemaError,
    retryable: bool,
) -> None:
    import repomap_kg.ops.readback as readback

    assert readback._host_error_supports_container_fallback(
        error,
        driver="psycopg",
    ) is retryable


def test_missing_database_errors_keep_a_distinct_typed_boundary() -> None:
    import repomap_kg.ops.readback as readback

    psycopg_error = readback._augment_host_error(
        _psycopg_storage_error("3D000"),
        driver="psycopg",
        label="operations status",
    )
    psql_error = readback._augment_host_error(
        StorageSchemaError('psql failed: FATAL: database "missing" does not exist'),
        driver="psql",
        label="operations status",
    )

    assert isinstance(psycopg_error, readback.MissingDatabaseReadbackError)
    assert isinstance(psql_error, readback.MissingDatabaseReadbackError)
    assert str(psycopg_error) == readback.MISSING_DATABASE_MESSAGE
    assert str(psql_error) == readback.MISSING_DATABASE_MESSAGE


def test_psycopg94_psycopg_public_error_does_not_leak_raw_cause() -> None:
    import repomap_kg.ops.readback as readback
    error = _psycopg_storage_error("28P01")

    public_error = readback._augment_host_error(
        error,
        driver="psycopg",
        label="operations status",
    )

    assert str(public_error) == "psycopg authentication failed for operations status"
    assert "password" not in str(public_error)
    assert "secret" not in str(public_error)


@pytest.mark.parametrize(
    "message",
    (
        "psql did not return operations status as JSON",
        "psql did not return operations status as a JSON object",
        "psql failed: FATAL: password authentication failed",
        "psql failed: syntax error at or near SELECT",
        'psql failed: FATAL: database "missing" does not exist',
    ),
)
def test_psycopg94_non_topology_psql_failures_are_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    message: str,
) -> None:
    import repomap_kg.ops.readback as readback
    monkeypatch.setattr(readback, "selected_json_readback_driver", lambda: "psql")
    monkeypatch.setattr(
        readback,
        "execute_json_readback_with_driver",
        lambda sql, **kwargs: (_ for _ in ()).throw(StorageSchemaError(message)),
    )
    monkeypatch.setattr(
        readback,
        "_container_psql_execution",
        lambda config: (_ for _ in ()).throw(AssertionError("container inspected")),
    )

    with pytest.raises(StorageSchemaError):
        readback.execute_ops_json_readback(
            _config(tmp_path),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_then_container",
        )


def test_psycopg94_container_failure_is_terminal_after_exactly_two_attempts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import repomap_kg.ops.readback as readback
    calls: list[str] = []

    def resolve_container_plan(config, *, allow_loopback_host: bool):
        assert allow_loopback_host is True
        return _container_plan(readback)

    monkeypatch.setattr(readback, "selected_json_readback_driver", lambda: "psql")
    monkeypatch.setattr(
        readback,
        "_resolve_container_readback_plan",
        resolve_container_plan,
    )

    def fail(sql: str, **kwargs: Any):
        calls.append(kwargs["psql_command"])
        if len(calls) == 1:
            raise OSError("host unavailable")
        raise StorageSchemaError("psql did not return operations status as JSON")

    monkeypatch.setattr(readback, "execute_json_readback_with_driver", fail)

    with pytest.raises(StorageSchemaError, match="did not return"):
        readback.execute_ops_json_readback(
            _config(tmp_path),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_then_container",
        )

    assert calls == ["psql", "docker"]


def test_psycopg94_selector_failure_prevents_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import repomap_kg.ops.readback as readback
    monkeypatch.setenv(storage_readback.PG_CONNECTOR_ENV, "psql")
    monkeypatch.setenv(storage_readback.READBACK_DRIVER_ENV, "psycopg")
    monkeypatch.setattr(
        readback,
        "execute_json_readback_with_driver",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("executed")),
    )

    with pytest.raises(StorageSchemaError, match="conflicting"):
        readback.execute_ops_json_readback(
            _config(tmp_path),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_only",
        )
