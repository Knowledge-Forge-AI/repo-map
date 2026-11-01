"""Unit tests for lexical storage driver, probe, population, lifecycle, revoke, and PostgreSQL navigation parity (Units 1 & 2)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from common_lore_index.ops.config_records import OpsPostgresConfig
from common_lore_index.retrieval.lexical_capture import (
    LexicalCapturePlan,
    LexicalCapturedChunk,
    LexicalCapturedDocument,
)
from common_lore_index.retrieval.query_contracts import OmissionRecord
from common_lore_index.storage.lexical_driver import (
    DENIED_LEXICAL_ROLES,
    LexicalConnectionParameters,
    LexicalPostgresAuthority,
    LexicalRoleDeniedError,
    LexicalStorageError,
    execute_fetchall,
    execute_fetchone,
    lexical_connection_scope,
    sanitize_driver_exception,
)
from common_lore_index.storage.lexical_lifecycle import (
    parse_snapshot_vector_json,
    publish_lexical_generation,
    read_accepted_graph_publication,
)
from common_lore_index.storage.lexical_probe import probe_lexical_runtime
from common_lore_index.storage.lexical_query_sql import execute_single_statement_lexical_query
from common_lore_index.storage.lexical_revoke import revoke_lexical_generations
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
from common_lore_index.storage.postgres_navigation_search import (
    read_postgres_navigation_search_with_executor,
)
from common_lore_index.storage.postgres_node_locations import (
    read_postgres_node_locations_with_executor,
)


class _FakeCursor:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = responses
        self._current: Any = None
        self.description: Any = (("col",),)
        self.rowcount = 1
        self.executed: list[tuple[str, Any]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))
        if "SELECT pg_try_advisory_xact_lock" in sql:
            self._current = (True,)
            return
        if "SET lease_expires_at = clock_timestamp()" in sql:
            self._current = ("owned-building-generation",)
            return
        if self._responses:
            nxt = self._responses.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            self._current = nxt

    def fetchone(self) -> Any:
        return self._current

    def fetchall(self) -> list[Any]:
        return list(self._current) if isinstance(self._current, (list, tuple)) else []


class _FakeConnection:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.closed = False
        self.rolled_back = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.responses)

    def rollback(self) -> None:
        self.rolled_back = True

    def commit(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_lexical_driver_role_denial_and_error_sanitization() -> None:
    """Verify limited database roles are denied and driver errors are sanitized."""
    for role in DENIED_LEXICAL_ROLES:
        params = LexicalConnectionParameters(
            host="127.0.0.1", port=5432, database="db", user=role, password="pw"
        )
        with pytest.raises(LexicalRoleDeniedError, match=role):
            params.validate()
        auth = LexicalPostgresAuthority(
            postgres=OpsPostgresConfig(
                host="127.0.0.1", port=5432, database="db", user=role, password_env="PW"
            ),
            database="db",
            password="pw",
        )
        with pytest.raises(LexicalStorageError, match=role):
            auth.validate_owner_principal()

    valid = LexicalConnectionParameters(
        host="127.0.0.1", port=5432, database="db", user="repomap", password="pw", read_only=True
    )
    assert valid.connection_params()["dbname"] == "db"
    assert valid.connection_params()["connect_timeout"] == "5"
    assert "default_transaction_read_only=on" in str(valid.connection_params()["options"])
    assert "lock_timeout=500" in str(valid.connection_params()["options"])
    assert "statement_timeout=2000" in str(valid.connection_params()["options"])

    class _SqlError(Exception):
        def __init__(self, msg: str, sqlstate: str) -> None:
            super().__init__(msg)
            self.sqlstate = sqlstate

    assert sanitize_driver_exception(_SqlError("denied", "42501"), operation="q").code == "lexical_permission_denied"
    assert sanitize_driver_exception(_SqlError("no db", "3D000"), operation="q").code == "lexical_database_missing"
    assert sanitize_driver_exception(_SqlError("auth", "28P01"), operation="q").code == "lexical_authentication_failed"
    assert sanitize_driver_exception(_SqlError("conn", "08006"), operation="q").code == "lexical_connection_failed"
    assert sanitize_driver_exception(_SqlError("timeout", "57014"), operation="q").code == "lexical_statement_timeout"
    assert sanitize_driver_exception(_SqlError("lock", "55P03"), operation="q").code == "lexical_lock_not_available"
    assert sanitize_driver_exception(_SqlError("ro", "25006"), operation="q").code == "lexical_read_only_violation"
    assert (
        sanitize_driver_exception(
            RuntimeError("cloe_lexical_competing_builder_in_progress: active"),
            operation="publish",
        ).code
        == "cloe_lexical_competing_builder_in_progress"
    )
    assert (
        sanitize_driver_exception(
            RuntimeError("cloe_lexical_publication_fence_mismatch: stale"),
            operation="publish",
        ).code
        == "cloe_lexical_publication_fence_mismatch"
    )

    conn = _FakeConnection([[(1, "a"), (2, "b")], (99,)])
    with lexical_connection_scope(valid, connection_factory=lambda _p: conn) as active:
        rows = execute_fetchall(active, "SELECT 1")
        assert rows == [(1, "a"), (2, "b")]
        one = execute_fetchone(active, "SELECT 99")
        assert one == (99,)
    assert conn.closed is True


def test_lexical_probe_lifecycle_revoke_and_query_sql_execution() -> None:
    """Verify probe, lifecycle publication, revocation, and single-statement query SQL execution."""
    conn_ok = _FakeConnection([(160004, True, "cloe-lexical-schema:1", True, 5, 2, True)])
    probe_ok = probe_lexical_runtime(conn_ok).require_ready()
    assert probe_ok.ready is True

    conn_old = _FakeConnection([(150000, True, "cloe-lexical-schema:1", True, 5, 2, True)])
    probe_old = probe_lexical_runtime(conn_old)
    assert probe_old.ready is False
    assert probe_old.failure_reason == "postgres_version_unsupported"
    with pytest.raises(LexicalStorageError, match="postgres_version_unsupported"):
        probe_old.require_ready()

    vec = parse_snapshot_vector_json(
        '[{"binding_id": "b1", "revision": 1, "snapshot_id": "s1"}, ["b2", 2, "s2"]]'
    )
    assert vec == (("b1", 1, "s1"), ("b2", 2, "s2"))

    pub_conn = _FakeConnection(
        [
            (
                10,
                "mixed-v1",
                "repo:mixed-v1",
                3,
                "portable-worker-v1",
                "bundle1:b",
                "manifest1:m",
                "receipt1:r",
                "cand1:c",
                '[["b1", 1, "s1"]]',
                True,
            )
        ]
    )
    rec = read_accepted_graph_publication(
        pub_conn, repository_identity="repo:mixed-v1", repository_name="mixed-v1"
    )
    assert rec is not None and rec.run_id == 3
    assert rec.to_publication_fence().run_id == 3

    chunk = LexicalCapturedChunk(
        "pchunk1:1", "b1", 1, "s1", "pkg/a.py", 0, 1, 2, 10, "sha256:1", "x=1\n", "pkg a x", "public-dev"
    )
    doc = LexicalCapturedDocument(
        0, "b1", 1, "s1", "pkg/a.py", "sha256:doc", 4, 1, 1, "x=1\n", "public-dev", "portable-hash-and-span", (chunk,)
    )
    plan = LexicalCapturePlan(
        "lexgen1:g", 10, 3, "bundle1:b", "manifest1:m", "receipt1:r", "cand1:c",
        (("b1", 1, "s1"),), "cloe-lexical-pg-fts-v1", "pg_catalog.simple", "ts_rank_cd",
        32, "identifier-path-split-v1", "sha256:pol", "public-dev", {"b1": "sha256:bp"},
        ("b1",), (), (doc,), (OmissionRecord("b2", None, "binding_privacy_not_authorized", "priv"),),
        4, 4,
    )
    life_conn = _FakeConnection(
        [
            None, None, None, None,
            (3, "portable-worker-v1", "bundle1:b", "manifest1:m", "receipt1:r", "cand1:c", '[["b1", 1, "s1"]]', True,
             "{}", True, True, True),
            None, None, None, None, None, None,
        ]
    )
    summary = publish_lexical_generation(life_conn, plan)
    assert summary.to_dict()["lexical_generation_id"] == "lexgen1:g"

    rev_conn = _FakeConnection([(10,), None, None, None, None, [("lexgen1:g",)], None])
    rev_sum = revoke_lexical_generations(rev_conn, repository_identity="repo:mixed-v1", reason="test")
    assert rev_sum.revoked_generation_ids == ("lexgen1:g",)

    dry_conn = _FakeConnection([(10,), (1,), (8,), (4,), (1,), [("lexgen1:g",)]])
    dry_sum = revoke_lexical_generations(
        dry_conn, repository_identity="repo:mixed-v1", reason="test", dry_run=True
    )
    assert dry_sum.revoked_generation_ids == ("lexgen1:g",)
    assert dry_sum.purged_chunk_count == 8

    q_payload = {
        "fence_status": "ok",
        "lexical_generation_id": "lexgen1:g",
        "run_id": 3,
        "publication_bundle_id": "bundle1:b",
        "snapshot_manifest_id": "manifest1:m",
        "extraction_receipt_id": "receipt1:r",
        "graph_candidate_id": "cand1:c",
        "empty_tsquery": False,
        "total_matches": 1,
        "capped_files": [],
        "omissions": [],
        "hits": [],
    }
    q_conn = _FakeConnection([(json.dumps(q_payload),)])
    raw_row = execute_single_statement_lexical_query(
        q_conn,
        repository_identity="repo:mixed-v1",
        repository_name="mixed-v1",
        root_path="graph:mixed-v1",
        expected_policy_digest="sha256:pol",
        expected_binding_policy_digests_json='{"b1":"sha256:bp"}',
        admitted_binding_ids=("b1",),
        omission_binding_ids=("b1",),
        path_prefixes=("pkg/",),
        query_style="ranked_terms",
        query_text="alpha",
        limit=10,
        offset=0,
    )
    assert raw_row.fence_status == "ok"


def test_postgres_navigation_and_node_locations_executor_parity() -> None:
    """Verify single-statement PostgreSQL node_locations and navigation_search JSON executors."""
    ev_row = {
        "evidence_key": "ev1",
        "link_kind": "defined_in",
        "run_id": 4,
        "raw_observation_ordinal": 1,
        "payload_hash": "sha256:1",
        "raw_kind": "file",
        "raw_source_id": "src1:a",
        "path": "core/pkg/pipeline.py",
        "start_line": 1,
        "end_line": 30,
        "extractor": "python-ast",
        "extractor_version": "1.0",
        "confidence": "1.0",
        "metadata_json": {
            "source_binding_id": "bind1:a",
            "source_binding_revision": 1,
            "source_snapshot_id": "snap1:a",
            "source_relative_path": "pkg/pipeline.py",
        },
        "publication_bundle_id": "bundle1:b",
        "snapshot_manifest_id": "manifest1:m",
        "extraction_receipt_id": "receipt1:r",
        "graph_candidate_id": "cand1:c",
        "snapshot_vector_json": [
            {"binding_id": "bind1:a", "revision": 1, "snapshot_id": "snap1:a"}
        ],
        "evidence_role": "direct",
        "node_id": 10,
    }
    loc_payload = {
        "has_accepted": True,
        "accepted": {
            "generation": 1,
            "run_id": 4,
            "publication_bundle_id": "bundle1:b",
        },
        "has_node": True,
        "node": {
            "id": 10,
            "metadata_json": {},
            "first_seen_run_id": 4,
            "last_seen_run_id": 4,
        },
        "selected_run_id": 4,
        "current_rows": [ev_row],
        "historical_rows": [],
    }
    loc_res = read_postgres_node_locations_with_executor(
        NodeLocationsQuery(canonical_key="file:core/pkg/pipeline.py", limit=5),
        executor=lambda _sql: loc_payload,
        repository_identity="repo:mixed-v1",
        root_path="graph:mixed-v1",
    )
    assert loc_res["status"] == "ok"
    assert len(loc_res["locations"]) == 1

    nav_payload = {
        "has_accepted": True,
        "accepted": loc_payload["accepted"],
        "candidate_nodes": [
            {
                "id": 10,
                "canonical_key": "file:core/pkg/pipeline.py",
                "kind": "file",
                "display_name": "pipeline.py",
                "first_seen_run_id": 4,
                "last_seen_run_id": 4,
            }
        ],
        "direct_evidence": [ev_row],
    }
    nav_res = read_postgres_navigation_search_with_executor(
        NavigationSearchQuery(query="pipeline.py", scope="all", limit=5),
        executor=lambda _sql: nav_payload,
        repository_identity="repo:mixed-v1",
        root_path="graph:mixed-v1",
    )
    assert nav_res["status"] == "ok"
    assert len(nav_res["nodes"]) == 1

    # Transport overflow under source_binding_id scope returns incomplete admission_work_limit (M4)
    overflow_res = read_postgres_navigation_search_with_executor(
        NavigationSearchQuery(query="pipeline", scope="all", source_binding_id="bind1:a", limit=5),
        executor=lambda _sql: {**nav_payload, "transport_overflow": True},
        admits_location=lambda _loc: True,
        repository_identity="repo:mixed-v1",
        root_path="graph:mixed-v1",
    )
    assert overflow_res["status"] == "incomplete"
    assert overflow_res["reason"] == "admission_work_limit"
