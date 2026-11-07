"""Disposable PostgreSQL proofs for owned lexical build races and cleanup."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_publication import (
    build_and_publish_lexical_generation,
    lexical_connection_parameters,
    resolve_ops_graph,
)
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
)
from common_lore_index.retrieval.lexical_capture import LexicalCapturePlan
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.storage import lexical_lifecycle as lifecycle
from common_lore_index.storage.lexical_build_lease import (
    cleanup_owned_lexical_generation,
)
from common_lore_index.storage.lexical_driver import (
    LexicalStorageError,
    execute_fetchall,
    execute_fetchone,
    lexical_connection_scope,
)
from common_lore_index.storage.lexical_population import (
    claim_lexical_generation,
    populate_lexical_generation_rows,
)
from common_lore_index.storage.lexical_revoke import revoke_lexical_generations
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
)


def _disable_companion(text: str) -> str:
    """Edit only the maintained companion binding in a disposable TOML home."""
    header, *blocks = text.split("[[graphs.source_bindings]]")
    for index, block in enumerate(blocks):
        if 'alias = "companion"' in block:
            blocks[index] = block.replace("enabled = true", "enabled = false", 1)
            break
    return "[[graphs.source_bindings]]".join((header, *blocks))


def _attempt_plan(plan: LexicalCapturePlan, owner: str) -> LexicalCapturePlan:
    """Frame deterministic capture identity with one disposable owned attempt."""
    return replace(
        plan,
        lexical_generation_id=(
            "lexgen1:"
            + hashlib.sha256(
                f"{plan.lexical_generation_id}\0{owner}".encode("utf-8")
            ).hexdigest()
        ),
    )


def _fixture_home(tmp_path: Path, pg_db: Any) -> tuple[Path, OpsConfig]:
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    home = write_mixed_v1_postgres_home(
        tmp_path / "home",
        working_copy,
        host=pg_db.host,
        port=pg_db.port,
        database=pg_db.database,
        user=pg_db.user,
        password=pg_db.password,
        declared_aliases=("core", "companion"),
    )
    publish_and_load_postgres_corpus(home, psql_command=pg_db.psql_command)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, OpsConfig)
    return home, config


def test_real_owned_claim_expiry_revoke_and_repeat_identity_fences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real accepted publication rows survive competing, expired, revoked, and repeat attempts."""
    with temporary_postgres() as pg_db:
        home, config = _fixture_home(tmp_path, pg_db)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        params = lexical_connection_parameters(config, graph)
        core_id = binding_id_for_alias("core")
        companion_id = binding_id_for_alias("companion")

        first = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id, companion_id),
            authorize_body=True,
        )
        assert first.result == "published" and first.published is not None and first.plan is not None
        ready_id = first.published.lexical_generation_id
        owner_a_plan = _attempt_plan(first.plan, "owner-a")

        # Actual claim admission: the committed owner-a row blocks owner-b.
        with lexical_connection_scope(params) as conn:
            claim_lexical_generation(conn, owner_a_plan, builder_owner_id="owner-a")
        with lexical_connection_scope(params) as conn:
            with pytest.raises(LexicalStorageError) as competing:
                claim_lexical_generation(
                    conn,
                    _attempt_plan(first.plan, "owner-b"),
                    builder_owner_id="owner-b",
                )
        assert competing.value.code == "cloe_lexical_competing_builder_in_progress"

        with lexical_connection_scope(params) as conn:
            cleanup_owned_lexical_generation(
                conn,
                repository_id=owner_a_plan.repository_id,
                lexical_generation_id=owner_a_plan.lexical_generation_id,
                builder_owner_id="owner-a",
            )
            authority = execute_fetchone(
                conn,
                "SELECT lexical_generation_id FROM cloe_lexical.authority WHERE repository_id = %s",
                (owner_a_plan.repository_id,),
            )
            assert authority == (ready_id,)

        # Reusing the exact deterministic identity cannot delete the ready rows.
        with lexical_connection_scope(params) as conn:
            with pytest.raises(LexicalStorageError) as reused:
                claim_lexical_generation(conn, first.plan, builder_owner_id="owner-repeat")
        assert reused.value.code == "cloe_lexical_competing_builder_in_progress"
        with lexical_connection_scope(params) as conn:
            ready_counts = execute_fetchone(
                conn,
                "SELECT count(*) FROM cloe_lexical.documents WHERE lexical_generation_id = %s",
                (ready_id,),
            )
            assert ready_counts == (first.plan.projected_document_count,)

        # Populate one real committed batch, then expire only its owned lease.
        expired_plan = _attempt_plan(first.plan, "owner-expired")
        with lexical_connection_scope(params) as conn:
            claim_lexical_generation(conn, expired_plan, builder_owner_id="owner-expired")
            populate_lexical_generation_rows(
                conn,
                expired_plan,
                builder_owner_id="owner-expired",
                batch_size=1,
                claim_generation=False,
            )
            with conn.cursor() as cur:
                # Race fixture: mutate only the owned generation after its committed batch.
                cur.execute(
                    """
                    UPDATE cloe_lexical.generations
                    SET lease_expires_at = clock_timestamp() - interval '1 second'
                    WHERE repository_id = %s
                      AND lexical_generation_id = %s
                      AND builder_owner_id = %s
                    """,
                    (expired_plan.repository_id, expired_plan.lexical_generation_id, "owner-expired"),
                )
            conn.commit()
        monkeypatch.setattr(lifecycle, "claim_lexical_generation", lambda *_a, **_k: None)
        monkeypatch.setattr(lifecycle, "populate_lexical_generation_rows", lambda *_a, **_k: None)
        with lexical_connection_scope(params) as conn:
            with pytest.raises(LexicalStorageError) as expired:
                lifecycle.publish_lexical_generation(conn, expired_plan, builder_owner_id="owner-expired")
        assert expired.value.code == "cloe_lexical_count_verification_failed"
        with lexical_connection_scope(params) as conn:
            cleanup_owned_lexical_generation(
                conn,
                repository_id=expired_plan.repository_id,
                lexical_generation_id=expired_plan.lexical_generation_id,
                builder_owner_id="owner-expired",
            )

        # Revoke after another committed batch; the old owner cannot activate afterward.
        revoked_plan = _attempt_plan(first.plan, "owner-revoked")
        with lexical_connection_scope(params) as conn:
            claim_lexical_generation(conn, revoked_plan, builder_owner_id="owner-revoked")
            populate_lexical_generation_rows(
                conn,
                revoked_plan,
                builder_owner_id="owner-revoked",
                batch_size=1,
                claim_generation=False,
            )
            revoke_lexical_generations(
                conn,
                repository_id=revoked_plan.repository_id,
                reason="owned_race_fixture_revoke",
                purge_rows=True,
            )
            conn.commit()
        with lexical_connection_scope(params) as conn:
            with pytest.raises(LexicalStorageError) as revoked:
                lifecycle.publish_lexical_generation(conn, revoked_plan, builder_owner_id="owner-revoked")
        assert revoked.value.code == "cloe_lexical_count_verification_failed"


def test_failed_attempt_cleanup_preserves_ready_authority_and_removes_owned_rows(
    tmp_path: Path,
) -> None:
    """Policy failure cleans only the new attempt and leaves usable prior publication rows."""
    with temporary_postgres() as pg_db:
        home, config = _fixture_home(tmp_path, pg_db)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        params = lexical_connection_parameters(config, graph)
        core_id = binding_id_for_alias("core")
        companion_id = binding_id_for_alias("companion")
        first = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id, companion_id),
            authorize_body=True,
        )
        assert first.published is not None and first.plan is not None
        config_path = home / "repomap.rpl.toml"
        original = config_path.read_text(encoding="utf-8")
        config_path.write_text(_disable_companion(original), encoding="utf-8")
        changed_config = load_graph_registry_config_home(home)
        assert isinstance(changed_config, OpsConfig)
        config_path.write_text(original, encoding="utf-8")
        with pytest.raises(LexicalStorageError) as failure:
            build_and_publish_lexical_generation(
                config,
                MIXED_V1_GRAPH_ID,
                selected_binding_ids=(core_id, companion_id),
                authorize_body=True,
                recheck_config_fn=lambda: changed_config,
            )
        assert failure.value.code == "cloe_lexical_policy_digest_mismatch"

        with lexical_connection_scope(params) as conn:
            rows = execute_fetchall(
                conn,
                """
                SELECT g.lexical_generation_id, g.state, g.builder_owner_id,
                       (SELECT count(*) FROM cloe_lexical.documents d
                        WHERE d.repository_id = g.repository_id
                          AND d.lexical_generation_id = g.lexical_generation_id),
                       (SELECT count(*) FROM cloe_lexical.chunks c
                        WHERE c.repository_id = g.repository_id
                          AND c.lexical_generation_id = g.lexical_generation_id),
                       (SELECT count(*) FROM cloe_lexical.omissions o
                        WHERE o.repository_id = g.repository_id
                          AND o.lexical_generation_id = g.lexical_generation_id)
                FROM cloe_lexical.generations g
                ORDER BY g.created_at, g.lexical_generation_id
                """,
            )
        ready = next(row for row in rows if row[0] == first.published.lexical_generation_id)
        failed = next(row for row in rows if row[1] == "invalidated")
        assert ready[1:] == ("published", None, first.plan.projected_document_count, first.plan.projected_chunk_count, first.plan.omitted_record_count)
        assert failed[2:] == (None, 0, 0, 0)
        env = query_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            LexicalQueryRequest(query="RetrievalExecutionPipeline", selected_binding_ids=(core_id,)),
            authorize_body=True,
        )
        assert env.hits


def test_newer_accepted_publication_rejects_old_lexical_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An actual newer portable graph publication fences an older lexical plan."""
    with temporary_postgres() as pg_db:
        home, config = _fixture_home(tmp_path, pg_db)
        graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
        params = lexical_connection_parameters(config, graph)
        core_id = binding_id_for_alias("core")
        companion_id = binding_id_for_alias("companion")
        first = build_graph_lexical_generation(
            config,
            MIXED_V1_GRAPH_ID,
            selected_binding_ids=(core_id, companion_id),
            authorize_body=True,
        )
        assert first.published is not None and first.plan is not None
        stale_plan = _attempt_plan(first.plan, "owner-stale")
        with lexical_connection_scope(params) as conn:
            claim_lexical_generation(conn, stale_plan, builder_owner_id="owner-stale")
            populate_lexical_generation_rows(
                conn,
                stale_plan,
                builder_owner_id="owner-stale",
                batch_size=1,
                claim_generation=False,
            )
        # Maintained fixture publication advances the accepted graph run, not lexical rows.
        working_copy = tmp_path / "working-copy"
        materialize_mixed_v1_working_copy(working_copy, generation=2)
        publish_and_load_postgres_corpus(home, psql_command=pg_db.psql_command)
        monkeypatch.setattr(lifecycle, "claim_lexical_generation", lambda *_a, **_k: None)
        monkeypatch.setattr(lifecycle, "populate_lexical_generation_rows", lambda *_a, **_k: None)
        with lexical_connection_scope(params) as conn:
            with pytest.raises(LexicalStorageError) as stale:
                lifecycle.publish_lexical_generation(conn, stale_plan, builder_owner_id="owner-stale")
        assert stale.value.code == "cloe_lexical_publication_fence_mismatch"
        with lexical_connection_scope(params) as conn:
            cleanup_owned_lexical_generation(
                conn,
                repository_id=stale_plan.repository_id,
                lexical_generation_id=stale_plan.lexical_generation_id,
                builder_owner_id="owner-stale",
            )
