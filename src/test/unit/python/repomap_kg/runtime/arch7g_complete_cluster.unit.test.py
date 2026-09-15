import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.coordinator.limits import DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS
from repomap_kg.ops.config_loading import load_ops_config_home
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.release_cluster import (
    GraphOperator,
    ReleaseClusterError,
    _initialize_or_upgrade_control,
    initialize_release_cluster,
)
def _service(compose: str, name: str, next_name: str | None) -> str:
    start = compose.index(f"  {name}:\n")
    if next_name is None:
        return compose[start:]
    return compose[start : compose.index(f"  {next_name}:\n", start + 1)]


def test_compose_declares_complete_health_gated_cluster() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / "home"
        setup_local_runtime(home)
        compose = (home / "runtime/compose.yaml").read_text(encoding="utf-8")

    for service in (
        "postgres",
        "init-upgrade",
        "http",
        "mcp",
        "coordinator",
        "lifecycle-admin",
    ):
        assert f"  {service}:\n" in compose
    assert 'POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=C"' in compose
    assert 'test: ["CMD", "/usr/bin/pg_isready"' in compose
    assert "condition: service_healthy" in compose
    assert compose.count("condition: service_completed_successfully") >= 4
    assert 'command: ["ops", "release-cluster-init"' in compose
    assert 'command: ["ops", "release-cluster-status"' in compose
    assert 'command: ["mcp", "serve"' in compose
    assert 'command: ["ops", "coordinator-serve"' in compose
    assert '"--service-package-psql", "/usr/lib/postgresql/16/bin/psql"' in compose
    assert "stdin_open: true" in compose
    assert "profiles: [\"integration\"]" in compose
    assert "profiles: [\"admin\"]" in compose
    assert compose.count("REPOMAP_PG_USER: repomap_read_status") == 2
    assert "internal: true" in compose
    assert "repomap-http:" in compose
    assert "-http\n" in compose
    coordinator = _service(compose, "coordinator", "lifecycle-admin")
    assert (
        f"start_period: {DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS}s"
        in coordinator
    )
    assert (
        f'"--startup-wait-seconds", "{DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS}"'
        in coordinator
    )


def test_long_running_units_are_read_only_and_admin_mounts_are_one_shot_only() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / "home"
        setup_local_runtime(home)
        compose = (home / "runtime/compose.yaml").read_text(encoding="utf-8")

    http = _service(compose, "http", "mcp")
    mcp = _service(compose, "mcp", "coordinator")
    coordinator = _service(compose, "coordinator", "lifecycle-admin")
    init_upgrade = _service(compose, "init-upgrade", "http")
    lifecycle = _service(compose, "lifecycle-admin", None)

    for service in (http, mcp, coordinator):
        assert "read_only: true" in service
        assert "cap_drop:\n      - ALL" in service
        assert "no-new-privileges:true" in service
        assert "admin-state:/repo-map-admin" not in service
    assert "coordinator-state:/repo-map-home/coordinator" in coordinator
    assert "coordinator-state:/repo-map-home/coordinator" not in http
    assert "coordinator-state:/repo-map-home/coordinator" not in mcp
    assert "admin-state:/repo-map-admin" in init_upgrade
    assert "admin-state:/repo-map-admin" in lifecycle
    assert "runtime/.env" not in http
    assert "runtime/.env" not in mcp
    assert "PGPASSWORD:" in http
    assert "PGPASSWORD:" in mcp
    assert "runtime/.env" not in coordinator
    assert "runtime/.env" in init_upgrade
    assert "runtime/.env" in lifecycle
    assert "REPOMAP_READ_STATUS_PASSWORD:" in coordinator
    assert "REPOMAP_REFRESH_PUBLICATION_PASSWORD:" in coordinator
    assert "REPOMAP_COORDINATOR_CONTROL_PASSWORD:" in coordinator
    assert "REPOMAP_PG_PASSWORD:" not in coordinator


def test_release_image_prepares_owner_private_container_state_roots() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / "home"
        setup_local_runtime(home)
        dockerfile = (home / "runtime/repomap-server.Dockerfile").read_text(
            encoding="utf-8"
        )

    assert "install -d -m 0700 /repo-map-home" in dockerfile
    assert "/repo-map-home/runtime /repo-map-home/coordinator /repo-map-admin" in dockerfile


def test_ambient_database_user_does_not_override_config_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / "home"
        setup_local_runtime(home)
        configured = load_ops_config_home(home)
        monkeypatch.setenv("REPOMAP_PG_USER", "repomap_read_status")
        reloaded = load_ops_config_home(home)

    assert configured.postgres.user == "repomap"
    assert reloaded.postgres.user == configured.postgres.user


def test_enabled_source_root_is_read_only_only_where_execution_requires_it() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir) / "home"
        source = home / "source"
        source.mkdir(parents=True)
        setup_local_runtime(home)
        config = home / "repomap.rpl.toml"
        config.write_text(
            config.read_text(encoding="utf-8")
            .replace('root_path = "./repo-map"', f'root_path = "{source}"')
            .replace("enabled = false", "enabled = true"),
            encoding="utf-8",
        )
        setup_local_runtime(home)
        compose = (home / "runtime/compose.yaml").read_text(encoding="utf-8")

    http = _service(compose, "http", "mcp")
    mcp = _service(compose, "mcp", "coordinator")
    coordinator = _service(compose, "coordinator", "lifecycle-admin")
    lifecycle = _service(compose, "lifecycle-admin", None)
    resolved_source = source.resolve()
    mount_source = f'source: "{resolved_source}"'
    mount_target = f'target: "{resolved_source}"'

    assert mount_source in coordinator
    assert mount_target in coordinator
    assert "read_only: true" in coordinator
    assert mount_source in lifecycle
    assert mount_source not in http
    assert mount_source not in mcp


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


class _FakeAuthority:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events

    @contextmanager
    def maintenance_window(self, *, graph_databases: tuple[str, ...]):
        assert graph_databases == ("graph_b",)
        self.events.append(("maintenance", "enter"))
        yield
        self.events.append(("maintenance", "exit"))


def test_release_cluster_initializes_and_backup_first_upgrades_exact_topology() -> None:
    operator = _FakeGraphOperator()

    def backup(_home: str | Path, _operator: object, database: str) -> None:
        operator.events.append(("backup", database))

    payload = initialize_release_cluster(
        "/repo-map-home",
        operator_factory=lambda _home: operator,
        control_initializer=lambda _home: {
            "result": "ready",
            "database_created": True,
        },
        authority_factory=lambda _home: _FakeAuthority(operator.events),
        backup_function=backup,
    )

    assert payload == {
        "command": "release-cluster-init",
        "result": "ready",
        "control_created": True,
        "graph_database_count": 3,
        "graph_database_created_count": 1,
        "graph_schema_initialized_count": 1,
        "graph_schema_upgraded_count": 1,
        "graph_schema_current_count": 1,
        "backup_first_upgrade_count": 1,
    }
    assert operator.events.index(("backup", "graph_b")) < operator.events.index(
        ("upgrade", "graph_b")
    )
    assert operator.events.count(("roles", "graph_a")) == 1
    assert operator.events.count(("roles", "graph_b")) == 1
    assert operator.events.count(("roles", "graph_c")) == 1


def test_release_control_preledger_is_backup_first_upgraded() -> None:
    store = SimpleNamespace(
        schema_readiness=lambda: SimpleNamespace(
            status=SimpleNamespace(value="preledger")
        )
    )
    authority = SimpleNamespace(
        database_exists=lambda: True,
        control_store=lambda: store,
    )
    with (
        patch(
            "repomap_kg.runtime.release_cluster.LocalControlAuthority",
            return_value=authority,
        ),
        patch("repomap_kg.runtime.release_cluster.ReleaseGraphOperator"),
        patch(
            "repomap_kg.runtime.release_cluster.upgrade_coordinator_control",
            return_value={"result": "ready", "schema_before": "supported-preledger"},
        ) as upgrade,
    ):
        payload = _initialize_or_upgrade_control("/repo-map-home")

    assert payload["result"] == "ready"
    kwargs = upgrade.call_args.kwargs
    assert kwargs["backup_first"] is True
    assert kwargs["confirmed"] is True
    assert kwargs["dry_run"] is False
    assert callable(kwargs["dump_function"])
    assert callable(kwargs["inspect_function"])
    with pytest.raises(
        ReleaseClusterError,
        match="release_cluster_control_backup_unverified",
    ):
        kwargs["inspect_function"](
            "/repo-map-home",
            Path("/repo-map-admin/schema-upgrades/unverified"),
        )
    with patch(
        "repomap_kg.runtime.release_cluster._backup_graph_before_upgrade",
        return_value=Path("/repo-map-admin/schema-upgrades/synthetic"),
    ) as backup:
        receipt = kwargs["dump_function"](
            "/repo-map-home",
            database="repomap_control",
        )
        inspection = kwargs["inspect_function"](
            "/repo-map-home",
            receipt.plan.backup_path,
        )
    assert inspection.checksum_verified is True
    assert inspection.manifest == {"restore_supported": True}
    backup.assert_called_once()


@pytest.mark.parametrize(
    ("database_exists", "readiness"),
    ((False, "unavailable"), (True, "current")),
)
def test_release_control_fresh_and_current_paths_use_idempotent_initializer(
    database_exists: bool,
    readiness: str,
) -> None:
    authority = SimpleNamespace(
        database_exists=lambda: database_exists,
        control_store=lambda: SimpleNamespace(
            schema_readiness=lambda: SimpleNamespace(
                status=SimpleNamespace(value=readiness)
            )
        ),
    )
    with (
        patch(
            "repomap_kg.runtime.release_cluster.LocalControlAuthority",
            return_value=authority,
        ),
        patch(
            "repomap_kg.runtime.release_cluster.initialize_coordinator_control",
            return_value={"result": "ready"},
        ) as initialize,
    ):
        payload = _initialize_or_upgrade_control("/repo-map-home")

    assert payload["result"] == "ready"
    initialize.assert_called_once()


def test_release_cluster_refuses_unmanaged_graph_schema() -> None:
    operator = _FakeGraphOperator()
    operator.states["graph_c"] = ("refused", 0)
    control_initializer = patch(
        "repomap_kg.runtime.release_cluster._initialize_or_upgrade_control"
    )

    with control_initializer as initialize_control:
        with pytest.raises(
            ReleaseClusterError,
            match="release_cluster_graph_schema_refused",
        ):
            initialize_release_cluster(
                "/repo-map-home",
                operator_factory=lambda _home: operator,
                control_initializer=initialize_control,
                backup_function=lambda _home, _operator, _database: None,
            )

    initialize_control.assert_not_called()
    assert operator.events == []


def test_release_cluster_refuses_preexisting_empty_database_without_adoption() -> None:
    operator = _FakeGraphOperator()
    operator.exists["graph_a"] = True
    control_initializer = patch(
        "repomap_kg.runtime.release_cluster._initialize_or_upgrade_control"
    )

    with control_initializer as initialize_control:
        with pytest.raises(
            ReleaseClusterError,
            match="release_cluster_graph_adoption_refused",
        ):
            initialize_release_cluster(
                "/repo-map-home",
                operator_factory=lambda _home: operator,
                control_initializer=initialize_control,
            )

    initialize_control.assert_not_called()
    assert operator.events == []
