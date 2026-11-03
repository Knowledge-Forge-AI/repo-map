"""SQLite/PostgreSQL publication and privacy matrix (W5)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.projection_policy import ExclusionReason
from common_lore_index.retrieval.projection_query import (
    CapturedTextQueryRequest,
    query_captured_text,
)
from common_lore_index.retrieval.query_contracts import CapabilityState
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    PublishedCorpusState,
    publish_and_load_postgres_corpus,
    publish_and_load_sqlite_corpus,
)
from repomap_test_support.w5_publication_privacy_fixtures import (
    assert_correspondence_mismatch_matrix,
    policy_with_resolution,
    publication_tree,
)


CORE_ID = binding_id_for_alias("core", MIXED_V1_GRAPH_ID)
QUERY = CapturedTextQueryRequest(
    query="ERR_CLOE_MANIFEST_SEAL_MISMATCH_409",
    selected_binding_ids=(CORE_ID,),
    limit=20,
)


def _assert_published_state(state: PublishedCorpusState) -> None:
    """Exercise positive, refusal, missing-object, and cleanup contracts on one backend."""
    inputs = state.projection_inputs()
    assert inputs.spool_dir is not None
    assert_correspondence_mismatch_matrix(inputs)

    projection = build_captured_text_projection(inputs, state.policy)
    assert projection.projected_files
    available = query_captured_text(
        projection,
        QUERY,
        current_accepted_reference=state.accepted_reference,
    )
    assert available.capability_state == CapabilityState.AVAILABLE
    assert available.hits

    # Binding privacy is resolved before the source object is opened.  The
    # retained workspace is the only run-owned scratch area this assertion
    # treats as cleanup-owned; object-store bytes remain untouched.
    private_policy = policy_with_resolution(
        state.policy,
        CORE_ID,
        resolved_binding_privacy="private-memory",
    )
    before_private = publication_tree(inputs.spool_dir)
    private_projection = build_captured_text_projection(inputs, private_policy)
    private_files = [
        item for item in private_projection.excluded_files if item.binding_id == CORE_ID
    ]
    assert private_files
    assert all(item.reason == ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED for item in private_files)
    assert all(not item.store_opened for item in private_files)
    assert not any(item.binding_id == CORE_ID for item in private_projection.projected_files)
    assert publication_tree(inputs.spool_dir) == before_private

    pipeline_entry = next(
        entry
        for entry in state.manifest.entries
        if entry.binding_id == CORE_ID and entry.source_relative_path == "pkg/pipeline.py"
    )
    digest_hex = pipeline_entry.reference.content_digest.split(":", 1)[1]
    object_file = state.store.root / "objects" / digest_hex
    saved_bytes = object_file.read_bytes()
    before_missing = publication_tree(inputs.spool_dir)
    try:
        object_file.unlink()
        degraded = build_captured_text_projection(inputs, state.policy)
        missing = next(
            item
            for item in degraded.excluded_files
            if item.binding_id == CORE_ID and item.source_relative_path == "pkg/pipeline.py"
        )
        assert missing.reason == ExclusionReason.ARTIFACT_MISSING
        assert missing.store_opened is True
        partial = query_captured_text(
            degraded,
            QUERY,
            current_accepted_reference=state.accepted_reference,
        )
        assert partial.capability_state == CapabilityState.PARTIAL
        assert partial.scope_complete is False
    finally:
        object_file.write_bytes(saved_bytes)
    assert publication_tree(inputs.spool_dir) == before_missing


def test_sqlite_publication_correspondence_privacy_and_generation_fence(
    tmp_path: Path,
) -> None:
    """SQLite Local keeps the accepted generation and refuses an older projection after refresh."""
    working = materialize_mixed_v1_working_copy(tmp_path / "working", generation=1)
    home = write_mixed_v1_sqlite_home(tmp_path / "sqlite-home", working)
    state_one = publish_and_load_sqlite_corpus(home)
    _assert_published_state(state_one)

    materialize_mixed_v1_working_copy(working, generation=2)
    state_two = publish_and_load_sqlite_corpus(home)
    assert state_two.accepted_reference.accepted_generation == 2
    stale = query_captured_text(
        build_captured_text_projection(state_one.projection_inputs(), state_one.policy),
        QUERY,
        current_accepted_reference=state_two.accepted_reference,
    )
    assert stale.capability_state == CapabilityState.STALE
    assert stale.hits == ()


def test_postgres_publication_correspondence_privacy_and_generation_fence(
    tmp_path: Path,
) -> None:
    """PostgreSQL matched-repository publication has the same projection/refusal matrix."""
    with temporary_postgres() as pg_db:
        working = materialize_mixed_v1_working_copy(tmp_path / "working", generation=1)
        home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home",
            working,
            host=pg_db.host,
            port=pg_db.port,
            database=pg_db.database,
            user=pg_db.user,
            password=pg_db.password,
        )
        state_one = publish_and_load_postgres_corpus(
            home,
            psql_command=pg_db.psql_command,
        )
        _assert_published_state(state_one)

        materialize_mixed_v1_working_copy(working, generation=2)
        state_two = publish_and_load_postgres_corpus(
            home,
            psql_command=pg_db.psql_command,
        )
        stale = query_captured_text(
            build_captured_text_projection(state_one.projection_inputs(), state_one.policy),
            QUERY,
            current_accepted_reference=state_two.accepted_reference,
        )
        assert stale.capability_state == CapabilityState.STALE
        assert stale.hits == ()


def test_repository_marker_change_is_stale_even_when_other_identity_fields_match(
    tmp_path: Path,
) -> None:
    """The query fence binds repository identity, not only the portable bundle tuple."""
    working = materialize_mixed_v1_working_copy(tmp_path / "working", generation=1)
    home = write_mixed_v1_sqlite_home(tmp_path / "sqlite-home", working)
    state = publish_and_load_sqlite_corpus(home)
    projection = build_captured_text_projection(state.projection_inputs(), state.policy)
    foreign = replace(state.accepted_reference, repository_id="repo1:other-repository")
    result = query_captured_text(projection, QUERY, current_accepted_reference=foreign)
    assert result.capability_state == CapabilityState.STALE
    assert result.hits == ()
