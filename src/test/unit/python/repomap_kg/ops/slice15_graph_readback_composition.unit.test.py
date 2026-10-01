"""Migrated Slice15 isolated regressions; no integration campaign credit."""

from __future__ import annotations
import argparse
import json
import sys
from types import ModuleType, SimpleNamespace
import unittest
from repomap_kg.cli._ops_control_dispatch import dispatch_ops_control_command
from repomap_kg.cli._ops_refresh_dispatch import dispatch_ops_refresh_command
from repomap_kg.cli.source_commands import dispatch_source_acquisition_command
from repomap_kg.ops.config_loading_records import merge_ops_config_payloads
from repomap_kg.ops.graph_file_sql import GraphFileFilters, validate_graph_file_query
from repomap_kg.storage.errors import StorageSchemaError


def _command_module(**members: object) -> ModuleType:
    module = ModuleType("fixture_commands")
    vars(module).update(members)
    return module


class Slice15GraphReadbackCompositionUnitTests(unittest.TestCase):
    def test_s15_b01_ops_control_command_coordinator_control_lifecycle(self) -> None:
        """dispatch_ops_control_command dispatches status, init, and upgrade control commands."""
        # Non-ops command returns None
        args_non_ops = argparse.Namespace(command="other")
        self.assertIsNone(dispatch_ops_control_command(args_non_ops, ModuleType("cmds"), lambda *a, **k: None))

        mock_cmds = _command_module()
        control_error = type("CoordinatorControlError", (Exception,), {})
        vars(mock_cmds)["CoordinatorControlError"] = control_error
        vars(mock_cmds)["coordinator_control_status"] = lambda home: {
            "result": "ready", "service_mode": "local", "fencing_epoch": 1,
        }
        vars(mock_cmds)["initialize_coordinator_control"] = lambda home: {
            "result": "ready", "status": "initialized",
        }
        vars(mock_cmds)["upgrade_coordinator_control"] = lambda home, **kwargs: {
            "result": "planned" if kwargs.get("dry_run") else "ready",
            "upgrade": True,
        }
        vars(mock_cmds)["format_coordinator_control_table"] = lambda p: f"TABLE: {p['result']}"

        # 1. coordinator-control-status with table output
        args_status = argparse.Namespace(
            command="ops",
            ops_command="coordinator-control-status",
            repo_map_home="/tmp/home",
            json=False,
        )
        self.assertEqual(dispatch_ops_control_command(args_status, mock_cmds, lambda *a, **k: None), 0)

        # 2. coordinator-control-status with JSON output
        args_status_json = argparse.Namespace(
            command="ops",
            ops_command="coordinator-control-status",
            repo_map_home="/tmp/home",
            json=True,
        )
        self.assertEqual(dispatch_ops_control_command(args_status_json, mock_cmds, lambda *a, **k: None), 0)

        # 3. coordinator-control-init
        args_init = argparse.Namespace(
            command="ops",
            ops_command="coordinator-control-init",
            repo_map_home="/tmp/home",
            json=False,
        )
        self.assertEqual(dispatch_ops_control_command(args_init, mock_cmds, lambda *a, **k: None), 0)

        # 4. coordinator-control-upgrade (dry-run)
        args_upgrade = argparse.Namespace(
            command="ops",
            ops_command="coordinator-control-upgrade",
            repo_map_home="/tmp/home",
            backup_first=True,
            yes=False,
            dry_run=True,
            reason="test upgrade",
            json=True,
        )
        self.assertEqual(dispatch_ops_control_command(args_upgrade, mock_cmds, lambda *a, **k: None), 0)

        # 5. Error propagation
        def _failing_status(home: str) -> dict[str, object]:
            raise control_error("database unavailable")

        vars(mock_cmds)["coordinator_control_status"] = _failing_status
        errors: list[object] = []
        code = dispatch_ops_control_command(args_status, mock_cmds, lambda err, **k: errors.append(err))
        self.assertEqual(code, 1)
        self.assertEqual(len(errors), 1)


    def test_s15_b02_ops_control_command_coordinator_jobs_management(self) -> None:
        """dispatch_ops_control_command handles job status, wait, cancel, and jobs listing."""
        mock_cmds = _command_module()
        vars(mock_cmds)["CoordinatorClientError"] = type("CoordinatorClientError", (Exception,), {})
        vars(mock_cmds)["CoordinatorModeError"] = type("CoordinatorModeError", (Exception,), {})
        vars(mock_cmds)["coordinator_job_status"] = lambda home, jid: {"result": "success", "job_id": jid, "status": "running"}
        vars(mock_cmds)["wait_for_coordinator_job"] = lambda home, jid, **k: {"result": "success", "job_id": jid, "status": "complete"}
        vars(mock_cmds)["cancel_coordinator_job"] = lambda home, jid: {"result": "success", "job_id": jid, "status": "cancelled"}
        vars(mock_cmds)["list_coordinator_jobs"] = lambda home, **k: {"jobs": [{"job_id": "j1"}], "has_more": False}
        vars(mock_cmds)["format_coordinator_job_table"] = lambda p: f"JOB: {p['job_id']}"
        vars(mock_cmds)["format_coordinator_jobs_table"] = lambda p: f"JOBS: {len(p['jobs'])}"

        # Status
        args_status = argparse.Namespace(command="ops", ops_command="coordinator-job-status", repo_map_home="/tmp", job_id="job-1", json=False)
        self.assertEqual(dispatch_ops_control_command(args_status, mock_cmds, lambda *a, **k: None), 0)

        # Wait
        args_wait = argparse.Namespace(command="ops", ops_command="coordinator-job-wait", repo_map_home="/tmp", job_id="job-1", wait_timeout_seconds=5.0, json=True)
        self.assertEqual(dispatch_ops_control_command(args_wait, mock_cmds, lambda *a, **k: None), 0)

        # Cancel
        args_cancel = argparse.Namespace(command="ops", ops_command="coordinator-job-cancel", repo_map_home="/tmp", job_id="job-1", json=False)
        self.assertEqual(dispatch_ops_control_command(args_cancel, mock_cmds, lambda *a, **k: None), 0)

        # List jobs
        args_list = argparse.Namespace(command="ops", ops_command="coordinator-jobs", repo_map_home="/tmp", limit=10, graph_id=None, cursor=None, json=False)
        self.assertEqual(dispatch_ops_control_command(args_list, mock_cmds, lambda *a, **k: None), 0)


    def test_s15_b03_ops_refresh_command_config_check_and_graphs(self) -> None:
        """dispatch_ops_refresh_command dispatches config-check and graphs commands."""
        # Non-ops returns None
        self.assertIsNone(dispatch_ops_refresh_command(argparse.Namespace(command="build"), ModuleType("cmds"), lambda *a, **k: None))

        mock_cmds = _command_module()
        vars(mock_cmds)["OpsConfigError"] = type("OpsConfigError", (Exception,), {})
        vars(mock_cmds)["load_ops_config_from_args"] = lambda args: {"loaded": True}
        vars(mock_cmds)["check_ops_postgres_status"] = lambda cfg, **k: {"db": "ok"}
        vars(mock_cmds)["ops_config_status_to_jsonable"] = lambda cfg, **k: {"status": "valid"}
        vars(mock_cmds)["format_ops_config_status_table"] = lambda cfg, **k: "STATUS TABLE"
        vars(mock_cmds)["check_ops_graph_storage_status"] = lambda cfg, **k: {"graphs_storage": "ok"}
        vars(mock_cmds)["ops_graph_registry_status_to_jsonable"] = lambda cfg, **k: {"registry": "valid"}
        vars(mock_cmds)["format_ops_graph_registry_table"] = lambda cfg, **k: "REGISTRY TABLE"

        # config-check table
        args_chk = argparse.Namespace(command="ops", ops_command="config-check", check_db=True, psql_command="psql", json=False)
        self.assertEqual(dispatch_ops_refresh_command(args_chk, mock_cmds, lambda *a, **k: None), 0)

        # config-check json
        args_chk_j = argparse.Namespace(command="ops", ops_command="config-check", check_db=False, psql_command="psql", json=True)
        self.assertEqual(dispatch_ops_refresh_command(args_chk_j, mock_cmds, lambda *a, **k: None), 0)

        # graphs table
        args_gr = argparse.Namespace(command="ops", ops_command="graphs", check_db=True, psql_command="psql", json=False)
        self.assertEqual(dispatch_ops_refresh_command(args_gr, mock_cmds, lambda *a, **k: None), 0)

        # graphs json
        args_gr_j = argparse.Namespace(command="ops", ops_command="graphs", check_db=False, psql_command="psql", json=True)
        self.assertEqual(dispatch_ops_refresh_command(args_gr_j, mock_cmds, lambda *a, **k: None), 0)


    def test_s15_b04_ops_refresh_command_coordinator_telemetry_rejection(self) -> None:
        """dispatch_ops_refresh_command rejects telemetry descriptors in coordinator mode."""
        mock_cmds = _command_module()
        vars(mock_cmds)["CoordinatorModeError"] = type("CoordinatorModeError", (Exception,), {})
        errors: list[object] = []

        args_bad_telemetry = argparse.Namespace(
            command="ops",
            ops_command="refresh-graph",
            mode="coordinator",
            backend_telemetry_fd=3,
            backend_telemetry_ack_fd=None,
            staging_event_fd=None,
        )
        code = dispatch_ops_refresh_command(args_bad_telemetry, mock_cmds, lambda err, **k: errors.append(err))
        self.assertEqual(code, 1)
        self.assertEqual(len(errors), 1)


    def test_s15_b05_source_acquisition_command_dispatch_imports(self) -> None:
        """dispatch_source_acquisition_command dispatches ingest-feed, import-archive, and import-warc."""
        summary_feed = SimpleNamespace(
            source_id="feed-1", feed_observations=10,
            to_jsonable=lambda: {"source_id": "feed-1", "feed_observations": 10},
        )
        summary_arch = SimpleNamespace(
            source_id="arch-1", observations=20,
            to_jsonable=lambda: {"source_id": "arch-1", "observations": 20},
        )
        summary_warc = SimpleNamespace(
            source_id="warc-1", observations=30, routed_payloads=5,
            to_jsonable=lambda: {"source_id": "warc-1", "observations": 30, "routed_payloads": 5},
        )
        mock_cmds = _command_module(
            ApiPolicyError=type("ApiPolicyError", (Exception,), {}),
            BulkPolicyError=type("BulkPolicyError", (Exception,), {}),
            GitHubApiPolicyError=type("GitHubApiPolicyError", (Exception,), {}),
            SourceAcquisitionError=type("SourceAcquisitionError", (Exception,), {}),
            SourcePolicyError=type("SourcePolicyError", (Exception,), {}),
            acquire_api_source=lambda **k: None,
            acquire_github_api_source=lambda **k: None,
            build_api_plan_from_config=lambda cfg: None,
            build_bulk_plan_from_config=lambda cfg: None,
            build_github_api_plan_from_config=lambda cfg: None,
            import_archive_source=lambda **k: summary_arch,
            import_bulk_source=lambda **k: None,
            import_warc_source=lambda **k: summary_warc,
            ingest_feed_source=lambda **k: summary_feed,
            json=json,
            sys=sys,
        )

        # Feed
        args_feed = argparse.Namespace(command="sources", source_command="ingest-feed", config="c.toml", root_path="/p", artifact_dir="/a", json=False)
        self.assertEqual(dispatch_source_acquisition_command(args_feed, mock_cmds, lambda *a, **k: None), 0)

        # Archive
        args_arch = argparse.Namespace(command="sources", source_command="import-archive", config="c.toml", root_path="/p", json=True)
        self.assertEqual(dispatch_source_acquisition_command(args_arch, mock_cmds, lambda *a, **k: None), 0)

        # WARC
        args_warc = argparse.Namespace(command="sources", source_command="import-warc", config="c.toml", root_path="/p", json=False)
        self.assertEqual(dispatch_source_acquisition_command(args_warc, mock_cmds, lambda *a, **k: None), 0)


    def test_s15_b06_source_acquisition_command_dispatch_planning(self) -> None:
        """dispatch_source_acquisition_command dispatches bulk, api, and github-api plan."""
        plan_result = SimpleNamespace(to_jsonable=lambda: {"planned": True})
        mock_cmds = _command_module(
            ApiPolicyError=type("ApiPolicyError", (Exception,), {}),
            BulkPolicyError=type("BulkPolicyError", (Exception,), {}),
            GitHubApiPolicyError=type("GitHubApiPolicyError", (Exception,), {}),
            SourceAcquisitionError=type("SourceAcquisitionError", (Exception,), {}),
            SourcePolicyError=type("SourcePolicyError", (Exception,), {}),
            acquire_api_source=lambda **k: None,
            acquire_github_api_source=lambda **k: None,
            build_api_plan_from_config=lambda cfg: plan_result,
            build_bulk_plan_from_config=lambda cfg: plan_result,
            build_github_api_plan_from_config=lambda cfg: plan_result,
            import_archive_source=lambda **k: None,
            import_bulk_source=lambda **k: None,
            import_warc_source=lambda **k: None,
            ingest_feed_source=lambda **k: None,
            json=json,
            sys=sys,
        )

        # Bulk plan
        args_bulk = argparse.Namespace(command="bulk", bulk_command="plan", config="bulk.toml", json=True)
        self.assertEqual(dispatch_source_acquisition_command(args_bulk, mock_cmds, lambda *a, **k: None), 0)

        # API plan
        args_api = argparse.Namespace(command="api", api_command="plan", config="api.toml", json=True)
        self.assertEqual(dispatch_source_acquisition_command(args_api, mock_cmds, lambda *a, **k: None), 0)

        # GitHub API plan
        args_gh = argparse.Namespace(command="github", github_command="plan", config="gh.toml", json=True)
        self.assertEqual(dispatch_source_acquisition_command(args_gh, mock_cmds, lambda *a, **k: None), 0)


    def test_s15_b07_ops_config_payload_merging_matrix(self) -> None:
        """merge_ops_config_payloads merges sections, graphs, and emits overlay diagnostics."""
        base_payload = {
            "service": {"mode": "local", "log_level": "info"},
            "postgres": {"host": "localhost", "port": 5432},
            "graphs": [{"id": "g1", "name": "Graph 1"}],
        }
        override_payload = {
            "service": {"log_level": "debug"},
            "postgres": {"port": 5433},
            "graphs": [{"id": "g1", "name": "Graph 1 Overridden"}, {"id": "g2", "name": "Graph 2"}],
        }

        merged, diagnostics = merge_ops_config_payloads([
            ("base.toml", base_payload),
            ("override.toml", override_payload),
        ])
        self.assertEqual(merged["service"]["log_level"], "debug")
        self.assertEqual(merged["service"]["mode"], "local")
        self.assertEqual(merged["postgres"]["port"], 5433)
        self.assertEqual(len(merged["graphs"]), 2)
        self.assertEqual(merged["graphs"][0]["name"], "Graph 1 Overridden")

        # Diagnostics reflect overlay warnings
        diag_codes = {d.code for d in diagnostics}
        self.assertIn("service-overlay", diag_codes)
        self.assertIn("postgres-overlay", diag_codes)
        self.assertIn("graph-overlay", diag_codes)


    def test_s15_b08_ops_graph_file_query_validation(self) -> None:
        """validate_graph_file_query validates bounds, limit, offset, and mutual exclusions."""
        # 1. Valid default filters
        filters = GraphFileFilters(path="src/main.py", generated="include", executable="include")
        limit, offset = validate_graph_file_query(filters, limit=25, offset=0)
        self.assertEqual(limit, 25)
        self.assertEqual(offset, 0)

        # 2. Combining path and path_prefix raises StorageSchemaError
        bad_comb = GraphFileFilters(path="src/main.py", path_prefix="src/")
        with self.assertRaises(StorageSchemaError) as cm_comb:
            validate_graph_file_query(bad_comb, limit=10, offset=0)
        self.assertIn("cannot combine path and path prefix", str(cm_comb.exception))

        # 3. Invalid tri-state filter values
        bad_gen = GraphFileFilters(generated="invalid_tri_state")
        with self.assertRaises(StorageSchemaError) as cm_gen:
            validate_graph_file_query(bad_gen, limit=10, offset=0)
        self.assertIn("invalid generated filter", str(cm_gen.exception))

        # 4. Limit exceeded (max 200)
        with self.assertRaises(StorageSchemaError) as cm_lim:
            validate_graph_file_query(GraphFileFilters(), limit=250, offset=0)
        self.assertIn("limit must be between 1 and 200", str(cm_lim.exception))

        # 5. Negative offset
        with self.assertRaises(StorageSchemaError) as cm_off:
            validate_graph_file_query(GraphFileFilters(), limit=10, offset=-5)
        self.assertIn("offset must be a non-negative integer", str(cm_off.exception))
