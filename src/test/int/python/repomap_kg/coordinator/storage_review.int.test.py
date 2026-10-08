from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import psycopg

from repomap_kg.coordinator import JobRequest
from repomap_kg.coordinator.configured_refresh import (
    ConfiguredRefreshResolver, build_configured_refresh_coordinator,
)
from repomap_test_support.test_scratch import short_test_directory
from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from repomap_kg.coordinator.storage import (
    ControlSchemaError,
    ControlStore,
)
from src.test.int.python.repomap_kg.coordinator.storage_review_fixtures import (
    StorageReviewIntegrationBase,
)


class ControlStoreReviewIntegrationTests(StorageReviewIntegrationBase):
    def test_configured_source_change_fails_durably_and_replay_keeps_original_identity(self):
        self.store.initialize_schema()
        with short_test_directory("r3-config-", "repository/main.py") as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            source = repository / "main.py"
            source.write_text("def first(): return 1\n", encoding="utf-8")
            config_path = root / "ops.toml"
            config_text = f'''schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[postgres]
host = "{self.postgres.host}"
port = {self.postgres.port}
database = "repomap_test"
user = "{self.postgres.user}"
[[graphs]]
id = "configured-review"
name = "Configured review"
root_path = "{repository}"
repository_name = "configured-review"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
'''
            config_path.write_text(config_text, encoding="utf-8")
            resolver = ConfiguredRefreshResolver(
                config_path, Path(self.postgres.psql_command),
                postgres_user=self.postgres.user, postgres_password=self.postgres.password,
            )
            payload = {
                "schema_version": 1, "job_kind": "refresh_graph",
                "graph_id": "configured-review", "request_id": "configured-original",
                "idempotency_key": "configured-original", "priority": "manual",
                "operation_options": {"reason": "source-change"},
            }
            original = resolver.resolve_request(payload)
            submitted = self.store.submit(original)
            source.write_text("def replacement(): return 2\n", encoding="utf-8")
            changed = resolver.resolve_request({
                **payload, "request_id": "configured-new", "idempotency_key": "configured-new",
            })
            self.assertNotEqual(changed.source_generation, original.source_generation)
            self.assertEqual(changed.config_generation, original.config_generation)
            coordinator = build_configured_refresh_coordinator(
                self.store, "configured-review-owner", resolver, root,
            )
            coordinator.startup(lambda: None)
            try:
                self.assertEqual(coordinator.run_once(), "failed")
                status = self.store.status(submitted.job_id)
                self.assertEqual(
                    (status.state, status.publication_state, status.error_category, status.attempt),
                    ("failed", "not_started", "generation_changed", 1),
                )
                replay = self.store.submit(original)
                self.assertTrue(replay.replayed)
                self.assertEqual((replay.job_id, replay.state), (submitted.job_id, "failed"))
                successor = self.store.submit(changed)
                self.assertFalse(successor.replayed)
                self.assertEqual(coordinator.request_cancel(successor.job_id), "cancelled")
                self.assertEqual(coordinator.run_once(), "idle")
                config_path.write_text(config_text.replace("enabled = true", "enabled = false"), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "^configured graph is unavailable$"):
                    resolver.resolve_request({**payload, "request_id": "disabled-request"})
                with self._connect() as connection:
                    rows = connection.execute(
                        "SELECT state, source_generation, current_attempt FROM jobs ORDER BY submitted_at, job_id"
                    ).fetchall()
                    self.assertEqual(rows, [
                        ("failed", original.source_generation, 1),
                        ("cancelled", changed.source_generation, 0),
                    ])
                    self.assertEqual(connection.execute("SELECT count(*) FROM graph_leases").fetchone(), (0,))
                    self.assertEqual(connection.execute("SELECT count(*) FROM job_attempts").fetchone(), (1,))
                self.assertEqual(tuple(root.glob("refresh-*.json")), ())
            finally:
                coordinator.shutdown()

    def test_submit_requires_revalidated_job_request_and_safe_json(self):
        self.store.initialize_schema()
        valid = self._request()

        with self.assertRaisesRegex(TypeError, "JobRequest"):
            self.store.submit(cast(JobRequest, valid.semantic_payload()))

        for prohibited_reason in (
            "/private/source.py",
            "postgresql://user:password@host/database",
            "credential=secret",
            "SELECT * FROM jobs",
            "command --unsafe",
        ):
            with self.subTest(prohibited_reason=prohibited_reason):
                unsafe = replace(
                    valid, operation_options=(("reason", prohibited_reason),)
                )
                with self.assertRaisesRegex(
                    ValueError, "prohibited|operation_options"
                ):
                    self.store.submit(unsafe)

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM jobs")
                row = cursor.fetchone()
                assert row is not None
                self.assertEqual(row[0], 0)

    def test_partial_override_migration_is_rejected_and_rolled_back(self):
        with self.assertRaisesRegex(ControlSchemaError, "incomplete|table set"):
            self.store.initialize_schema(
                migration_sql="""
                CREATE TABLE jobs(job_id text primary key);
                COMMENT ON TABLE jobs IS 'repomap-control-schema:1';
                """
            )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
                row = cursor.fetchone()
                assert row is not None
                self.assertEqual(row[0], 0)

    def test_schema_rejects_incompatible_state_publication_pairs(self):
        self.store.initialize_schema()
        submitted = self.store.submit(self._request())
        for state_name, publication_state in (
            ("succeeded", "not_started"),
            ("failed", "commit_unknown"),
            ("queued", "commit_unknown"),
        ):
            with self.subTest(
                state_name=state_name, publication_state=publication_state
            ):
                with self._connect() as connection:
                    with self.assertRaises(psycopg.errors.CheckViolation):
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "UPDATE jobs SET state = %s, publication_state = %s "
                                "WHERE job_id = %s",
                                (state_name, publication_state, submitted.job_id),
                            )

    def test_admission_limits_bound_nonterminal_and_manual_queues(self):
        limits = replace(
            DEFAULT_LIMITS,
            max_nonterminal_jobs=2,
            max_queued_manual_jobs_per_graph=1,
            cleanup_batch_size=2,
        )
        self.store = ControlStore(self._connect, limits=limits)
        self.store.initialize_schema()
        first = self.store.submit(self._request(key="one"))
        with self.assertRaisesRegex(ValueError, "manual queue limit"):
            self.store.submit(self._request(key="two"))
        self.store.submit(self._request(graph_id="synthetic-b", key="three"))
        with self.assertRaisesRegex(ValueError, "nonterminal job limit"):
            self.store.submit(self._request(graph_id="synthetic-c", key="four"))
        self.assertEqual(
            self.store.submit(self._request(key="one")).job_id, first.job_id
        )

    def test_automatic_hints_coalesce_without_touching_manual_jobs(self):
        self.store.initialize_schema()
        manual = self.store.submit(self._request(key="manual"))
        first = self.store.coalesce_automatic(
            self._request(key="auto-one", priority="automatic")
        )
        replay = self.store.coalesce_automatic(
            self._request(key="auto-one-copy", priority="automatic")
        )
        self.assertEqual(replay.job_id, first.job_id)
        second = self.store.coalesce_automatic(
            self._request(
                key="auto-two", priority="automatic", source_seed=b"new-source"
            )
        )
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT job_id, state FROM jobs ORDER BY submitted_at, job_id"
                )
                states = dict(cursor.fetchall())
                cursor.execute(
                    "SELECT queued_job_id, dirty FROM coalescing_state "
                    "WHERE graph_id = 'synthetic-a'"
                )
                queued = cursor.fetchone()
        self.assertEqual(states[manual.job_id], "queued")
        self.assertEqual(states[first.job_id], "superseded")
        self.assertEqual(states[second.job_id], "queued")
        self.assertEqual(queued, (second.job_id, True))
