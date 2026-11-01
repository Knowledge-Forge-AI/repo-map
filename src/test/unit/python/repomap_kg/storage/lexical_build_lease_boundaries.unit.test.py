"""Unit proofs for owned cloe_lexical claims, leases, fences, and cleanup."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from common_lore_index.storage import lexical_lifecycle as lifecycle
from common_lore_index.storage.lexical_build_lease import (
    acquire_repository_lifecycle_lock,
    cleanup_owned_lexical_generation,
    refresh_lexical_build_lease,
)
from common_lore_index.storage.lexical_driver import LexicalStorageError
from common_lore_index.storage.lexical_population import claim_lexical_generation


class _Cursor:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.current: Any = None
        self.rowcount = 1
        self.description = (("value",),)

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.connection.executed.append((sql, params))
        compact = " ".join(sql.split())
        self.rowcount = 1
        self.current = None
        if compact.startswith("SELECT pg_try_advisory_xact_lock"):
            self.current = self.connection.lock_row
        elif compact.startswith("INSERT INTO cloe_lexical.generations"):
            self.rowcount = self.connection.insert_rowcount
            self.current = ("claimed",) if self.rowcount else None
        elif "SET lease_expires_at" in compact:
            self.current = self.connection.lease_row
            self.rowcount = 1 if self.current is not None else 0
        elif "SELECT state, builder_owner_id" in compact:
            self.current = self.connection.cleanup_row
        elif "SET state = 'invalidated'" in compact:
            self.rowcount = self.connection.cleanup_update_rowcount
        elif compact.startswith("SELECT") and "FROM public.runs" in compact:
            self.current = self.connection.verify_row
        elif compact.startswith("DELETE FROM"):
            self.rowcount = 1

    def fetchone(self) -> Any:
        return self.current

    def fetchall(self) -> list[Any]:
        return list(self.current) if isinstance(self.current, (list, tuple)) else []


class _Connection:
    def __init__(self) -> None:
        self.lock_row: Any = (True,)
        self.insert_rowcount = 1
        self.lease_row: Any = ("lexgen1:" + "1" * 64,)
        self.cleanup_row: Any = ("building", "owner-a")
        self.cleanup_update_rowcount = 1
        self.verify_row: Any = None
        self.executed: list[tuple[str, Any]] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _plan() -> Any:
    binding_id = "bind1:" + "2" * 64
    snapshot_id = "snap1:" + "3" * 64
    return SimpleNamespace(
        lexical_generation_id="lexgen1:" + "4" * 64,
        repository_id=17,
        run_id=9,
        publication_bundle_id="bundle1:" + "5" * 64,
        snapshot_manifest_id="snapmanifest1:" + "6" * 64,
        extraction_receipt_id="receipt1:" + "7" * 64,
        graph_candidate_id="cand1:" + "8" * 64,
        snapshot_vector=((binding_id, 1, snapshot_id),),
        representation_version="cloe-lexical-pg-fts-v1",
        text_config_regconfig="pg_catalog.simple",
        ranking_function="ts_rank_cd(weight={0.1,0.2,0.4,1.0},normalization=32)",
        normalization_flags=32,
        alias_split_rule_version="identifier-path-split-v1",
        policy_digest="sha256:" + "9" * 64,
        resolved_graph_privacy="public-dev",
        binding_policy_digests={binding_id: "sha256:" + "a" * 64},
        admitted_binding_ids=(binding_id,),
        excluded_binding_ids=(),
        documents=(),
        omissions=(),
        aggregate_input_bytes=0,
        aggregate_projected_bytes=0,
        projected_document_count=0,
        projected_chunk_count=0,
        omitted_record_count=0,
        publication_receipt_json="{}",
    )


def _fence_row(
    *,
    run_id: int = 9,
    no_competing: bool = True,
    counts_valid: bool = True,
) -> tuple[Any, ...]:
    plan = _plan()
    return (
        run_id,
        "portable-worker-v1",
        plan.publication_bundle_id,
        plan.snapshot_manifest_id,
        plan.extraction_receipt_id,
        plan.graph_candidate_id,
        '[["' + plan.snapshot_vector[0][0] + '",1,"' + plan.snapshot_vector[0][2] + '"]]',
        True,
        "{}",
        True,
        no_competing,
        counts_valid,
    )


def test_lifecycle_lock_fails_closed_for_false_and_malformed_rows() -> None:
    """A missing, malformed, or false advisory-lock result cannot admit mutation."""
    for lock_row in ((False,), (None,), ()):
        connection = _Connection()
        connection.lock_row = lock_row
        with pytest.raises(LexicalStorageError) as error:
            acquire_repository_lifecycle_lock(connection, 17)
        assert error.value.code == "cloe_lexical_competing_builder_in_progress"


def test_claim_rejects_active_or_reused_generation_without_destructive_delete() -> None:
    """A real claim conflict is surfaced and never replaces an existing ready identity."""
    connection = _Connection()
    connection.insert_rowcount = 0
    with pytest.raises(LexicalStorageError) as error:
        claim_lexical_generation(connection, _plan(), builder_owner_id="owner-b")
    assert error.value.code == "cloe_lexical_competing_builder_in_progress"
    assert not any("DELETE FROM cloe_lexical.generations" in sql for sql, _ in connection.executed)
    insert_sql = next(sql for sql, _ in connection.executed if "INSERT INTO cloe_lexical.generations" in sql)
    assert "state = 'building'" in insert_sql
    assert "lease_expires_at" in insert_sql and "clock_timestamp()" in insert_sql


def test_expired_owner_lease_and_cleanup_owner_fences_are_distinct() -> None:
    """Expiry blocks the old owner, while cleanup rejects cross-owner custody."""
    connection = _Connection()
    connection.lease_row = None
    with pytest.raises(LexicalStorageError) as error:
        refresh_lexical_build_lease(
            connection,
            repository_id=17,
            lexical_generation_id=_plan().lexical_generation_id,
            builder_owner_id="owner-a",
        )
    assert error.value.code == "cloe_lexical_build_lease_lost"
    assert any("builder_owner_id" in sql and "clock_timestamp()" in sql for sql, _ in connection.executed)

    connection = _Connection()
    connection.cleanup_row = ("building", "owner-b")
    with pytest.raises(LexicalStorageError) as error:
        cleanup_owned_lexical_generation(
            connection,
            repository_id=17,
            lexical_generation_id=_plan().lexical_generation_id,
            builder_owner_id="owner-a",
        )
    assert error.value.code == "cloe_lexical_cleanup_owner_mismatch"
    assert not any(sql.lstrip().startswith("DELETE FROM") for sql, _ in connection.executed)


def test_cleanup_clears_owned_custody_and_all_body_families() -> None:
    """Owned failed rows purge authority/body families and commit invalidation custody."""
    connection = _Connection()
    cleanup_owned_lexical_generation(
        connection,
        repository_id=17,
        lexical_generation_id=_plan().lexical_generation_id,
        builder_owner_id="owner-a",
    )
    deleted = " ".join(sql for sql, _ in connection.executed)
    for table in ("authority", "chunks", "documents", "omissions"):
        assert f"cloe_lexical.{table}" in deleted
    update_sql = next(sql for sql, _ in connection.executed if "SET state = 'invalidated'" in sql)
    assert "builder_owner_id = NULL" in update_sql
    assert "lease_expires_at = NULL" in update_sql
    assert connection.commits == 1

    published = _Connection()
    published.cleanup_row = ("published", None)
    with pytest.raises(LexicalStorageError) as error:
        cleanup_owned_lexical_generation(
            published,
            repository_id=17,
            lexical_generation_id=_plan().lexical_generation_id,
            builder_owner_id="owner-a",
        )
    assert error.value.code == "cloe_lexical_cleanup_published_generation"
    assert not any(sql.lstrip().startswith("DELETE FROM") for sql, _ in published.executed)


@pytest.mark.parametrize(
    ("code", "fence"),
    (
        ("cloe_lexical_concurrent_build_active", _fence_row(no_competing=False)),
        ("cloe_lexical_count_verification_failed", _fence_row(counts_valid=False)),
        ("cloe_lexical_publication_fence_mismatch", _fence_row(run_id=10)),
    ),
)
def test_final_activation_fences_competition_expiry_and_newer_publication(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    fence: tuple[Any, ...],
) -> None:
    """Actual publication logic refuses each owned-state race before activation writes."""
    connection = _Connection()
    connection.verify_row = fence
    monkeypatch.setattr(lifecycle, "claim_lexical_generation", lambda *_a, **_k: None)
    monkeypatch.setattr(lifecycle, "populate_lexical_generation_rows", lambda *_a, **_k: None)
    with pytest.raises(LexicalStorageError) as error:
        lifecycle.publish_lexical_generation(
            connection,
            _plan(),
            builder_owner_id="owner-a",
        )
    assert error.value.code == code
    verify_sql = next(sql for sql, _ in connection.executed if "FROM public.runs lc" in sql)
    assert "builder_owner_id" in verify_sql and "clock_timestamp()" in verify_sql
    assert not any("INSERT INTO cloe_lexical.authority" in sql for sql, _ in connection.executed)
