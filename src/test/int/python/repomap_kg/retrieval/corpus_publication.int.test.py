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


def test_disposable_fixture_format_exclusions_and_multibyte_utf8_truncation(
    tmp_path: Path,
) -> None:
    """Verify pre-open format exclusions (.eml, .rss, .xml), empty file, and mid-codepoint UTF-8 prefix."""
    from dataclasses import replace

    wc = materialize_mixed_v1_working_copy(tmp_path / "wc_variant", generation=1)
    comp_root = wc / "companion"
    (comp_root / "generated" / "notice.eml").write_bytes(
        b"From: ops@example.invalid\nSubject: Notice\n\nBody text\n"
    )
    (comp_root / "releases.rss").write_bytes(
        b"<rss><channel><title>Releases</title></channel></rss>\n"
    )
    (comp_root / "opaque.xml").write_bytes(b"<root><item>opaque</item></root>\n")
    (comp_root / "generated" / "empty_note.md").write_bytes(b"")
    multibyte_text = ("alpha \u03b1\u03b2\u03b3 \U0001f680 line\r\n" * 8).encode("utf-8")
    (comp_root / "generated" / "multibyte_utf8.md").write_bytes(multibyte_text)

    sq_home = write_mixed_v1_sqlite_home(tmp_path / "sq_variant", wc)
    state = publish_and_load_sqlite_corpus(sq_home)

    tight_policy = replace(state.policy, max_projected_file_bytes=27)
    proj = build_captured_text_projection(state.projection_inputs(), tight_policy)

    comp_id = binding_id_for_alias("companion")
    excluded_by_path = {
        (e.binding_id, e.source_relative_path): e for e in proj.excluded_files
    }
    eml_ex = excluded_by_path[(comp_id, "generated/notice.eml")]
    assert eml_ex.reason == ExclusionReason.EMAIL_BODY_FORBIDDEN
    assert eml_ex.store_opened is False

    rss_ex = excluded_by_path[(comp_id, "releases.rss")]
    assert rss_ex.reason == ExclusionReason.FEED_BODY_FORBIDDEN
    assert rss_ex.store_opened is False

    xml_ex = excluded_by_path[(comp_id, "opaque.xml")]
    assert xml_ex.reason == ExclusionReason.UNSUPPORTED_SOURCE_FORMAT
    assert xml_ex.store_opened is False

    projected_by_path = {
        (f.binding_id, f.source_relative_path): f for f in proj.projected_files
    }
    empty_rec = projected_by_path[(comp_id, "generated/empty_note.md")]
    assert empty_rec.projected_byte_length == 0
    assert len(empty_rec.chunks) == 1
    assert empty_rec.chunks[0].is_empty_file_record is True

    mb_rec = projected_by_path[(comp_id, "generated/multibyte_utf8.md")]
    assert mb_rec.truncated is True
    assert mb_rec.projected_byte_length <= 27
    joined_mb = "".join(c.content_text for c in mb_rec.chunks)
    assert "\r" not in joined_mb
    assert joined_mb.startswith("alpha \u03b1\u03b2\u03b3 ")

    env = query_captured_text(
        proj,
        CapturedTextQueryRequest(query="alpha", selected_binding_ids=(comp_id,)),
        current_accepted_reference=state.accepted_reference,
    )
    assert env.capability_state == CapabilityState.PARTIAL
    assert env.scope_complete is False
    omission_reasons = {
        (o.source_relative_path, o.reason_code) for o in env.omissions
    }
    assert ("generated/notice.eml", ExclusionReason.EMAIL_BODY_FORBIDDEN.value) in omission_reasons
    assert ("releases.rss", ExclusionReason.FEED_BODY_FORBIDDEN.value) in omission_reasons
    assert ("opaque.xml", ExclusionReason.UNSUPPORTED_SOURCE_FORMAT.value) in omission_reasons
    assert ("generated/multibyte_utf8.md", "projected_prefix_truncated") in omission_reasons
