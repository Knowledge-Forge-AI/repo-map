from __future__ import annotations


OPS_RUNTIME_EXPORTS = {
    "ops_refresh": (
        "common_lore_index.ops_refresh",
        "common_lore_index.ops.refresh",
        "refresh_graph",
    ),
    "ops_preflight": (
        "common_lore_index.ops_refresh",
        "common_lore_index.ops.refresh",
        "preflight_graph",
    ),
    "ops_baseline_save": (
        "common_lore_index.ops_refresh",
        "common_lore_index.ops.refresh",
        "save_graph_baselines",
    ),
    "ops_drift": (
        "common_lore_index.ops_refresh",
        "common_lore_index.ops.refresh",
        "query_drift_check",
    ),
    "runtime_setup": (
        "common_lore_index.local_runtime",
        "common_lore_index.runtime.local",
        "setup_local_runtime",
    ),
    "runtime_status": (
        "common_lore_index.local_runtime",
        "common_lore_index.runtime.local",
        "query_local_runtime_status",
    ),
    "runtime_identity": (
        "common_lore_index.local_runtime",
        "common_lore_index.runtime.plan",
        "LocalRuntimeIdentity",
    ),
    "runtime_dockerfile": (
        "common_lore_index.local_runtime",
        "common_lore_index.runtime.commands",
        "render_server_dockerfile",
    ),
}


ROOT_FACADE_MODULES = {
    "common_lore_index.ops_refresh": "common_lore_index.ops.refresh",
    "common_lore_index.local_runtime": "common_lore_index.runtime.local",
}


def test_pkg4_root_facades_export_package_symbols() -> None:
    import common_lore_index.ops_refresh as root_ops_refresh
    import common_lore_index.local_runtime as root_local_runtime
    import common_lore_index.ops.refresh as pkg_ops_refresh
    import common_lore_index.runtime.local as pkg_runtime_local
    import common_lore_index.runtime.plan as pkg_runtime_plan
    import common_lore_index.runtime.commands as pkg_runtime_commands

    module_map = {
        "common_lore_index.ops_refresh": root_ops_refresh,
        "common_lore_index.local_runtime": root_local_runtime,
        "common_lore_index.ops.refresh": pkg_ops_refresh,
        "common_lore_index.runtime.local": pkg_runtime_local,
        "common_lore_index.runtime.plan": pkg_runtime_plan,
        "common_lore_index.runtime.commands": pkg_runtime_commands,
    }

    for root_name, package_name, symbol_name in OPS_RUNTIME_EXPORTS.values():
        root_module = module_map[root_name]
        package_module = module_map[package_name]

        assert getattr(root_module, symbol_name) is getattr(package_module, symbol_name)


def test_pkg4_root_facades_alias_package_modules_for_patch_targets() -> None:
    import common_lore_index.ops_refresh as ops_refresh
    import common_lore_index.local_runtime as local_runtime
    import common_lore_index.ops.refresh as ops_pkg_refresh
    import common_lore_index.runtime.local as runtime_pkg_local

    module_map = {
        "common_lore_index.ops_refresh": ops_refresh,
        "common_lore_index.local_runtime": local_runtime,
        "common_lore_index.ops.refresh": ops_pkg_refresh,
        "common_lore_index.runtime.local": runtime_pkg_local,
    }

    for root_name, package_name in ROOT_FACADE_MODULES.items():
        assert module_map[root_name] is module_map[package_name]


def test_pkg4_existing_patch_targets_remain_reachable() -> None:
    import common_lore_index.ops_refresh as ops_refresh
    import common_lore_index.local_runtime as local_runtime
    import common_lore_index.runtime.backup as local_db_backup
    import common_lore_index.ops.config as ops_config
    import common_lore_index.runtime.backup_manifests as backup_manifests
    import common_lore_index.server.mcp_core as server_mcp_core

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
    import common_lore_index.cli as cli
    import common_lore_index.server.ops as mcp_ops
    import common_lore_index.server.memory_bridge as server_memory_bridge
    import common_lore_index.server.http as local_server

    import common_lore_index.ops.config as ops_config
    import common_lore_index.ops.refresh as ops_refresh
    import common_lore_index.runtime.local as runtime_local
    import common_lore_index.runtime.backup as runtime_backup

    assert getattr(cli, "LocalDbBackupError") is getattr(runtime_backup, "LocalDbBackupError")
    assert getattr(cli, "setup_local_runtime") is getattr(runtime_local, "setup_local_runtime")
    assert getattr(cli, "OpsConfigError") is getattr(ops_config, "OpsConfigError")
    assert getattr(cli, "OpsRefreshError") is getattr(ops_refresh, "OpsRefreshError")
    assert mcp_ops.query_refresh_status is ops_refresh.query_refresh_status
    assert server_memory_bridge.load_ops_config is ops_config.load_ops_config
    assert local_server.load_ops_config_home is ops_config.load_ops_config_home
