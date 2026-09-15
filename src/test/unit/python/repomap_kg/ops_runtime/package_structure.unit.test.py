from __future__ import annotations


OPS_RUNTIME_EXPORTS = {
    "ops_refresh": (
        "repomap_kg.ops_refresh",
        "repomap_kg.ops.refresh",
        "refresh_graph",
    ),
    "ops_preflight": (
        "repomap_kg.ops_refresh",
        "repomap_kg.ops.refresh",
        "preflight_graph",
    ),
    "ops_baseline_save": (
        "repomap_kg.ops_refresh",
        "repomap_kg.ops.refresh",
        "save_graph_baselines",
    ),
    "ops_drift": (
        "repomap_kg.ops_refresh",
        "repomap_kg.ops.refresh",
        "query_drift_check",
    ),
    "runtime_setup": (
        "repomap_kg.local_runtime",
        "repomap_kg.runtime.local",
        "setup_local_runtime",
    ),
    "runtime_status": (
        "repomap_kg.local_runtime",
        "repomap_kg.runtime.local",
        "query_local_runtime_status",
    ),
    "runtime_identity": (
        "repomap_kg.local_runtime",
        "repomap_kg.runtime.plan",
        "LocalRuntimeIdentity",
    ),
    "runtime_dockerfile": (
        "repomap_kg.local_runtime",
        "repomap_kg.runtime.commands",
        "render_server_dockerfile",
    ),
}


ROOT_FACADE_MODULES = {
    "repomap_kg.ops_refresh": "repomap_kg.ops.refresh",
    "repomap_kg.local_runtime": "repomap_kg.runtime.local",
}


def test_pkg4_root_facades_export_package_symbols() -> None:
    import repomap_kg.ops_refresh as root_ops_refresh
    import repomap_kg.local_runtime as root_local_runtime
    import repomap_kg.ops.refresh as pkg_ops_refresh
    import repomap_kg.runtime.local as pkg_runtime_local
    import repomap_kg.runtime.plan as pkg_runtime_plan
    import repomap_kg.runtime.commands as pkg_runtime_commands

    module_map = {
        "repomap_kg.ops_refresh": root_ops_refresh,
        "repomap_kg.local_runtime": root_local_runtime,
        "repomap_kg.ops.refresh": pkg_ops_refresh,
        "repomap_kg.runtime.local": pkg_runtime_local,
        "repomap_kg.runtime.plan": pkg_runtime_plan,
        "repomap_kg.runtime.commands": pkg_runtime_commands,
    }

    for root_name, package_name, symbol_name in OPS_RUNTIME_EXPORTS.values():
        root_module = module_map[root_name]
        package_module = module_map[package_name]

        assert getattr(root_module, symbol_name) is getattr(package_module, symbol_name)


def test_pkg4_root_facades_alias_package_modules_for_patch_targets() -> None:
    import repomap_kg.ops_refresh as ops_refresh
    import repomap_kg.local_runtime as local_runtime
    import repomap_kg.ops.refresh as ops_pkg_refresh
    import repomap_kg.runtime.local as runtime_pkg_local

    module_map = {
        "repomap_kg.ops_refresh": ops_refresh,
        "repomap_kg.local_runtime": local_runtime,
        "repomap_kg.ops.refresh": ops_pkg_refresh,
        "repomap_kg.runtime.local": runtime_pkg_local,
    }

    for root_name, package_name in ROOT_FACADE_MODULES.items():
        assert module_map[root_name] is module_map[package_name]


def test_pkg4_existing_patch_targets_remain_reachable() -> None:
    import repomap_kg.ops_refresh as ops_refresh
    import repomap_kg.local_runtime as local_runtime
    import repomap_kg.runtime.backup as local_db_backup
    import repomap_kg.ops.config as ops_config
    import repomap_kg.runtime.backup_manifests as backup_manifests
    import repomap_kg.server.mcp_core as server_mcp_core

    assert callable(getattr(ops_refresh, "run_psql"))
    assert callable(getattr(local_runtime, "inspect_container"))
    assert callable(getattr(ops_refresh, "discover_observations"))
    assert not hasattr(ops_refresh, "load_file_observations")
    assert callable(getattr(local_runtime, "shutil").which)
    assert callable(getattr(local_runtime, "subprocess").run)
    assert hasattr(getattr(local_runtime, "urllib").request, "urlopen")
    assert callable(getattr(local_runtime, "is_local_port_open"))
    assert callable(local_db_backup.subprocess.run)
    assert callable(local_db_backup.discover_migrations)
    assert callable(local_db_backup.write_manifest_and_restore_docs)
    assert callable(backup_manifests.select_dump_file_for_database)
    assert callable(backup_manifests.write_manifest_and_restore_docs)
    assert callable(server_mcp_core.validate_source_id_arg)
    assert callable(ops_config.run_psql)


def test_pkg4_cli_and_mcp_route_to_package_symbols() -> None:
    import repomap_kg.cli as cli
    import repomap_kg.server.ops as mcp_ops
    import repomap_kg.server.memory_bridge as server_memory_bridge
    import repomap_kg.server.http as local_server

    import repomap_kg.ops.config as ops_config
    import repomap_kg.ops.refresh as ops_refresh
    import repomap_kg.runtime.local as runtime_local
    import repomap_kg.runtime.backup as runtime_backup

    assert getattr(cli, "LocalDbBackupError") is getattr(runtime_backup, "LocalDbBackupError")
    assert getattr(cli, "setup_local_runtime") is getattr(runtime_local, "setup_local_runtime")
    assert getattr(cli, "OpsConfigError") is getattr(ops_config, "OpsConfigError")
    assert getattr(cli, "OpsRefreshError") is getattr(ops_refresh, "OpsRefreshError")
    assert mcp_ops.query_refresh_status is ops_refresh.query_refresh_status
    assert server_memory_bridge.load_ops_config is ops_config.load_ops_config
    assert local_server.load_ops_config_home is ops_config.load_ops_config_home
