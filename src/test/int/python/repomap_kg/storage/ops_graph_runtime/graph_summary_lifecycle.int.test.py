import json
from pathlib import Path
import tempfile
import unittest

from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


class StorageOpsGraphSummaryLifecycleIntegrationTests(unittest.TestCase):
    def test_ops_graph_summary_cli_reports_bounded_private_graph_counts(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            repo_map_home = Path(tmpdir) / "repo-map-home"
            graph_root = Path(tmpdir) / "codex-memories"
            repo_map_home.mkdir()
            graph_root.mkdir()
            (graph_root / "README.md").write_text("# Private fixture\nPRIVATE_FIXTURE_SECRET\n", encoding="utf-8")
            before_files = sorted(path.name for path in graph_root.iterdir())
            with temporary_postgres() as postgres:
                apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
                config_text = f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "codex-memories"
name = "Codex Memories"
root_path = "{graph_root}"
repository_name = "codex-memories"
privacy = "private-memory"
enabled = true
mcp_visible = true
extractor_profile = "private-ops"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
"""
                config_path.write_text(config_text, encoding="utf-8")
                (repo_map_home / "repomap.rpl.toml").write_text(config_text, encoding="utf-8")

                def _run(*args: str) -> tuple[int, str, str]:
                    return run_repo_map_in_process("ops", *args)

                refresh_exit_code, refresh_stdout, refresh_stderr = _run(
                    "refresh-graph", "--config", str(config_path), "--graph", "codex-memories",
                    "--psql-command", postgres.psql_command, "--json",
                )
                raw_before_summary = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")
                summary_exit_code, summary_stdout, summary_stderr = _run(
                    "graph-summary", "--config", str(config_path), "--graph", "codex-memories",
                    "--psql-command", postgres.psql_command, "--json",
                )
                table_exit_code, table_stdout, table_stderr = _run(
                    "graph-summary", "--config", str(config_path), "--graph", "codex-memories",
                    "--psql-command", postgres.psql_command,
                )
                baseline_exit_code, baseline_stdout, baseline_stderr = _run(
                    "graph-baseline", "--config", str(config_path), "--graph", "codex-memories",
                    "--psql-command", postgres.psql_command, "--json",
                )
                baseline_table_exit_code, baseline_table_stdout, baseline_table_stderr = _run(
                    "graph-baseline", "--config", str(config_path), "--graph", "codex-memories",
                    "--psql-command", postgres.psql_command,
                )
                baseline_path = Path(tmpdir) / "codex-memories-baseline.json"
                baseline_path.write_text(baseline_stdout, encoding="utf-8")
                no_drift_exit_code, no_drift_stdout, no_drift_stderr = _run(
                    "drift-check", "--config", str(config_path), "--graph", "codex-memories",
                    "--baseline-file", str(baseline_path), "--psql-command", postgres.psql_command, "--json",
                )
                preflight_exit_code, preflight_stdout, preflight_stderr = _run(
                    "refresh-preflight", "--config", str(config_path), "--graph", "codex-memories", "--json",
                )
                preflight_baseline_path = Path(tmpdir) / "codex-memories-preflight.json"
                preflight_baseline_path.write_text(preflight_stdout, encoding="utf-8")
                preflight_no_drift_exit_code, preflight_no_drift_stdout, preflight_no_drift_stderr = _run(
                    "drift-check", "--config", str(config_path), "--graph", "codex-memories",
                    "--baseline-file", str(baseline_path), "--include-preflight",
                    "--preflight-baseline-file", str(preflight_baseline_path),
                    "--psql-command", postgres.psql_command, "--json",
                )
                baseline_save_exit_code, baseline_save_stdout, baseline_save_stderr = _run(
                    "baseline-save", "--repo-map-home", str(repo_map_home), "--graph", "codex-memories",
                    "--kind", "both", "--psql-command", postgres.psql_command, "--json",
                )
                saved_stored_latest_path = repo_map_home / "status" / "baselines" / "codex-memories" / "stored" / "latest.json"
                saved_preflight_latest_path = repo_map_home / "status" / "baselines" / "codex-memories" / "preflight" / "latest.json"
                saved_no_drift_exit_code, saved_no_drift_stdout, saved_no_drift_stderr = _run(
                    "drift-check", "--repo-map-home", str(repo_map_home), "--graph", "codex-memories",
                    "--baseline-file", str(saved_stored_latest_path), "--include-preflight",
                    "--preflight-baseline-file", str(saved_preflight_latest_path),
                    "--psql-command", postgres.psql_command, "--json",
                )
                saved_stored_latest_exists = saved_stored_latest_path.exists()
                saved_preflight_latest_exists = saved_preflight_latest_path.exists()
                raw_after_baseline_save = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")
                old_stored_baseline_path = saved_stored_latest_path.with_name("20000101T000000Z.json")
                old_preflight_baseline_path = saved_preflight_latest_path.with_name("20000101T000000Z.json")
                ignored_baseline_path = saved_stored_latest_path.with_name("not-a-timestamp.json")
                old_stored_baseline_path.write_text(saved_stored_latest_path.read_text(encoding="utf-8"), encoding="utf-8")
                old_preflight_baseline_path.write_text(saved_preflight_latest_path.read_text(encoding="utf-8"), encoding="utf-8")
                ignored_baseline_path.write_text("{}", encoding="utf-8")
                baseline_prune_dry_exit_code, baseline_prune_dry_stdout, baseline_prune_dry_stderr = _run(
                    "baseline-prune", "--repo-map-home", str(repo_map_home), "--graph", "codex-memories",
                    "--kind", "both", "--keep", "1", "--dry-run", "--json",
                )
                old_stored_exists_after_dry_run = old_stored_baseline_path.exists()
                baseline_prune_yes_exit_code, baseline_prune_yes_stdout, baseline_prune_yes_stderr = _run(
                    "baseline-prune", "--repo-map-home", str(repo_map_home), "--graph", "codex-memories",
                    "--kind", "both", "--keep", "1", "--yes", "--json",
                )
                old_stored_exists_after_prune = old_stored_baseline_path.exists()
                old_preflight_exists_after_prune = old_preflight_baseline_path.exists()
                stored_latest_exists_after_prune = saved_stored_latest_path.exists()
                preflight_latest_exists_after_prune = saved_preflight_latest_path.exists()
                ignored_exists_after_prune = ignored_baseline_path.exists()
                raw_after_baseline_prune = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")
                drifted_preflight_baseline = json.loads(preflight_stdout)
                drifted_preflight_baseline["graph"]["files_included"] -= 1
                drifted_preflight_baseline_path = Path(tmpdir) / "codex-memories-preflight-drift.json"
                drifted_preflight_baseline_path.write_text(json.dumps(drifted_preflight_baseline), encoding="utf-8")
                preflight_drift_exit_code, preflight_drift_stdout, preflight_drift_stderr = _run(
                    "drift-check", "--config", str(config_path), "--graph", "codex-memories",
                    "--baseline-file", str(baseline_path), "--include-preflight",
                    "--preflight-baseline-file", str(drifted_preflight_baseline_path),
                    "--psql-command", postgres.psql_command, "--json",
                )
                legacy_baseline_path = Path(tmpdir) / "codex-memories-legacy.json"
                legacy_baseline_path.write_text(json.dumps({"graph": json.loads(baseline_stdout)["baseline"]}), encoding="utf-8")
                legacy_no_drift_exit_code, legacy_no_drift_stdout, legacy_no_drift_stderr = _run(
                    "drift-check", "--config", str(config_path), "--graph", "codex-memories",
                    "--baseline-file", str(legacy_baseline_path), "--psql-command", postgres.psql_command, "--json",
                )
                drifted_baseline = json.loads(baseline_stdout)
                drifted_baseline["baseline"]["files"] -= 1
                drifted_baseline_path = Path(tmpdir) / "codex-memories-drift.json"
                drifted_baseline_path.write_text(json.dumps(drifted_baseline), encoding="utf-8")
                drift_exit_code, drift_stdout, drift_stderr = _run(
                    "drift-check", "--config", str(config_path), "--graph", "codex-memories",
                    "--baseline-file", str(drifted_baseline_path), "--psql-command", postgres.psql_command, "--json",
                )
                drift_table_exit_code, drift_table_stdout, drift_table_stderr = _run(
                    "drift-check", "--config", str(config_path), "--graph", "codex-memories",
                    "--baseline-file", str(drifted_baseline_path), "--psql-command", postgres.psql_command,
                )
                mismatched_baseline = json.loads(baseline_stdout)
                mismatched_baseline["baseline"]["graph_id"] = "other-graph"
                mismatched_baseline_path = Path(tmpdir) / "other-baseline.json"
                mismatched_baseline_path.write_text(json.dumps(mismatched_baseline), encoding="utf-8")
                mismatch_exit_code, mismatch_stdout, mismatch_stderr = _run(
                    "drift-check", "--config", str(config_path), "--graph", "codex-memories",
                    "--baseline-file", str(mismatched_baseline_path), "--psql-command", postgres.psql_command, "--json",
                )
                invalid_baseline_path = Path(tmpdir) / "invalid-baseline.json"
                invalid_baseline_path.write_text("[]", encoding="utf-8")
                invalid_exit_code, invalid_stdout, invalid_stderr = _run(
                    "drift-check", "--config", str(config_path), "--graph", "codex-memories",
                    "--baseline-file", str(invalid_baseline_path), "--psql-command", postgres.psql_command, "--json",
                )
                malformed_baseline_path = Path(tmpdir) / "malformed-baseline.json"
                malformed_baseline_path.write_text("{", encoding="utf-8")
                malformed_exit_code, malformed_stdout, malformed_stderr = _run(
                    "drift-check", "--config", str(config_path), "--graph", "codex-memories",
                    "--baseline-file", str(malformed_baseline_path), "--psql-command", postgres.psql_command, "--json",
                )
                raw_after_summary = postgres.psql_scalar("SELECT count(*) FROM raw_observations;")
            after_files = sorted(path.name for path in graph_root.iterdir())

        self.assertEqual(refresh_exit_code, 0, refresh_stderr)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        payload = json.loads(summary_stdout)
        self.assertEqual(payload["command"], "graph-summary")
        self.assertEqual(payload["graph"]["graph_id"], "codex-memories")
        self.assertEqual(payload["graph"]["root_path_display"], "[private-root]")
        self.assertEqual(payload["graph"]["root_path_expanded"], "[private-root]")
        self.assertGreater(payload["graph"]["raw_observations"], 0)
        self.assertGreater(payload["graph"]["canonical_nodes"], 0)
        self.assertFalse(payload["safety"]["graph_root_read"])
        self.assertFalse(payload["safety"]["storage_written"])
        self.assertNotIn("PRIVATE_FIXTURE_SECRET", summary_stdout)
        self.assertNotIn(str(graph_root), summary_stdout)
        self.assertEqual(raw_before_summary, raw_after_summary)
        self.assertEqual(before_files, after_files)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertIn("RepoMap ops graph summary", table_stdout)
        self.assertIn("raw_total=", table_stdout)
        self.assertIn("raw_latest=", table_stdout)
        self.assertNotIn("PRIVATE_FIXTURE_SECRET", table_stdout)
        self.assertEqual(baseline_exit_code, 0, baseline_stderr)
        baseline_payload = json.loads(baseline_stdout)
        self.assertEqual(baseline_payload["command"], "graph-baseline")
        self.assertEqual(baseline_payload["baseline"]["graph_id"], "codex-memories")
        self.assertEqual(baseline_payload["baseline"]["root_path_display"], "[private-root]")
        self.assertGreater(baseline_payload["baseline"]["raw_observations"], 0)
        self.assertFalse(baseline_payload["safety"]["graph_root_read"])
        self.assertFalse(baseline_payload["readback"]["path_examples_included"])
        self.assertNotIn("PRIVATE_FIXTURE_SECRET", baseline_stdout)
        self.assertNotIn(str(graph_root), baseline_stdout)
        self.assertEqual(baseline_table_exit_code, 0, baseline_table_stderr)
        self.assertIn("RepoMap ops graph summary", baseline_table_stdout)
        self.assertNotIn("PRIVATE_FIXTURE_SECRET", baseline_table_stdout)
        self.assertEqual(no_drift_exit_code, 0, no_drift_stderr)
        no_drift_payload = json.loads(no_drift_stdout)
        self.assertEqual(no_drift_payload["command"], "drift-check")
        self.assertEqual(no_drift_payload["result"], "success")
        self.assertFalse(no_drift_payload["drift_detected"])
        self.assertFalse(no_drift_payload["safety"]["storage_written"])
        self.assertNotIn("PRIVATE_FIXTURE_SECRET", no_drift_stdout)
        self.assertEqual(preflight_exit_code, 0, preflight_stderr)
        preflight_payload = json.loads(preflight_stdout)
        self.assertEqual(preflight_payload["command"], "refresh-preflight")
        self.assertEqual(preflight_payload["graph"]["graph_id"], "codex-memories")
        self.assertEqual(preflight_payload["graph"]["root_path_display"], "[private-root]")
        self.assertFalse(preflight_payload["graph"]["path_examples_included"])
        self.assertFalse(preflight_payload["safety"]["storage_written"])
        self.assertNotIn("PRIVATE_FIXTURE_SECRET", preflight_stdout)
        self.assertEqual(preflight_no_drift_exit_code, 0, preflight_no_drift_stderr)
        preflight_no_drift_payload = json.loads(preflight_no_drift_stdout)
        self.assertFalse(preflight_no_drift_payload["stored_drift_detected"])
        self.assertFalse(preflight_no_drift_payload["preflight_drift_detected"])
        self.assertFalse(preflight_no_drift_payload["drift_detected"])
        self.assertEqual(preflight_no_drift_payload["preflight_drift"]["files_included"]["delta"], 0)
        self.assertFalse(preflight_no_drift_payload["preflight_safety_drift"]["storage_written"])
        self.assertNotIn("PRIVATE_FIXTURE_SECRET", preflight_no_drift_stdout)
        self.assertEqual(baseline_save_exit_code, 0, baseline_save_stderr)
        baseline_save_payload = json.loads(baseline_save_stdout)
        self.assertEqual(baseline_save_payload["command"], "baseline-save")
        self.assertEqual(baseline_save_payload["graph_id"], "codex-memories")
        self.assertEqual(baseline_save_payload["kinds"], ["stored", "preflight"])
        self.assertEqual(baseline_save_payload["baseline_root_display"], "status/baselines/codex-memories")
        self.assertTrue(baseline_save_payload["safety"]["baseline_files_written"])
        self.assertFalse(baseline_save_payload["safety"]["db_storage_mutated"])
        self.assertFalse(baseline_save_payload["safety"]["destructive_db_actions"])
        self.assertNotIn(str(repo_map_home), baseline_save_stdout)
        self.assertNotIn(str(graph_root), baseline_save_stdout)
        self.assertNotIn("PRIVATE_FIXTURE_SECRET", baseline_save_stdout)
        self.assertTrue(saved_stored_latest_exists)
        self.assertTrue(saved_preflight_latest_exists)
        self.assertEqual(saved_no_drift_exit_code, 0, saved_no_drift_stderr)
        saved_no_drift_payload = json.loads(saved_no_drift_stdout)
        self.assertFalse(saved_no_drift_payload["stored_drift_detected"])
        self.assertFalse(saved_no_drift_payload["preflight_drift_detected"])
        self.assertFalse(saved_no_drift_payload["drift_detected"])
        self.assertEqual(raw_before_summary, raw_after_baseline_save)
        self.assertEqual(baseline_prune_dry_exit_code, 0, baseline_prune_dry_stderr)
        baseline_prune_dry_payload = json.loads(baseline_prune_dry_stdout)
        self.assertEqual(baseline_prune_dry_payload["command"], "baseline-prune")
        self.assertTrue(baseline_prune_dry_payload["dry_run"])
        self.assertEqual(baseline_prune_dry_payload["graph_id"], "codex-memories")
        self.assertEqual(baseline_prune_dry_payload["kinds"], ["stored", "preflight"])
        self.assertEqual(baseline_prune_dry_payload["baseline_root_display"], "status/baselines/codex-memories")
        self.assertEqual(sum(kind["candidate_count"] for kind in baseline_prune_dry_payload["processed"]), 2)
        self.assertEqual(baseline_prune_dry_payload["safety"]["baseline_files_deleted"], 0)
        self.assertFalse(baseline_prune_dry_payload["safety"]["latest_deleted"])
        self.assertTrue(old_stored_exists_after_dry_run)
        self.assertNotIn(str(repo_map_home), baseline_prune_dry_stdout)
        self.assertNotIn(str(graph_root), baseline_prune_dry_stdout)
        self.assertEqual(baseline_prune_yes_exit_code, 0, baseline_prune_yes_stderr)
        baseline_prune_yes_payload = json.loads(baseline_prune_yes_stdout)
        self.assertFalse(baseline_prune_yes_payload["dry_run"])
        self.assertEqual(baseline_prune_yes_payload["safety"]["baseline_files_deleted"], 2)
        self.assertFalse(baseline_prune_yes_payload["safety"]["latest_deleted"])
        self.assertFalse(old_stored_exists_after_prune)
        self.assertFalse(old_preflight_exists_after_prune)
        self.assertTrue(stored_latest_exists_after_prune)
        self.assertTrue(preflight_latest_exists_after_prune)
        self.assertTrue(ignored_exists_after_prune)
        self.assertEqual(raw_before_summary, raw_after_baseline_prune)
        self.assertEqual(preflight_drift_exit_code, 2, preflight_drift_stderr)
        preflight_drift_payload = json.loads(preflight_drift_stdout)
        self.assertFalse(preflight_drift_payload["stored_drift_detected"])
        self.assertTrue(preflight_drift_payload["preflight_drift_detected"])
        self.assertTrue(preflight_drift_payload["drift_detected"])
        self.assertEqual(preflight_drift_payload["preflight_drift"]["files_included"]["delta"], 1)
        self.assertNotIn("PRIVATE_FIXTURE_SECRET", preflight_drift_stdout)
        self.assertEqual(legacy_no_drift_exit_code, 0, legacy_no_drift_stderr)
        legacy_no_drift_payload = json.loads(legacy_no_drift_stdout)
        self.assertFalse(legacy_no_drift_payload["drift_detected"])
        self.assertEqual(drift_exit_code, 2, drift_stderr)
        drift_payload = json.loads(drift_stdout)
        self.assertEqual(drift_payload["result"], "warning")
        self.assertTrue(drift_payload["drift_detected"])
        self.assertEqual(drift_payload["drift"]["files"]["delta"], 1)
        self.assertFalse(drift_payload["safety"]["destructive_db_actions"])
        self.assertEqual(drift_table_exit_code, 2, drift_table_stderr)
        self.assertIn("RepoMap ops drift check", drift_table_stdout)
        self.assertIn("drift_detected=true", drift_table_stdout)
        self.assertIn("files: baseline=", drift_table_stdout)
        self.assertNotIn("PRIVATE_FIXTURE_SECRET", drift_table_stdout)
        self.assertEqual(mismatch_exit_code, 1)
        self.assertEqual(mismatch_stdout, "")
        self.assertIn("baseline graph id", mismatch_stderr)
        self.assertEqual(invalid_exit_code, 1)
        self.assertEqual(invalid_stdout, "")
        self.assertIn("baseline file must contain a JSON object", invalid_stderr)
        self.assertEqual(malformed_exit_code, 1)
        self.assertEqual(malformed_stdout, "")
        self.assertIn("baseline file is not valid JSON", malformed_stderr)
