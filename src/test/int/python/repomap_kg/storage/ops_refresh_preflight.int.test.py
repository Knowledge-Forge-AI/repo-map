import json
from pathlib import Path
import tempfile
import unittest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


def _graph(
    gid: str, name: str, root: Path, repo: str, priv: str = "public-dev",
    enabled: bool = True, exc: list[str] | None = None, db: str | None = None, prof: str = "default",
) -> str:
    res = (
        f'[[graphs]]\nid = "{gid}"\nname = "{name}"\nroot_path = "{root}"\n'
        f'repository_name = "{repo}"\nprivacy = "{priv}"\nenabled = {str(enabled).lower()}\n'
        f'mcp_visible = {str(enabled).lower()}\nextractor_profile = "{prof}"\nrefresh_policy = "manual"'
    )
    if db:
        res += f'\ndatabase = "{db}"'
    if exc:
        res += f"\nexclude_paths = {json.dumps(exc)}"
    return res


def _cfg(host: str, port: int, user: str, graphs: str, db: str = "repomap_test") -> str:
    return (
        f'schema_version = 1\n[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n'
        f'[postgres]\nhost = "{host}"\nport = {port}\ndatabase = "{db}"\nuser = "{user}"\npassword_env = "REPOMAP_PG_PASSWORD"\n'
        f'{graphs}\n[server_memory]\nenabled = false\npath = "~/.codex/codex-vc/mcp/server-memory"\nmode = "read_only"\n'
    )


class StorageOpsRefreshPreflightIntegrationTests(unittest.TestCase):
    def test_ops_refresh_graph_cli_enforces_configured_exclude_paths(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path, graph_root = Path(tmpdir) / "repomap.local.toml", Path(tmpdir) / "repo-map"
            graph_root.mkdir()
            (graph_root / "README.md").write_text("# Fixture\n", encoding="utf-8")
            (graph_root / "mcp").mkdir()
            (graph_root / "mcp" / "keep.md").write_text("# Keep\n", encoding="utf-8")
            server_memory_root = graph_root / "mcp" / "server-memory"
            server_memory_root.mkdir()
            (server_memory_root / "memory.jsonl").write_text('{"name": "hidden"}\n', encoding="utf-8")
            (server_memory_root / "serena").mkdir()
            (server_memory_root / "serena" / "state.json").write_text('{"state": "hidden"}\n', encoding="utf-8")
            (graph_root / "result-abc").mkdir()
            (graph_root / "result-abc" / "generated.txt").write_text("generated\n", encoding="utf-8")
            (graph_root / "src").mkdir()
            (graph_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            before_files = sorted(p.relative_to(graph_root).as_posix() for p in graph_root.rglob("*"))
            with temporary_postgres() as postgres:
                apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
                config_path.write_text(_cfg(
                    postgres.socket_dir, postgres.port, postgres.user,
                    _graph("repo-map", "RepoMap", graph_root, "repo-map", exc=["mcp/server-memory/memory.jsonl", "mcp/server-memory/serena", "result-*"]),
                ), encoding="utf-8")
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops", "refresh-graph", "--config", str(config_path), "--graph", "repo-map",
                    "--psql-command", postgres.psql_command, "--json",
                )
                observed_paths = postgres.psql_scalar(
                    "SELECT string_agg(path, ',' ORDER BY path) FROM (SELECT DISTINCT path FROM raw_observations) observed;"
                )
            after_files = sorted(p.relative_to(graph_root).as_posix() for p in graph_root.rglob("*"))

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["result"], "success")
        self.assertTrue(payload["graphs"][0]["exclude_paths_enforced"])
        self.assertEqual(payload["graphs"][0]["configured_exclude_paths_count"], 3)
        for p in ("README.md", "mcp/keep.md", "src/app.py"):
            self.assertIn(p, observed_paths)
        for p in ("mcp/server-memory/memory.jsonl", "mcp/server-memory/serena/state.json", "result-abc/generated.txt"):
            self.assertNotIn(p, observed_paths)
        self.assertEqual(before_files, after_files)
        self.assertEqual(stderr, "")

    def test_ops_refresh_enabled_skips_disabled_private_placeholders(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path, graph_root = Path(tmpdir) / "repomap.local.toml", Path(tmpdir) / "repo-map"
            graph_root.mkdir()
            (graph_root / "README.md").write_text("# Fixture\n", encoding="utf-8")
            (graph_root / "mcp" / "server-memory").mkdir(parents=True)
            (graph_root / "mcp" / "server-memory" / "memory.jsonl").write_text('{"name": "hidden"}\n', encoding="utf-8")
            disabled_private_root = Path(tmpdir) / "missing-private-root"
            with temporary_postgres() as postgres:
                apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
                graphs = (
                    _graph("repo-map", "RepoMap", graph_root, "repo-map", exc=["mcp/server-memory/memory.jsonl"]) + "\n"
                    + _graph("codex-vc", "Codex VC", disabled_private_root, "codex-vc", priv="private-ops", enabled=False, db="repomap_codex_vc", prof="private-ops")
                )
                config_path.write_text(_cfg(postgres.socket_dir, postgres.port, postgres.user, graphs), encoding="utf-8")
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops", "refresh-enabled", "--config", str(config_path),
                    "--psql-command", postgres.psql_command, "--json",
                )
                table_exit_code, table_stdout, table_stderr = run_repo_map_in_process(
                    "ops", "refresh-enabled", "--config", str(config_path),
                    "--psql-command", postgres.psql_command,
                )
                repository_names = postgres.psql_scalar("SELECT string_agg(name, ',' ORDER BY name) FROM repositories;")
                observed_paths = postgres.psql_scalar(
                    "SELECT string_agg(path, ',' ORDER BY path) FROM (SELECT DISTINCT path FROM raw_observations) observed;"
                )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["result"], "success")
        self.assertEqual(payload["graph_count"], 1)
        self.assertEqual(payload["graphs"][0]["graph_id"], "repo-map")
        self.assertTrue(payload["graphs"][0]["exclude_paths_enforced"])
        self.assertNotIn("codex-vc", stdout)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertIn("RepoMap ops refresh result", table_stdout)
        self.assertIn("repo-map | repo-map | repomap_test | public-dev | success", table_stdout)
        self.assertNotIn("codex-vc", table_stdout)
        self.assertEqual(repository_names, "repo-map")
        self.assertIn("README.md", observed_paths)
        self.assertNotIn("mcp/server-memory/memory.jsonl", observed_paths)
        self.assertEqual((stderr, table_stderr), ("", ""))

    def test_ops_refresh_graph_cli_reports_storage_load_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path, graph_root = Path(tmpdir) / "repomap.local.toml", Path(tmpdir) / "repo-map"
            graph_root.mkdir()
            (graph_root / "README.md").write_text("# Fixture\n", encoding="utf-8")
            config_path.write_text(_cfg(
                "127.0.0.1", 5432, "admin",
                _graph("repo-map", "RepoMap", graph_root, "repo-map", priv="private-ops"),
                db="repomap",
            ), encoding="utf-8")
            exit_code, stdout, stderr = run_repo_map_in_process(
                "ops", "refresh-graph", "--config", str(config_path), "--graph", "repo-map",
                "--psql-command", "/bin/false", "--json",
            )

        self.assertEqual(exit_code, 1)
        payload = json.loads(stdout)
        self.assertEqual(payload["result"], "failed")
        self.assertEqual(payload["graphs"][0]["result"], "failure")
        self.assertEqual(payload["graphs"][0]["warnings"][0]["code"], "private-graph-refresh")
        self.assertFalse(payload["safety"]["destructive_db_actions"])
        self.assertEqual(stderr, "")

    def test_ops_refresh_graph_cli_rejects_disabled_graph_before_root_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            disabled_root = Path(tmpdir) / "missing"
            config_path.write_text(_cfg(
                "127.0.0.1", 5432, "admin",
                _graph("codex-vc", "Codex VC", disabled_root, "codex-vc", priv="private-ops", enabled=False, db="repomap_codex_vc", prof="private-ops"),
                db="repomap",
            ), encoding="utf-8")
            exit_code, stdout, stderr = run_repo_map_in_process(
                "ops", "refresh-graph", "--config", str(config_path), "--graph", "codex-vc", "--json",
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("disabled", stderr)

    def test_ops_refresh_status_cli_reports_missing_schema_read_only(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path, graph_root = Path(tmpdir) / "repomap.local.toml", Path(tmpdir) / "repo-map"
            with temporary_postgres() as postgres:
                graphs = (
                    _graph("repo-map", "RepoMap", graph_root, "repo-map") + "\n"
                    + _graph("codex-vc", "Codex VC", Path(tmpdir) / "codex-vc", "codex-vc", priv="private-ops", db="repomap_codex_vc", prof="private-ops")
                )
                config_path.write_text(_cfg(postgres.socket_dir, postgres.port, postgres.user, graphs), encoding="utf-8")
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops", "refresh-status", "--config", str(config_path), "--graph", "repo-map",
                    "--psql-command", postgres.psql_command, "--json",
                )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["filtered"])
        self.assertEqual(payload["graph_count"], 1)
        self.assertEqual(payload["graphs"][0]["graph_id"], "repo-map")
        self.assertNotIn("codex-vc", stdout)
        self.assertTrue(payload["db_checked"])
        self.assertFalse(payload["graphs"][0]["root_path_checked"])
        self.assertIn("storage schema is unavailable", payload["graphs"][0]["error"])
        self.assertFalse(payload["safety"]["destructive_db_actions"])
        self.assertEqual(stderr, "")

    def test_ops_refresh_preflight_cli_does_not_write_storage_rows(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path, graph_root = Path(tmpdir) / "repomap.local.toml", Path(tmpdir) / "codex-memories"
            graph_root.mkdir()
            (graph_root / "README.md").write_text("# Fake memory docs\n", encoding="utf-8")
            (graph_root / "notes").mkdir()
            (graph_root / "notes" / "index.md").write_text("bounded note\n", encoding="utf-8")
            (graph_root / "mcp" / "server-memory" / "serena").mkdir(parents=True)
            (graph_root / "mcp" / "server-memory" / "memories.jsonl").write_text('{"text":"fixture-secret-memory-value"}\n', encoding="utf-8")
            (graph_root / "mcp" / "server-memory" / "serena" / "state.json").write_text('{"state":"skip"}\n', encoding="utf-8")
            with temporary_postgres() as postgres:
                apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
                count_sql = (
                    "SELECT (SELECT count(*) FROM repositories)::text || '|' || (SELECT count(*) FROM raw_observations)::text || '|'"
                    " || (SELECT count(*) FROM canonical_nodes)::text || '|' || (SELECT count(*) FROM canonical_edges)::text;"
                )
                before_count = postgres.psql_scalar(count_sql)
                config_path.write_text(_cfg(
                    postgres.socket_dir, postgres.port, postgres.user,
                    _graph("codex-memories", "Codex Memories", graph_root, "codex-memories", priv="private-memory", prof="private-ops", exc=["mcp/server-memory/memories.jsonl", "mcp/server-memory/serena"]),
                ), encoding="utf-8")
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops", "refresh-preflight", "--config", str(config_path), "--graph", "codex-memories", "--json",
                )
                table_exit, table_stdout, table_stderr = run_repo_map_in_process(
                    "ops", "refresh-preflight", "--config", str(config_path), "--graph", "codex-memories",
                )
                after_count = postgres.psql_scalar(count_sql)

        self.assertEqual((exit_code, table_exit), (0, 0))
        self.assertEqual((after_count, before_count), ("0|0|0|0", "0|0|0|0"))
        payload = json.loads(stdout)
        self.assertEqual((payload["command"], payload["graph"]["graph_id"]), ("refresh-preflight", "codex-memories"))
        self.assertTrue(payload["graph"]["root_exists"])
        self.assertEqual(
            (payload["graph"]["files_included"], payload["graph"]["files_skipped"], payload["graph"]["directories_skipped"]),
            (2, 1, 1),
        )
        self.assertEqual(payload["graph"]["configured_exclude_hit_counts"]["mcp/server-memory/memories.jsonl"], 1)
        self.assertEqual(payload["graph"]["configured_exclude_hit_counts"]["mcp/server-memory/serena"], 1)
        self.assertFalse(payload["safety"]["storage_written"])
        self.assertFalse(payload["safety"]["destructive_db_actions"])
        self.assertNotIn("fixture-secret-memory-value", stdout)
        self.assertIn("RepoMap ops refresh preflight", table_stdout)
        self.assertIn("storage_written=false", table_stdout)

    def test_ops_refresh_preflight_cli_reports_nix_hazards_bounded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path, graph_root = Path(tmpdir) / "repomap.local.toml", Path(tmpdir) / "flakes"
            outside_root = Path(tmpdir) / "outside-output"
            graph_root.mkdir()
            outside_root.mkdir()
            (graph_root / "README.md").write_text("# Flakes\n", encoding="utf-8")
            (graph_root / ".direnv").mkdir()
            (graph_root / ".direnv" / "cache.json").write_text("{}\n", encoding="utf-8")
            (graph_root / "secrets.local").write_text("fixture-secret-value\n", encoding="utf-8")
            try:
                (graph_root / "result").symlink_to(outside_root, target_is_directory=True)
                (graph_root / "result-store").symlink_to("/nix/store/repomap-fixture-output")
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            config_path.write_text(_cfg(
                "127.0.0.1", 5432, "repomap",
                _graph("flakes", "Flakes", graph_root, "flakes", priv="private-config", prof="private-ops", db="repomap_flakes", exc=["result", "result-*"]),
                db="repomap",
            ), encoding="utf-8")
            exit_code, stdout, stderr = run_repo_map_in_process(
                "ops", "refresh-preflight", "--config", str(config_path), "--graph", "flakes", "--json",
            )
            table_exit, table_stdout, table_stderr = run_repo_map_in_process(
                "ops", "refresh-preflight", "--config", str(config_path), "--graph", "flakes",
            )

        self.assertEqual((exit_code, table_exit), (0, 0))
        payload = json.loads(stdout)
        graph = payload["graph"]
        self.assertEqual(graph["graph_id"], "flakes")
        self.assertEqual(graph["root_path_display"], "[private-root]")
        self.assertEqual(graph["default_exclude_hit_counts"][".direnv"], 1)
        self.assertEqual(graph["configured_exclude_hit_counts"]["result"], 1)
        self.assertEqual(graph["configured_exclude_hit_counts"]["result-*"], 1)
        self.assertGreaterEqual(graph["symlink_count"], 2)
        self.assertGreaterEqual(graph["symlinks_skipped_outside_root"], 2)
        self.assertGreaterEqual(graph["symlinks_skipped_nix_store"], 1)
        self.assertGreaterEqual(graph["generated_output_skips"], 2)
        self.assertGreaterEqual(graph["secret_like_path_count"], 1)
        self.assertFalse(graph["path_examples_included"])
        self.assertFalse(payload["safety"]["storage_written"])
        self.assertFalse(payload["safety"]["source_acquisition"])
        self.assertNotIn("fixture-secret-value", stdout)
        self.assertIn("nix hazards:", table_stdout)
        self.assertIn("path_examples_included=false", table_stdout)
