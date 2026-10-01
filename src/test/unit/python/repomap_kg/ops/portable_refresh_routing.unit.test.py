from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from repomap_test_support.ops_refresh import OpsRefreshUnitTestCase

from repomap_kg.graph.multi_source_pipeline import scan_multi_source_generations
from repomap_kg.ops.generations import canonicalizer_generation, extractor_generation
from repomap_kg.ops.portable_refresh import (
    _private_directory,
    _prune_expired_terminal_attempts,
    execute_portable_refresh,
    PortableRefreshError,
)
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.main import LoadSummary
from repomap_kg.storage.staged_ingestion import IngestionAuthority


class PortableRefreshRoutingUnitTests(OpsRefreshUnitTestCase):
    def test_parent_private_directory_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owned = root / "owned"
            owned.mkdir()
            substituted = root / "substituted"
            substituted.symlink_to(owned, target_is_directory=True)

            with self.assertRaises(OSError):
                _private_directory(substituted)

    def test_direct_route_runs_real_portable_worker_then_one_publisher_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = self.config_for_roots(root)

            with patch(
                "repomap_kg.ops.portable_refresh.run_staged_portable_refresh",
                return_value=LoadSummary(repository_id=7, run_id=11, files=1),
            ) as publish:
                outcome = execute_portable_refresh(
                    config,
                    config.graphs[0],
                    "repomap_repo_map",
                    authority=None,
                )

        assert outcome.files == 1
        assert outcome.observations >= 1
        bundle = publish.call_args.args[1]
        binding = publish.call_args.kwargs["portable_binding"]
        assert bundle.row_stage_contract == "stage-unassigned-v1"
        assert binding.execution_mode == "direct"
        assert binding.publication_bundle_id == bundle.bundle_id
        assert all(
            row["stage_id"] == "stage-unassigned"
            for rows in bundle.families.values()
            for row in rows
        )

    def test_coordinator_replay_uses_retained_bundle_without_second_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = self.config_for_roots(root)
            graph = config.graphs[0]
            scan = scan_multi_source_generations(graph)
            authority = IngestionAuthority(
                operation_id=OperationId("job-portable-route"),
                attempt=AttemptNumber(1),
                execution_mode="coordinator",
                source_generation=scan.source_generation,
                config_generation=scan.config_generation,
                extractor_generation=extractor_generation(graph),
                canonicalizer_generation=canonicalizer_generation(),
                job_id=JobId("job-portable-route"),
                coordinator_instance_id="coord-1",
                singleton_fencing_epoch=3,
                graph_lease_fencing_epoch=5,
            )

            with patch(
                "repomap_kg.ops.portable_refresh.run_staged_portable_refresh",
                return_value=LoadSummary(repository_id=7, run_id=11, files=1),
            ) as publish:
                first = execute_portable_refresh(
                    config, graph, "repomap_repo_map", authority=authority
                )
                with patch(
                    "repomap_kg.ops.portable_refresh.run_portable_worker",
                    side_effect=AssertionError("worker replayed"),
                ):
                    second = execute_portable_refresh(
                        config, graph, "repomap_repo_map", authority=authority
                    )

            retained = tuple(
                (Path(config.config_path).resolve().parent / "state" / "portable-publication" / "attempts")
                .glob("*/portable-result.json")
            )
            assert len(retained) == 1
            retention = json.loads(retained[0].read_text(encoding="utf-8"))

        assert first.files == second.files == 1
        assert publish.call_count == 2
        assert retention["retention_class"] == "terminal-accepted"
        assert isinstance(retention["expires_at_epoch"], int)
        assert all(
            call.kwargs["authority"] == authority for call in publish.call_args_list
        )

    def test_cleanup_prunes_only_expired_terminal_attempts(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            os.chmod(parent, 0o700)
            expired = parent / "expired"
            unresolved = parent / "unresolved"
            for attempt in (expired, unresolved):
                attempt.mkdir(mode=0o700)
            (expired / "portable-result.json").write_text(
                json.dumps(
                    {"retention_class": "terminal-accepted", "expires_at_epoch": 1}
                ),
                encoding="utf-8",
            )
            (unresolved / "portable-result.json").write_text(
                json.dumps({"retention_class": "publication-reconciliation"}),
                encoding="utf-8",
            )
            os.chmod(expired / "portable-result.json", 0o600)
            os.chmod(unresolved / "portable-result.json", 0o600)

            _prune_expired_terminal_attempts(parent, exclude=parent / "current")

            assert not expired.exists()
            assert unresolved.is_dir()

    def test_publication_failure_marks_terminal_failed_retention(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = self.config_for_roots(root)

            with patch(
                "repomap_kg.ops.portable_refresh.run_staged_portable_refresh",
                side_effect=RuntimeError("database exploded"),
            ):
                with self.assertRaises(RuntimeError):
                    execute_portable_refresh(
                        config,
                        config.graphs[0],
                        "repomap_repo_map",
                        authority=None,
                    )

            retained = tuple(
                (Path(config.config_path).resolve().parent / "state" / "portable-publication" / "attempts")
                .glob("*/portable-result.json")
            )
            assert len(retained) == 1
            retention = json.loads(retained[0].read_text(encoding="utf-8"))
            assert retention["retention_class"] == "terminal-failed"
            assert isinstance(retention["expires_at_epoch"], int)

    def test_parent_publication_executes_strictly_after_worker_and_outside_child_deadline(self):
        """Assert call ordering within execute_portable_refresh where child worker completes before publication.

        Note: This sequence holds within execute_portable_refresh, but does not isolate publication
        from the outer coordinator worker process deadline in configured_refresh (see ADR 0073).
        """
        import repomap_kg.ops.portable_refresh as pr_module
        call_order = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = self.config_for_roots(root)

            orig_run_portable = pr_module.run_portable_worker
            def tracked_run_portable(*args, **kwargs):
                call_order.append("child_worker_start")
                res = orig_run_portable(*args, **kwargs)
                call_order.append("child_worker_complete")
                return res

            def tracked_publish(*args, **kwargs):
                call_order.append("parent_publish_start")
                call_order.append("parent_publish_complete")
                return LoadSummary(repository_id=7, run_id=11, files=1)

            with (
                patch("repomap_kg.ops.portable_refresh.run_portable_worker", side_effect=tracked_run_portable),
                patch("repomap_kg.ops.portable_refresh.run_staged_portable_refresh", side_effect=tracked_publish),
            ):
                outcome = execute_portable_refresh(
                    config,
                    config.graphs[0],
                    "repomap_repo_map",
                    authority=None,
                )

        assert outcome.files == 1
        assert call_order == [
            "child_worker_start",
            "child_worker_complete",
            "parent_publish_start",
            "parent_publish_complete",
        ]

    def test_leaf_worker_process_timeout_surfaces_as_worker_timeout(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = self.config_for_roots(root)

            fake_worker = SimpleNamespace(
                terminal={
                    "status": "failed",
                    "reason": "process_timeout",
                    "summary": "synthetic process_timeout",
                }
            )
            with patch("repomap_kg.ops.portable_refresh.run_portable_worker", return_value=fake_worker):
                with self.assertRaises(PortableRefreshError) as ctx:
                    execute_portable_refresh(
                        config,
                        config.graphs[0],
                        "repomap_repo_map",
                        authority=None,
                    )
                self.assertEqual(ctx.exception.category, "worker_timeout")
                self.assertEqual(ctx.exception.publication_state, "not_started")

    def test_leaf_worker_heartbeat_timeout_surfaces_as_worker_timeout(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = self.config_for_roots(root)

            fake_worker = SimpleNamespace(
                terminal={
                    "status": "failed",
                    "reason": "heartbeat_timeout",
                    "summary": "synthetic heartbeat_timeout",
                }
            )
            with patch("repomap_kg.ops.portable_refresh.run_portable_worker", return_value=fake_worker):
                with self.assertRaises(PortableRefreshError) as ctx:
                    execute_portable_refresh(
                        config,
                        config.graphs[0],
                        "repomap_repo_map",
                        authority=None,
                    )
                self.assertEqual(ctx.exception.category, "worker_timeout")
                self.assertEqual(ctx.exception.publication_state, "not_started")

    def test_refresh_graph_leaf_worker_timeout_records_not_started(self):
        from types import SimpleNamespace
        from repomap_kg.ops.refresh import refresh_graph

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = self.config_for_roots(root)

            fake_worker = SimpleNamespace(
                terminal={
                    "status": "failed",
                    "reason": "process_timeout",
                    "summary": "synthetic process_timeout",
                }
            )
            with patch("repomap_kg.ops.portable_refresh.run_portable_worker", return_value=fake_worker):
                report = refresh_graph(config, config.graphs[0].id)
                self.assertEqual(report.result, "failure")
                self.assertEqual(report.publication_state, "not_started")
                self.assertEqual(report.error_category, "worker_timeout")

    def test_execute_portable_refresh_passes_authority_leaf_deadline_to_portable_worker(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            config = self.config_for_roots(root)
            graph = config.graphs[0]
            scan = scan_multi_source_generations(graph)
            authority = IngestionAuthority(
                operation_id=OperationId("job-leaf-test"),
                attempt=AttemptNumber(1),
                execution_mode="coordinator",
                source_generation=scan.source_generation,
                config_generation=scan.config_generation,
                extractor_generation=extractor_generation(graph),
                canonicalizer_generation=canonicalizer_generation(),
                job_id=JobId("job-leaf-test"),
                coordinator_instance_id="coord-leaf",
                singleton_fencing_epoch=1,
                graph_lease_fencing_epoch=1,
                process_deadline_seconds=42,
            )
            fake_worker = SimpleNamespace(
                terminal={
                    "status": "failed",
                    "reason": "process_timeout",
                    "summary": "synthetic process_timeout",
                }
            )
            with patch("repomap_kg.ops.portable_refresh.run_portable_worker", return_value=fake_worker) as spy:
                with self.assertRaises(PortableRefreshError):
                    execute_portable_refresh(
                        config,
                        config.graphs[0],
                        "repomap_repo_map",
                        authority=authority,
                    )
                self.assertTrue(spy.called)
                passed_limits = spy.call_args[0][2]
                self.assertEqual(passed_limits.process_deadline_seconds, 42)
