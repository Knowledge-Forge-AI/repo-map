from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
from threading import Event
from types import SimpleNamespace
import time
from typing import Sequence
import uuid

import psycopg

from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.coordinator.contracts import normalize_request
from repomap_kg.coordinator.desired_state import DesiredStateReconciler
from repomap_kg.coordinator.polling import PollingScheduler
from repomap_kg.coordinator.storage import ControlStore
from repomap_kg.ops.source_generation import (
    SourceGenerationLimits, SourceGenerationResult, scan_source_generation,
)
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _generation(prefix: str, value: str) -> str:
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()


class _PollingResolver:
    def __init__(self) -> None:
        self.source = SourceGenerationResult("ready", _generation("sg1:", "one"), 2, 10)
        self.publication: dict[str, object] | None = None

    def polling_snapshot(
        self, graph_id: str, *, cancel_event: Event | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(
            graph_id=graph_id,
            refresh_policy="polling",
            source=self.source,
            config_generation=_generation("cg1:", "config"),
            extractor_generation=_generation("eg1:", "extractor"),
            canonicalizer_generation=_generation("kg1:", "canonicalizer"),
        )

    def latest_publication(self, _graph_id: str) -> dict[str, object] | None:
        return self.publication


class _MultiGraphPollingResolver:
    def __init__(
        self, graph_ids: Sequence[str], unavailable: Sequence[str] = ()
    ) -> None:
        self.graph_ids = tuple(graph_ids)
        self.unavailable = set(unavailable)

    def polling_graphs(self) -> tuple[tuple[str, str], ...]:
        return tuple((graph_id, "polling") for graph_id in reversed(self.graph_ids))

    def polling_snapshot(
        self, graph_id: str, *, cancel_event: Event | None = None
    ) -> SimpleNamespace:
        if graph_id in self.unavailable:
            source = SourceGenerationResult("source_unavailable", None, 0, 0)
        else:
            source = SourceGenerationResult(
                "ready", _generation("sg1:", graph_id), 1, len(graph_id)
            )
        return SimpleNamespace(
            graph_id=graph_id,
            refresh_policy="polling",
            source=source,
            config_generation=_generation("cg1:", graph_id),
            extractor_generation=_generation("eg1:", "extractor"),
            canonicalizer_generation=_generation("kg1:", "canonicalizer"),
        )

    def latest_publication(self, _graph_id: str) -> dict[str, object] | None:
        return None


class _FilesystemPollingResolver(_PollingResolver):
    """Exercise real bounded inventory with the durable reconciliation store."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.limits = SourceGenerationLimits(chunk_bytes=3)

    def polling_snapshot(
        self, graph_id: str, *, cancel_event: Event | None = None
    ) -> SimpleNamespace:
        self.source = scan_source_generation(
            self.root, exclude_paths=("generated/*", "*.cache", "vendor"),
            limits=self.limits, cancel_event=cancel_event,
        )
        return super().polling_snapshot(graph_id, cancel_event=cancel_event)


def _request(source: str, *, graph_id: str = "polling-graph"):
    return normalize_request(
        {
            "schema_version": 1,
            "job_kind": "refresh_graph",
            "graph_id": graph_id,
            "request_id": "polling-request",
            "idempotency_key": "polling-key-" + source[-8:],
            "priority": "automatic",
            "operation_options": {"reason": "polling"},
        },
        source_generation=source,
        config_generation=_generation("cg1:", "config"),
        extractor_generation=_generation("eg1:", "extractor"),
        canonicalizer_generation=_generation("kg1:", "canonicalizer"),
        require_synthetic_graph=False,
    )


class TestDesiredStateControlIntegration:
    def test_filesystem_polling_preserves_identity_and_refuses_unsafe_inventory(self):
        with tempfile.TemporaryDirectory(prefix="repomap-poll-inventory-") as temporary:
            root = Path(temporary) / "source"
            root.mkdir()
            (root / "lib").mkdir()
            source = root / "lib" / "deploy.sh"
            source.write_text("echo first\n", encoding="utf-8")
            for directory in ("generated", "vendor", ".git"):
                (root / directory).mkdir()
                (root / directory / "ignored.sh").write_text("ignored", encoding="utf-8")
            (root / "build.cache").write_text("ignored", encoding="utf-8")
            resolver = _FilesystemPollingResolver(root)
            reconciler = DesiredStateReconciler(resolver, self.store)
            first = reconciler.reconcile_graph("filesystem-graph")
            assert first.to_public() == {
                "category": "refresh_requested", "refresh_requested": True,
                "file_count": 1, "total_bytes": len(b"echo first\n"),
            }
            initial_generation = resolver.source.generation
            (root / "generated" / "ignored.sh").write_text("changed", encoding="utf-8")
            assert reconciler.reconcile_graph("filesystem-graph").category == "refresh_coalesced"
            assert resolver.source.generation == initial_generation
            source.write_text("echo second\n", encoding="utf-8")
            assert reconciler.reconcile_graph("filesystem-graph").category == "refresh_requested"
            assert resolver.source.generation != initial_generation
            with self._connect() as connection:
                assert connection.execute(
                    "SELECT state FROM jobs WHERE graph_id = %s ORDER BY submitted_at, job_id",
                    ("filesystem-graph",),
                ).fetchall() == [("superseded",), ("queued",)]
            resolver.publication = {
                "source_generation": resolver.source.generation,
                "config_generation": _generation("cg1:", "config"),
                "extractor_generation": _generation("eg1:", "extractor"),
                "canonicalizer_generation": _generation("kg1:", "canonicalizer"),
            }
            assert reconciler.reconcile_graph("filesystem-graph").category == "current"
            unsafe = root / "linked.sh"
            unsafe.symlink_to(source)
            assert reconciler.reconcile_graph("filesystem-graph").category == "source_invalid"
            unsafe.unlink()
            for limits in (
                SourceGenerationLimits(max_file_bytes=3),
                SourceGenerationLimits(max_total_bytes=3),
            ):
                resolver.limits = limits
                outcome = reconciler.reconcile_graph("filesystem-graph")
                assert outcome.category == "source_limit_exceeded"
                assert not outcome.refresh_requested
                assert resolver.source.generation is None
            resolver.limits = SourceGenerationLimits(chunk_bytes=3)
            assert reconciler.reconcile_graph("filesystem-graph").category == "current"
            resolver.publication = {"source_generation": initial_generation}
            assert reconciler.reconcile_graph("filesystem-graph").category == "publication_unavailable"
            reconciler.cancel()
            assert reconciler.reconcile_graph("filesystem-graph").category == "cancelled"
            with self._connect() as connection:
                assert connection.execute(
                    "SELECT count(*) FROM jobs WHERE graph_id = %s", ("filesystem-graph",),
                ).fetchone() == (2,)
                assert connection.execute(
                    "SELECT reason_categories FROM coalescing_state WHERE graph_id = %s",
                    ("filesystem-graph",),
                ).fetchone() == (["publication_unavailable"],)

    def setup_method(self):
        require_postgres_binaries()
        self.postgres_context = temporary_postgres()
        self.postgres = self.postgres_context.__enter__()
        self.store = ControlStore(self._connect)
        self.store.initialize_schema()

    def teardown_method(self):
        self.postgres_context.__exit__(None, None, None)

    def _connect(self):
        return psycopg.connect(
            host=self.postgres.host,
            port=self.postgres.port,
            user=self.postgres.user,
            dbname=self.postgres.database,
            password=self.postgres.password,
        )

    def test_actual_generations_and_condition_updates_are_durable(self):
        request = _request(_generation("sg1:", "one"))
        submitted = self.store.coalesce_automatic(request, requester="polling")

        with self._connect() as connection:
            row = connection.execute(
                "SELECT source_generation, config_generation, "
                "extractor_generation, canonicalizer_generation "
                "FROM jobs WHERE job_id = %s",
                (submitted.job_id,),
            ).fetchone()
        assert row == (
            request.source_generation,
            request.config_generation,
            request.extractor_generation,
            request.canonicalizer_generation,
        )

        assert self.store.record_reconciliation_condition(
            "polling-graph", "source_unavailable", next_reconcile_seconds=15
        )
        assert self.store.record_reconciliation_current(
            "polling-graph",
            (
                request.source_generation,
                request.config_generation,
                request.extractor_generation,
                request.canonicalizer_generation,
            ),
            next_reconcile_seconds=60,
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT desired_source_generation, dirty, reason_categories, "
                "next_reconcile_at IS NOT NULL FROM coalescing_state "
                "WHERE graph_id = 'polling-graph'"
            ).fetchone()
        assert row == (request.source_generation, False, ["current"], True)

    def test_reconciliation_coalesces_duplicate_and_changed_polls(self):
        resolver = _PollingResolver()
        reconciler = DesiredStateReconciler(resolver, self.store)

        first = reconciler.reconcile_graph("polling-graph")
        replay = reconciler.reconcile_graph("polling-graph")
        assert first.category == "refresh_requested"
        assert replay.category == "refresh_coalesced"

        resolver.source = SourceGenerationResult(
            "ready", _generation("sg1:", "two"), 2, 11
        )
        changed = reconciler.reconcile_graph("polling-graph")
        assert changed.category == "refresh_requested"
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT state FROM jobs WHERE graph_id = 'polling-graph' "
                "ORDER BY submitted_at, job_id"
            ).fetchall()
        assert [row[0] for row in rows] == ["superseded", "queued"]

        resolver.source = SourceGenerationResult("source_unavailable", None, 2, 11)
        unavailable = reconciler.reconcile_graph("polling-graph")
        assert unavailable.category == "source_unavailable"
        with self._connect() as connection:
            row = connection.execute(
                "SELECT count(*), max(reason_categories[1]) "
                "FROM coalescing_state WHERE graph_id = 'polling-graph'"
            ).fetchone()
        assert row == (1, "source_unavailable")

    def test_multi_graph_scheduler_bounds_startup_and_preserves_unavailable_graphs(self):
        graph_ids = ("alpha", "beta", "gamma", "delta")
        resolver = _MultiGraphPollingResolver(graph_ids, unavailable=("beta",))
        scheduler = PollingScheduler(
            resolver,
            DesiredStateReconciler(resolver, self.store),
            interval_seconds=10,
            retry_seconds=0.2,
            jitter_seconds=0,
            max_concurrent_polls=2,
            startup_batch=2,
            scheduler_wake_seconds=0.01,
        )
        scheduler.start()
        try:
            deadline = time.monotonic() + 3
            while True:
                completed = scheduler.health()["polls_completed"]
                assert isinstance(completed, int)
                if completed >= len(graph_ids):
                    break
                assert time.monotonic() < deadline
                time.sleep(0.01)
            health = scheduler.health()
            assert health["poll_capacity"] == 2
            assert health["startup_backlog"] == 0
            assert health["automatic_refreshes_requested"] == 3
            polls_unavailable = health["polls_unavailable"]
            assert isinstance(polls_unavailable, int)
            assert polls_unavailable >= 1
        finally:
            scheduler.stop()

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT graph_id, state FROM jobs "
                "WHERE priority_class = 'automatic' ORDER BY graph_id"
            ).fetchall()
        assert rows == [("alpha", "queued"), ("delta", "queued"), ("gamma", "queued")]

    def test_configured_refresh_resolver_reconciliation_and_stale_generation(self, monkeypatch):
        with tempfile.TemporaryDirectory(prefix="repomap-poll-cfg-") as temporary:
            root, repo = Path(temporary), Path(temporary) / "repo"
            repo.mkdir()
            (repo / "entry.py").write_text("print('v1')\n", encoding="utf-8")
            monkeypatch.setenv("REPOMAP_POLLING_TEST_PASSWORD", self.postgres.password)
            graph_pg = self.postgres.create_database(f"repomap_poll_{uuid.uuid4().hex[:8]}")
            graph_db = graph_pg.database
            try:
                apply_migrations(default_rdbms_root(), graph_pg.psql_args,
                                 psql_command=graph_pg.psql_command)
                config_path = root / "configured.rp.toml"
                config_path.write_text(f'''schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[postgres]
host = "{self.postgres.host}"
port = {self.postgres.port}
database = "{graph_pg.database}"
user = "{self.postgres.user}"
password_env = "REPOMAP_POLLING_TEST_PASSWORD"
[[graphs]]
id = "cfg-poll"
name = "Configured Polling"
root_path = "{repo}"
repository_name = "cfg-poll"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "polling"
[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
''', encoding="utf-8")
                resolver = ConfiguredRefreshResolver(config_path, Path(self.postgres.psql_command))
                reconciler = DesiredStateReconciler(resolver, self.store)
                first = reconciler.reconcile_graph("cfg-poll")
                assert first.category == "refresh_requested" and first.refresh_requested
                replay = reconciler.reconcile_graph("cfg-poll")
                assert replay.category == "refresh_coalesced" and not replay.refresh_requested
                with psycopg.connect(
                    host=graph_pg.host, port=graph_pg.port, user=graph_pg.user,
                    dbname=graph_pg.database, password=graph_pg.password,
                ) as connection:
                    snap = resolver.polling_snapshot("cfg-poll")
                    source_generation = snap.source.generation
                    assert source_generation is not None
                    repository = connection.execute(
                        "INSERT INTO repositories(name, root_path) VALUES (%s, %s) RETURNING id",
                        ("cfg-poll", str(repo)),
                    ).fetchone()
                    assert repository is not None
                    connection.execute(
                        "INSERT INTO runs (repository_id, status, finished_at, "
                        "publication_job_id, publication_attempt, "
                        "source_generation, config_generation, extractor_generation, canonicalizer_generation) "
                        "VALUES (%s, 'complete', now(), 'job-prev', 1, %s, %s, %s, %s)",
                        (repository[0], source_generation, snap.config_generation,
                         snap.extractor_generation, snap.canonicalizer_generation),
                    )
                assert reconciler.reconcile_graph("cfg-poll").category == "current"
                (repo / "entry.py").write_text("print('v2')\n", encoding="utf-8")
                drifted = reconciler.reconcile_graph("cfg-poll")
                assert drifted.category == "refresh_requested" and drifted.refresh_requested
                assert reconciler.reconcile_graph("missing-graph").category == "configuration_invalid"
            finally:
                self.postgres.psql_scalar(
                    f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    f"WHERE datname = '{graph_db}' AND pid <> pg_backend_pid();"
                )
                self.postgres.psql_scalar(f'DROP DATABASE IF EXISTS "{graph_db}";')
                assert self.postgres.psql_scalar(
                    f"SELECT count(*) FROM pg_database WHERE datname = '{graph_db}';"
                ) == "0"
            with self._connect() as control_connection:
                assert control_connection.execute(
                    "SELECT to_regclass('public.repositories')"
                ).fetchone() == (None,)
