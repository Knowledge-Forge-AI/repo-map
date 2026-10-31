"""Integration tests for mixed-v1 multi-source corpus publication, edge cases, and generation diffs (S2)."""

from __future__ import annotations

from pathlib import Path

from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.projection_policy import ExclusionReason
from common_lore_index.retrieval.projection_query import (
    CapturedTextQueryRequest,
    query_captured_text,
)
from common_lore_index.retrieval.query_contracts import CapabilityState
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
    publish_and_load_sqlite_corpus,
)


def test_mixed_v1_corpus_edge_cases_duplicate_paths_and_generation_diff_across_backends(
    tmp_path: Path,
) -> None:
    """mixed-v1 publishes cleanly on SQLite and PostgreSQL with identical edge-case and diff accounting."""
    wc1 = materialize_mixed_v1_working_copy(tmp_path / "wc1", generation=1)
    wc2 = materialize_mixed_v1_working_copy(tmp_path / "wc2", generation=2)

    sq_home1 = write_mixed_v1_sqlite_home(tmp_path / "sq1", wc1)
    sq_home2 = write_mixed_v1_sqlite_home(tmp_path / "sq2", wc2)
    sq_state1 = publish_and_load_sqlite_corpus(sq_home1)
    sq_state2 = publish_and_load_sqlite_corpus(sq_home2)

    sq_proj1 = build_captured_text_projection(
        sq_state1.projection_inputs(), sq_state1.policy
    )
    sq_proj2 = build_captured_text_projection(
        sq_state2.projection_inputs(),
        sq_state2.policy,
        prior_manifest=sq_state1.manifest,
    )

    # Verify removed file tracking from generation 1 -> generation 2
    core_id = binding_id_for_alias("core")
    comp_id = binding_id_for_alias("companion")
    assert (core_id, "pkg/legacy_deprecated.py") in sq_proj2.removed_files_from_prior

    # Verify edge-case exclusions and truncations in generation 1
    reasons_by_path = {
        (o.binding_id, o.source_relative_path): o.reason
        for o in sq_proj1.excluded_files
    }
    assert (
        reasons_by_path.get((comp_id, "generated/oversized_dump.txt"))
        == ExclusionReason.ARTIFACT_OVERSIZED
    )
    assert (
        reasons_by_path.get((comp_id, "generated/binary_nul.txt"))
        == ExclusionReason.NUL_BYTE_REJECTED
    )
    assert (
        reasons_by_path.get((comp_id, "generated/invalid_utf8.txt"))
        == ExclusionReason.INVALID_UTF8
    )

    files_by_path = {
        (f.binding_id, f.source_relative_path): f
        for f in sq_proj1.projected_files
    }
    trunc_prose = files_by_path[(comp_id, "generated/truncatable_prose.md")]
    assert trunc_prose.truncated is True
    long_line_notes = files_by_path[(comp_id, "generated/long_line_notes.md")]
    assert any(c.line_split_continuation for c in long_line_notes.chunks)

    # Verify duplicate relative path disambiguation across core and companion
    dup_req = CapturedTextQueryRequest(
        query="STATUS_REGISTRY_HEADER",
        selected_binding_ids=(core_id, comp_id),
        limit=10,
    )
    dup_env = query_captured_text(
        sq_proj1,
        dup_req,
        current_accepted_reference=sq_state1.accepted_reference,
    )
    assert dup_env.capability_state in (
        CapabilityState.AVAILABLE,
        CapabilityState.PARTIAL,
    )
    hit_bindings = {
        h.locator.binding_id
        for h in dup_env.hits
        if h.locator.source_relative_path == "shared/status_codes.py"
    }
    assert hit_bindings == {core_id, comp_id}
    assert_canary_free(dup_env.to_dict())

    # Verify PostgreSQL produces the exact same chunk and omission structure across generations 1 and 2
    with temporary_postgres() as pg_db:
        pg_home1 = write_mixed_v1_postgres_home(
            tmp_path / "pg1",
            wc1,
            host=pg_db.host,
            port=pg_db.port,
            database=pg_db.database,
            user=pg_db.user,
            password=pg_db.password,
        )
        pg_state1 = publish_and_load_postgres_corpus(
            pg_home1, psql_command=pg_db.psql_command
        )
        pg_proj1 = build_captured_text_projection(
            pg_state1.projection_inputs(), pg_state1.policy
        )
        sq_chunks = [c for f in sq_proj1.projected_files for c in f.chunks]
        pg_chunks = [c for f in pg_proj1.projected_files for c in f.chunks]
        assert len(pg_chunks) == len(sq_chunks)
        for sq_c, pg_c in zip(sq_chunks, pg_chunks, strict=True):
            sq_dict = {k: v for k, v in sq_c.to_dict().items() if k not in {"chunk_id", "file_projection_id"}}
            pg_dict = {k: v for k, v in pg_c.to_dict().items() if k not in {"chunk_id", "file_projection_id"}}
            assert pg_dict == sq_dict
        assert [e.to_dict() for e in pg_proj1.excluded_files] == [
            e.to_dict() for e in sq_proj1.excluded_files
        ]
        assert [b.to_dict() for b in pg_proj1.excluded_bindings] == [
            b.to_dict() for b in sq_proj1.excluded_bindings
        ]
        assert_canary_free([c.content_text for c in pg_chunks])

        pg_home2 = write_mixed_v1_postgres_home(
            tmp_path / "pg2",
            wc2,
            host=pg_db.host,
            port=pg_db.port,
            database=pg_db.database,
            user=pg_db.user,
            password=pg_db.password,
        )
        pg_state2 = publish_and_load_postgres_corpus(
            pg_home2, psql_command=pg_db.psql_command
        )
        pg_proj2 = build_captured_text_projection(
            pg_state2.projection_inputs(),
            pg_state2.policy,
            prior_manifest=pg_state1.manifest,
        )
        assert pg_proj2.removed_files_from_prior == sq_proj2.removed_files_from_prior
        assert [e.to_dict() for e in pg_proj2.excluded_files] == [
            e.to_dict() for e in sq_proj2.excluded_files
        ]
