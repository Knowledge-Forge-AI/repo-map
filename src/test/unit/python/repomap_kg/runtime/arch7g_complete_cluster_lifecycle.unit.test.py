import io
import json
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.cli import main
from repomap_kg.runtime.release_cluster import (
    GraphOperator,
    ReleaseClusterError,
    ReleaseGraphOperator,
    _backup_graph_before_upgrade,
    _runtime_password,
    initialize_release_cluster,
    release_cluster_status,
)


class _FakeGraphOperator(GraphOperator):
    databases: tuple[str, ...] = ("graph_a", "graph_b", "graph_c")
    expected_count: int = 15

    def __init__(self) -> None:
        self.exists = {"graph_a": False, "graph_b": True, "graph_c": True}
        self.states = {
            "graph_a": ("uninitialized", 0),
            "graph_b": ("behind", 14),
            "graph_c": ("current", 15),
        }
        self.events: list[tuple[str, str]] = []

    def database_exists(self, database: str) -> bool:
        return self.exists[database]

    def create_database(self, database: str) -> None:
        self.events.append(("create", database))
        self.exists[database] = True

    def schema_state(self, database: str) -> tuple[str, int]:
        return self.states[database]

    def initialize_schema(self, database: str) -> None:
        self.events.append(("initialize", database))
        self.states[database] = ("current", self.expected_count)

    def upgrade_schema(self, database: str, applied_count: int) -> None:
        assert applied_count == 14
        self.events.append(("upgrade", database))
        self.states[database] = ("current", self.expected_count)

    def reconcile_roles(self, database: str) -> None:
        self.events.append(("roles", database))

    def drop_created_database(self, database: str) -> None:
        self.events.append(("drop", database))
        self.exists[database] = False


def test_release_cluster_cleans_invocation_created_targets_after_failure() -> None:
    operator = _FakeGraphOperator()
    operator.exists["graph_b"] = False

    def fail_initialize(database: str) -> None:
        operator.events.append(("initialize", database))
        if database == "graph_b":
            raise RuntimeError("private initialization failure")
        operator.states[database] = ("current", operator.expected_count)

    setattr(operator, "initialize_schema", fail_initialize)
    control_cleanup = patch(
        "repomap_kg.runtime.release_cluster._cleanup_created_control"
    )

    with control_cleanup as cleanup_control:
        with pytest.raises(
            ReleaseClusterError,
            match="release_cluster_initialization_failed",
        ):
            initialize_release_cluster(
                "/repo-map-home",
                operator_factory=lambda _home: operator,
                control_initializer=lambda _home: {
                    "result": "ready",
                    "database_created": True,
                },
                control_cleanup=cleanup_control,
            )

    assert operator.events == [
        ("create", "graph_a"),
        ("initialize", "graph_a"),
        ("create", "graph_b"),
        ("initialize", "graph_b"),
        ("drop", "graph_b"),
        ("drop", "graph_a"),
    ]
    cleanup_control.assert_called_once_with("/repo-map-home")


def test_release_cluster_reports_bounded_cleanup_failure() -> None:
    operator = _FakeGraphOperator()

    def fail_initialize(database: str) -> None:
        operator.events.append(("initialize", database))
        raise RuntimeError("private initialization failure")

    def fail_cleanup(database: str) -> None:
        raise RuntimeError(f"private cleanup failure {database}")

    setattr(operator, "initialize_schema", fail_initialize)
    setattr(operator, "drop_created_database", fail_cleanup)

    with pytest.raises(
        ReleaseClusterError,
        match="release_cluster_cleanup_failed",
    ) as raised:
        initialize_release_cluster(
            "/repo-map-home",
            operator_factory=lambda _home: operator,
            control_initializer=lambda _home: {
                "result": "ready",
                "database_created": False,
            },
        )

    assert "private cleanup failure" not in str(raised.value)


def test_release_cluster_backup_adapter_inspects_and_publishes_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = ReleaseGraphOperator.__new__(ReleaseGraphOperator)
    setattr(operator, "plan", SimpleNamespace())
    operator.password = "synthetic-password"
    setattr(operator, "pg_dump_command", lambda database: (
        "/usr/bin/pg_dump",
        "-d",
        database,
    ))
    staging = tmp_path / ".staging"
    staging.mkdir()
    published = tmp_path / "schema-upgrades" / "synthetic" / "graph_a"
    dump = SimpleNamespace(
        name="database.dump",
        size_bytes=12,
        sha256="a" * 64,
    )

    @contextmanager
    def atomic_directory(_final: Path, *, backups_root: Path):
        assert backups_root == tmp_path
        yield staging

    monkeypatch.setenv("REPOMAP_ADMIN_ROOT", str(tmp_path))
    with (
        patch(
            "repomap_kg.runtime.release_cluster.timestamp_utc",
            return_value="synthetic",
        ),
        patch(
            "repomap_kg.runtime.release_cluster.atomic_private_backup_directory",
            side_effect=atomic_directory,
        ),
        patch(
            "repomap_kg.runtime.release_cluster.stream_pg_dump_to_file",
            return_value=dump,
        ) as stream,
        patch(
            "repomap_kg.runtime.release_cluster.subprocess.run",
            return_value=SimpleNamespace(returncode=0),
        ) as inspect,
        patch(
            "repomap_kg.runtime.release_cluster.write_private_text"
        ) as write_manifest,
    ):
        result = _backup_graph_before_upgrade(
            "/repo-map-home",
            operator,
            "graph_a",
        )

    assert result == published
    stream.assert_called_once()
    assert inspect.call_args.args[0] == (
        "/usr/bin/pg_restore",
        "-l",
        str(staging / "database.dump"),
    )
    manifest = json.loads(write_manifest.call_args.args[1])
    assert manifest == {
        "artifact": "database.dump",
        "restore_client": "/usr/bin/pg_restore",
        "schema_version": 1,
        "sha256": "a" * 64,
        "size_bytes": 12,
    }


def test_release_cluster_refuses_noncurrent_postcondition() -> None:
    operator = _FakeGraphOperator()
    operator.exists = {database: True for database in operator.databases}
    operator.states = {
        database: ("current", operator.expected_count)
        for database in operator.databases
    }
    operator.states["graph_c"] = ("current", operator.expected_count - 1)

    with pytest.raises(
        ReleaseClusterError,
        match="release_cluster_graph_not_ready",
    ):
        initialize_release_cluster(
            "/repo-map-home",
            operator_factory=lambda _home: operator,
            control_initializer=lambda _home: {
                "result": "ready",
                "database_created": False,
            },
        )


def test_release_cluster_status_is_bounded_and_identity_free() -> None:
    operator = _FakeGraphOperator()
    operator.exists["graph_a"] = True
    operator.states["graph_a"] = ("current", 15)
    operator.states["graph_b"] = ("current", 15)

    payload = release_cluster_status(
        "/repo-map-home",
        operator_factory=lambda _home: operator,
        control_status=lambda _home: {"result": "ready"},
    )

    assert payload["result"] == "ready"
    assert payload["graph_schema_ready_count"] == 3
    rendered = json.dumps(payload, sort_keys=True)
    assert "graph_a" not in rendered
    assert "graph_b" not in rendered
    assert "/repo-map-home" not in rendered


def test_release_cluster_current_init_is_idempotent() -> None:
    operator = _FakeGraphOperator()
    operator.exists = {database: True for database in operator.databases}
    operator.states = {
        database: ("current", operator.expected_count)
        for database in operator.databases
    }

    payload = initialize_release_cluster(
        "/repo-map-home",
        operator_factory=lambda _home: operator,
        control_initializer=lambda _home: {
            "result": "ready",
            "database_created": False,
        },
    )

    assert payload["graph_database_created_count"] == 0
    assert payload["graph_schema_initialized_count"] == 0
    assert payload["graph_schema_upgraded_count"] == 0
    assert payload["graph_schema_current_count"] == 3


def test_release_cluster_status_counts_missing_and_noncurrent_graphs() -> None:
    operator = _FakeGraphOperator()
    operator.states["graph_b"] = ("refused", 0)

    payload = release_cluster_status(
        "/repo-map-home",
        operator_factory=lambda _home: operator,
        control_status=lambda _home: {"result": "not_ready"},
    )

    assert payload["result"] == "not_ready"
    assert payload["control_schema_ready"] is False
    assert payload["graph_schema_ready_count"] == 1
    assert payload["graph_schema_unavailable_count"] == 2


def test_release_cluster_wraps_unexpected_init_and_status_failures() -> None:
    def fail(_home: str | Path) -> GraphOperator:
        raise RuntimeError("private failure")

    with pytest.raises(
        ReleaseClusterError,
        match="release_cluster_initialization_failed",
    ):
        initialize_release_cluster(
            "/repo-map-home",
            operator_factory=fail,
        )
    with pytest.raises(ReleaseClusterError, match="release_cluster_status_failed"):
        release_cluster_status(
            "/repo-map-home",
            operator_factory=fail,
        )


@pytest.mark.parametrize(
    "content",
    ("CUSTOM=value\n", f"REPOMAP_PG_PASSWORD={'x' * 257}\n"),
)
def test_release_cluster_rejects_missing_or_oversized_runtime_password(
    tmp_path: Path,
    content: str,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(content, encoding="utf-8")

    with pytest.raises(
        ReleaseClusterError,
        match="release_cluster_credential_unavailable",
    ):
        _runtime_password(env_file)


def test_release_cluster_cli_wires_init_and_status() -> None:
    ready = {
        "result": "ready",
        "graph_database_count": 3,
    }
    for command, target in (
        ("release-cluster-init", "initialize_release_cluster"),
        ("release-cluster-status", "release_cluster_status"),
    ):
        stdout = io.StringIO()
        with patch(f"repomap_kg.cli.{target}", return_value=ready) as operation:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "ops",
                        command,
                        "--repo-map-home",
                        "/placeholder/home",
                        "--json",
                    ]
                )

        assert exit_code == 0
        assert json.loads(stdout.getvalue()) == ready
        operation.assert_called_once_with("/placeholder/home")


def test_release_cluster_cli_failure_is_bounded() -> None:
    stderr = io.StringIO()
    with patch(
        "repomap_kg.cli.initialize_release_cluster",
        side_effect=ReleaseClusterError("release_cluster_init_failed"),
    ):
        with redirect_stderr(stderr):
            exit_code = main(
                [
                    "ops",
                    "release-cluster-init",
                    "--repo-map-home",
                    "/placeholder/home",
                ]
            )

    assert exit_code == 1
    assert stderr.getvalue() == "ERROR: release_cluster_init_failed\n"


def test_release_cluster_cli_table_reports_not_ready() -> None:
    stdout = io.StringIO()
    payload = {"result": "not_ready", "graph_database_count": 2}
    with patch(
        "repomap_kg.cli.release_cluster_status",
        return_value=payload,
    ) as status:
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "ops",
                    "release-cluster-status",
                    "--repo-map-home",
                    "/placeholder/home",
                ]
            )

    assert exit_code == 1
    assert stdout.getvalue() == (
        "RepoMap release cluster: result=not_ready graphs=2\n"
    )
    status.assert_called_once_with("/placeholder/home")
