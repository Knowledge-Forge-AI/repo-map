from dataclasses import replace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from repomap_test_support.ops_mcp_validation_cases import assert_mcp_validation_cases


from repomap_kg.runtime import backup as local_db_backup
from repomap_kg.runtime import backup_commands
from repomap_kg.runtime import backup_manifests
from repomap_kg.runtime import local as local_runtime
from repomap_kg.server import ops as mcp_ops
from repomap_kg.ops import config as ops_config
from repomap_kg.ops import refresh as ops_refresh


class OpsRuntimeBackupMcpHelperBranchContract(unittest.TestCase):
    __test__ = False

    def test_ops_runtime_backup_and_mcp_helpers_cover_safe_branch_matrices(self):
        self.assertEqual(ops_refresh._int_or_zero(True), 1)
        self.assertEqual(ops_refresh._int_or_zero(False), 0)
        self.assertEqual(ops_refresh._int_or_zero(7), 7)
        self.assertEqual(ops_refresh._int_or_zero(None), 0)
        self.assertEqual(ops_refresh._int_or_zero("8"), 8)
        self.assertEqual(ops_refresh._int_or_zero("not-int"), 0)
        self.assertEqual(ops_refresh._int_or_zero(object()), 0)

        normalized = ops_refresh._normalize_preflight_baseline_payload(
            {
                "graph": {
                    "graph_id": "flakes",
                    "files_included": "329",
                    "role_counts": {"unknown": "161"},
                    "safety": {"storage_written": True},
                },
                "safety": {"source_tree_mutated": False},
            }
        )
        self.assertEqual(normalized["files_included"], "329")
        self.assertEqual(normalized["safety"], {"source_tree_mutated": False})
        fallback_normalized = ops_refresh._normalize_preflight_baseline_payload(
            {"graph": [], "safety": "bad"}
        )
        self.assertEqual(fallback_normalized["graph"], [])
        self.assertEqual(fallback_normalized["safety"], {})

        baseline_preflight = {
            "graph_id": "flakes",
            "files_considered": 337,
            "files_included": 329,
            "files_skipped": 8,
            "directories_skipped": 8,
            "role_counts": {"unknown": 161},
            "secret_like_path_count": 19,
            "symlink_count": 0,
            "diagnostics": [],
            "warnings": [{"code": "private"}],
            "configured_exclude_hit_counts": {"result": 1},
            "safety": {
                "storage_written": False,
                "server_memory_mutated": False,
                "source_acquisition": False,
                "source_tree_mutated": False,
                "destructive_db_actions": False,
                "remote_exposure": False,
                "watch_daemon_started": False,
            },
            "root_path_display": "[private-root]",
            "root_path_expanded": "[private-root]",
        }
        current_preflight = {
            **baseline_preflight,
            "files_included": 330,
            "role_counts": {"unknown": 162},
            "configured_exclude_hit_counts": {"result": 1, ".direnv": 1},
        }
        preflight_drift = ops_refresh._build_preflight_drift_payload(
            current_preflight,
            baseline_preflight,
        )
        self.assertTrue(preflight_drift["files_included"]["changed"])
        self.assertTrue(preflight_drift["unknown_role_count"]["changed"])
        self.assertEqual(
            preflight_drift["configured_exclude_hit_counts"]["changed"][".direnv"]["current"],
            1,
        )
        safety_drift = ops_refresh._build_preflight_safety_drift(
            current_preflight,
            baseline_preflight,
            privacy="private-config",
        )
        self.assertFalse(any(safety_drift.values()))
        self.assertTrue(ops_refresh._preflight_drift_detected(preflight_drift, safety_drift))
        self.assertFalse(
            ops_refresh._preflight_drift_detected(
                ops_refresh._build_preflight_drift_payload(
                    baseline_preflight,
                    baseline_preflight,
                ),
                ops_refresh._build_preflight_safety_drift(
                    baseline_preflight,
                    baseline_preflight,
                    privacy="private-config",
                ),
            )
        )
        unsafe_root = {**baseline_preflight, "root_path_display": "/private/root"}
        self.assertTrue(
            ops_refresh._build_preflight_safety_drift(
                unsafe_root,
                baseline_preflight,
                privacy="private-config",
            )["private_root_redacted"]
        )

        manifest = {
            "backup_format_version": local_db_backup.BACKUP_FORMAT_VERSION,
            "dump_format": "pgcustom",
            "database": "repomap",
            "dump_files": [{"name": "dump.pgcustom", "sha256": "abc", "size_bytes": 3}],
        }
        self.assertEqual(
            backup_manifests.select_dump_file_for_database(manifest, "repomap")["name"],
            "dump.pgcustom",
        )
        multi_manifest = {
            "backup_format_version": local_db_backup.BACKUP_FORMAT_VERSION,
            "dump_format": None,
            "databases": ["repomap", "repomap_flakes"],
            "dump_files": [
                {"name": "repomap_flakes.pgcustom", "sha256": "abc", "size_bytes": 3}
            ],
        }
        self.assertEqual(
            backup_manifests.select_dump_file_for_database(
                multi_manifest,
                "repomap_flakes",
            )["name"],
            "repomap_flakes.pgcustom",
        )
        for bad_manifest in (
            {"backup_format_version": "old", "dump_files": []},
            {
                "backup_format_version": local_db_backup.BACKUP_FORMAT_VERSION,
                "dump_format": "plain",
                "dump_files": [],
            },
            {
                "backup_format_version": local_db_backup.BACKUP_FORMAT_VERSION,
                "dump_files": "bad",
            },
            {
                "backup_format_version": local_db_backup.BACKUP_FORMAT_VERSION,
                "database": "other",
                "dump_files": [],
            },
            {
                "backup_format_version": local_db_backup.BACKUP_FORMAT_VERSION,
                "databases": ["other"],
                "dump_files": [],
            },
            {
                "backup_format_version": local_db_backup.BACKUP_FORMAT_VERSION,
                "database": "repomap",
                "dump_files": [{"name": "dump.pgcustom", "sha256": None, "size_bytes": "3"}],
            },
        ):
            with self.subTest(manifest=bad_manifest):
                with self.assertRaises(local_db_backup.LocalDbBackupError):
                    backup_manifests.select_dump_file_for_database(bad_manifest, "repomap")
        self.assertEqual(backup_commands.decode_process_output(None), "")
        self.assertEqual(backup_commands.decode_process_output(b"a"), "a")
        self.assertEqual(backup_commands.decode_process_output("a"), "a")
        self.assertEqual(backup_commands.decode_process_bytes(None), b"")
        self.assertEqual(backup_commands.decode_process_bytes("a"), b"a")
        self.assertEqual(backup_commands.decode_process_bytes(b"a"), b"a")

        with tempfile.TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir) / "source"
            (source_root / "src" / "main" / "python" / "repomap_kg").mkdir(parents=True)
            (source_root / "src" / "main" / "python" / "repomap_kg" / "__main__.py").write_text(
                "",
                encoding="utf-8",
            )
            (source_root / "src" / "main" / "resources").mkdir(parents=True)
            (source_root / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
            (source_root / "README.md").write_text("# fixture\n", encoding="utf-8")
            nested = source_root / "src" / "main"
            self.assertEqual(
                local_runtime.resolve_runtime_source_root(nested),
                source_root.resolve(),
            )
            with patch.dict(local_runtime.os.environ, {local_runtime.ENV_RUNTIME_SOURCE_ROOT: str(source_root)}):
                self.assertTrue(
                    local_runtime.resolve_runtime_source_root().samefile(source_root)
                )

        plan = local_runtime.default_local_runtime_plan(Path("/tmp/repo-map-home"))
        result = local_runtime.LocalRuntimeResult(
            command="status",
            result="running",
            plan=plan,
            planned_command=("docker", "compose", "ps"),
            diagnostics=(
                local_runtime.LocalRuntimeDiagnostic(
                    "warning",
                    "password-log",
                    "runtime/.env",
                    "POSTGRES_PASSWORD=secret",
                ),
            ),
            containers={
                "server": local_runtime.LocalContainerStatus(
                    "repomap-server",
                    "server",
                    checked=True,
                    exists=True,
                    owned=True,
                    status="running",
                    health="healthy",
                ),
                "postgres": local_runtime.LocalContainerStatus(
                    "repomap-postgres",
                    "postgres",
                    checked=True,
                    exists=True,
                    owned=True,
                    status="exited",
                    exit_code=0,
                    diagnostic="PGPASSWORD=secret closed",
                ),
            },
            server_health=local_runtime.LocalServerHealth(
                checked=True,
                reachable=True,
                status="ok",
                url="http://127.0.0.1:55880/healthz",
                payload={"service": "repomap"},
            ),
        )
        table = local_runtime.format_local_runtime_table(result)
        self.assertIn("dbeaver: disabled", table)
        self.assertIn("container: component=server status=running", table)
        self.assertIn("server_health: status=ok reachable=true", table)
        self.assertIn("POSTGRES_PASSWORD=[REDACTED]", table)
        self.assertIn("PGPASSWORD=[REDACTED]", result.to_jsonable()["containers"]["postgres"]["diagnostic"])
        minimal_container = local_runtime.LocalContainerStatus(
            "repomap-server",
            "server",
        ).to_jsonable()
        self.assertNotIn("exit_code", minimal_container)
        self.assertNotIn("health", minimal_container)
        self.assertNotIn("diagnostic", minimal_container)
        minimal_health = local_runtime.LocalServerHealth().to_jsonable()
        self.assertNotIn("url", minimal_health)
        self.assertNotIn("payload", minimal_health)
        self.assertNotIn("diagnostic", minimal_health)
        direct_db_table = local_runtime.format_local_runtime_table(
            local_runtime.LocalRuntimeResult(
                command="status",
                result="running",
                plan=replace(plan, direct_db_host_port_enabled=True),
            )
        )
        self.assertIn("dbeaver: host=127.0.0.1", direct_db_table)

        backup_plan = local_db_backup.build_backup_plan(
            plan,
            command="dump",
            backup_kind="manual-dump",
            database="repomap",
            databases=("repomap",),
            timestamp="20260703T000000Z",
            reason="coverage fixture",
        )
        diagnostic = local_runtime.LocalRuntimeDiagnostic(
            "warning",
            "format-branch",
            "manifest.json",
            "format branch covered",
        )
        backup_result = local_db_backup.LocalDbBackupResult(
            command="dump",
            result="completed",
            plan=backup_plan,
            dump_files=(
                local_db_backup.BackupDumpFile(
                    name="dump.pgcustom",
                    size_bytes=3,
                    sha256="abc",
                ),
            ),
            diagnostics=(diagnostic,),
            dump_executed=True,
        )
        backup_table = local_db_backup.format_backup_result_table(backup_result)
        self.assertIn("dump_files=dump.pgcustom", backup_table)
        self.assertIn("warning: format-branch", backup_table)

        init_result = local_db_backup.LocalDbInitResult(
            command="init",
            result="completed",
            repo_map_home=plan.repo_map_home,
            database="repomap",
            source_mode="dump",
            runtime_plan=plan,
            backup_id=backup_plan.backup_id,
            backup_path=backup_plan.backup_path,
            manifest_path=backup_plan.manifest_path,
            dump_file="dump.pgcustom",
            dump_path=backup_plan.backup_path / "dump.pgcustom",
            planned_actions=("create-database", "restore-dump"),
            diagnostics=(diagnostic,),
        )
        init_table = local_db_backup.format_init_result_table(init_result)
        self.assertIn(f"backup_id={backup_plan.backup_id}", init_table)
        self.assertIn("dump_file=dump.pgcustom", init_table)
        self.assertIn("planned_actions=create-database,restore-dump", init_table)
        self.assertIn("warning: format-branch", init_table)

        drop_result = local_db_backup.LocalDbDropResult(
            command="drop",
            result="completed",
            repo_map_home=plan.repo_map_home,
            database="repomap",
            runtime_plan=plan,
            backup_plan=backup_plan,
            planned_actions=("create-backup", "drop-database"),
            diagnostics=(diagnostic,),
        )
        drop_table = local_db_backup.format_drop_result_table(drop_result)
        self.assertIn("planned_actions=create-backup,drop-database", drop_table)
        self.assertIn("warning: format-branch", drop_table)

        assert_mcp_validation_cases(self)
        sanitized = mcp_ops.sanitize_jsonable(
            {
                "token": "secret",
                "url": "https://user:pass@example.test/path",
                "canonical_key": "function:main",
                "long": "x" * (mcp_ops.MAX_STRING_LENGTH + 10),
                "nested": [{"password": "secret"}],
            }
        )
        self.assertEqual(sanitized["token"], ops_config.REDACTED)
        self.assertEqual(sanitized["url"], ops_config.REDACTED)
        self.assertEqual(sanitized["canonical_key"], "function:main")
        self.assertTrue(str(sanitized["long"]).endswith("...[truncated]"))
        self.assertEqual(sanitized["nested"][0]["password"], ops_config.REDACTED)
        self.assertIn("FROM canonical_nodes", mcp_ops.build_mcp_search_sql(
            root_path="/repo",
            target="nodes",
            query="main",
            kind="function",
            limit=2,
            offset=0,
            include_raw=False,
        ))
        self.assertIn("payload_json AS payload", mcp_ops.build_mcp_search_sql(
            root_path="/repo",
            target="observations",
            query="main",
            kind="python.function",
            path="src/app.py",
            limit=2,
            offset=0,
            include_raw=True,
        ))
        self.assertIn("FROM files", mcp_ops.build_mcp_search_sql(
            root_path="/repo",
            target="files",
            query="py",
            path="src/app.py",
            limit=2,
            offset=0,
            include_raw=False,
        ))
        with self.assertRaises(mcp_ops.McpOpsError):
            mcp_ops.build_mcp_search_sql(
                root_path="/repo",
                target="bad",
                query="main",
                limit=2,
                offset=0,
                include_raw=False,
            )
