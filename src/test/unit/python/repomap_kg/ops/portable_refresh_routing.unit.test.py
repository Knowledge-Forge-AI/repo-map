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
