from dataclasses import replace
from unittest.mock import patch

import pytest

from repomap_kg.ops.config_loading import load_ops_config_home
from repomap_kg.ops.config_records import OpsConfigError
from repomap_kg.ops.generations import config_generation
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.postgres_route import execution_postgres, select_postgres_route


def configured(tmp_path):
    setup_local_runtime(tmp_path)
    config = load_ops_config_home(tmp_path)
    return replace(config, runtime=replace(config.runtime, postgres=replace(
        config.runtime.postgres, direct_host_port_enabled=True, host_port=55891,
    )))


@pytest.mark.parametrize("release,enabled,home,host,port,expected", [
    (False, True, True, "postgres", 5432, ("127.0.0.1", 55891)),
    (True, True, True, "postgres", 5432, ("postgres", 5432)),
    (False, False, True, "postgres", 5432, ("postgres", 5432)),
    (False, True, False, "postgres", 5432, ("postgres", 5432)),
    (False, True, True, "remote.example.invalid", 5432, ("remote.example.invalid", 5432)),
    (False, True, True, "postgres", 5433, ("postgres", 5433)),
])
def test_execution_route_scope(tmp_path, release, enabled, home, host, port, expected):
    config = configured(tmp_path)
    config = replace(config, config_home=config.config_home if home else None,
                     postgres=replace(config.postgres, host=host, port=port),
                     runtime=replace(config.runtime, postgres=replace(
                         config.runtime.postgres, direct_host_port_enabled=enabled)))
    route = select_postgres_route(config, release_container=release)
    assert (route.host, route.port) == expected
    assert (config.postgres.host, config.postgres.port) == (host, port)


def test_marker_alone_preserves_endpoint_and_generation_inputs(tmp_path, monkeypatch):
    config = configured(tmp_path)
    graph = config.graphs[0]
    generation = config_generation(config, graph, tmp_path)
    marker = tmp_path / "release-marker"
    monkeypatch.delenv("REPOMAP_CONTAINER_INTERNAL", raising=False)
    with patch("repomap_kg.runtime.postgres_route.CONTAINER_INTERNAL_MARKER", marker):
        assert execution_postgres(config).host == "127.0.0.1"
        marker.touch()
        assert execution_postgres(config).host == "postgres"
    assert config_generation(config, graph, tmp_path) == generation
    assert config.postgres.host == "postgres"


@pytest.mark.parametrize("value", ['"unsupported"', 'true', '42', '[]', '{}'])
def test_coordinator_mode_is_closed(tmp_path, value):
    setup_local_runtime(tmp_path)
    path = tmp_path / "repomap.rpl.toml"
    path.write_text(path.read_text().replace("[runtime]", f"[runtime]\ncoordinator_mode = {value}"))
    with pytest.raises(OpsConfigError, match="coordinator_mode"):
        load_ops_config_home(tmp_path)


def test_coordinator_mode_default_and_overlay(tmp_path):
    setup_local_runtime(tmp_path)
    assert load_ops_config_home(tmp_path).runtime.coordinator_mode == "container"
    (tmp_path / "zz.rpl.toml").write_text('schema_version = 1\n[runtime]\ncoordinator_mode = "native"\n')
    config = load_ops_config_home(tmp_path)
    assert config.runtime.coordinator_mode == "native"
    assert config.runtime.to_jsonable()["coordinator_mode"] == "native"


@pytest.mark.parametrize("bind", ["localhost", "::1", "0.0.0.0", "192.0.2.1"])
def test_direct_exposure_requires_ipv4_literal(tmp_path, bind):
    setup_local_runtime(tmp_path)
    path = tmp_path / "repomap.rpl.toml"
    path.write_text(path.read_text().replace("direct_host_port_enabled = false", "direct_host_port_enabled = true").replace('bind_host = "127.0.0.1"', f'bind_host = "{bind}"'))
    with pytest.raises(OpsConfigError, match="127.0.0.1"):
        load_ops_config_home(tmp_path)


def test_host_ops_share_execution_route(tmp_path):
    from repomap_kg.ops.config_status import graph_psql_args
    from repomap_kg.ops.readback import execute_ops_json_readback
    from repomap_kg.ops._refresh_psql import _run_ops_psql, run_storage_readback_with_ops_psql
    from unittest.mock import Mock

    config = configured(tmp_path)
    assert graph_psql_args(config, config.graphs[0])[:4] == ["-h", "127.0.0.1", "-p", "55891"]
    with patch("repomap_kg.ops.readback.execute_json_readback_with_driver", return_value={}) as query:
        execute_ops_json_readback(config, database="fixture", sql="SELECT 1", label="fixture",
                                  expected_shape="object", mode="host_only", psql_command="psql")
        assert query.call_args.kwargs["psql_args"][:4] == ["-h", "127.0.0.1", "-p", "55891"]
    with patch("repomap_kg.ops._refresh_psql._dispatch_run_psql") as dispatch:
        _run_ops_psql(config, "fixture", psql_command="psql", input_text="SELECT 1")
        assert dispatch.return_value.call_args.args[0][1:5] == ["-h", "127.0.0.1", "-p", "55891"]
    readback = Mock(return_value={})
    run_storage_readback_with_ops_psql(config, "fixture", readback, psql_command="psql")
    assert readback.call_args.args[0][:4] == ["-h", "127.0.0.1", "-p", "55891"]
    assert config.postgres.host == "postgres"


def test_native_mode_omits_only_coordinator_and_its_state(tmp_path):
    from repomap_kg.runtime.plan import build_local_runtime_plan
    from repomap_kg.runtime.compose import render_compose_yaml

    setup_local_runtime(tmp_path)
    config = tmp_path / "repomap.rpl.toml"
    config.write_text(config.read_text().replace(
        "[runtime]", '[runtime]\ncoordinator_mode = "native"'
    ).replace("direct_host_port_enabled = false", "direct_host_port_enabled = true"))
    compose = render_compose_yaml(build_local_runtime_plan(tmp_path))
    assert "  coordinator:\n" not in compose
    assert "coordinator-state" not in compose
    for name in ("postgres", "init-upgrade", "http", "mcp", "lifecycle-admin"):
        assert f"  {name}:\n" in compose
    postgres = compose.split("  postgres:\n", 1)[1].split("  init-upgrade:\n", 1)[0]
    assert "      - repomap-local\n      - repomap-postgres-host" in postgres
    assert '127.0.0.1:55432:5432' in postgres
    assert compose.count("      - repomap-postgres-host") == 1
    assert "    internal: true" in compose
    assert "  repomap-postgres-host:" in compose


def test_default_container_mode_keeps_postgres_internal_only(tmp_path):
    from repomap_kg.runtime.compose import render_compose_yaml
    from repomap_kg.runtime.plan import build_local_runtime_plan

    setup_local_runtime(tmp_path)
    compose = render_compose_yaml(build_local_runtime_plan(tmp_path))
    postgres = compose.split("  postgres:\n", 1)[1].split("  init-upgrade:\n", 1)[0]
    networks = postgres.split("    networks:\n", 1)[1].split("    healthcheck:", 1)[0]
    assert networks == "      - repomap-local\n"
    assert "    ports:" not in postgres
    assert "repomap-postgres-host" not in compose
    assert "  coordinator:\n" in compose
    assert "  coordinator-state:\n" in compose
