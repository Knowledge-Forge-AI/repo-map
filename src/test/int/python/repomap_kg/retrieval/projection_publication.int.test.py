"""Integration tests for captured-text projection binding over real SQLite and PostgreSQL publications (S1/S2)."""

from __future__ import annotations

from common_lore_index.retrieval.projection_build import CapturedTextProjection
from common_lore_index.retrieval.publication_binding import AcceptedPublicationReference
from common_lore_index.retrieval.query_contracts import FallbackDisclosure, QueryMode

from pathlib import Path
import json
from dataclasses import replace

import pytest

from common_lore_index.retrieval.projection_build import build_captured_text_projection
from common_lore_index.retrieval.projection_policy import ExclusionReason
from common_lore_index.retrieval.projection_query import (
    CapturedTextQueryRequest,
    query_captured_text,
)
from common_lore_index.retrieval.query_contracts import CapabilityState, QueryEnvelope
from common_lore_index.retrieval.publication_binding import CorrespondenceErrorCode, CorrespondenceRefusal
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
    publish_and_load_sqlite_corpus,
    read_postgres_accepted_publication,
    read_sqlite_accepted_publication,
)


def _check_serialized_contract(envelope: QueryEnvelope) -> None:
    """Consume actual backend-produced envelopes through the closed wire parser."""
    wire = json.loads(json.dumps(envelope.to_dict()))
    assert QueryEnvelope.from_mapping(wire).to_dict() == envelope.to_dict()
    wire["scope_complete"] = "false"
    with pytest.raises(ValueError, match="scope_complete"):
        QueryEnvelope.from_mapping(wire)


def _check_explicit_fallback(projection: CapturedTextProjection, request: CapturedTextQueryRequest,
                             current: AcceptedPublicationReference, expected: QueryEnvelope) -> None:
    fallback = FallbackDisclosure(caller_selected=True, from_mode=QueryMode.RANKED_DISCOVERY,
                                  to_mode=QueryMode.LITERAL_CAPTURED_TEXT, reason_code="explicit_backend_reference_scan")
    envelope = query_captured_text(projection, replace(request, fallback=fallback),
                                  current_accepted_reference=current)
    assert envelope.requested_mode == QueryMode.RANKED_DISCOVERY
    assert envelope.effective_mode == QueryMode.LITERAL_CAPTURED_TEXT and envelope.fallback == fallback
    assert envelope.hits == expected.hits and envelope.capability_state == expected.capability_state
    _check_serialized_contract(envelope)


def test_real_retained_bundle_must_pass_streaming_validation_and_identity_binding(tmp_path: Path) -> None:
    working = materialize_mixed_v1_working_copy(tmp_path / "working", generation=1)
    state = publish_and_load_sqlite_corpus(write_mixed_v1_sqlite_home(tmp_path / "home", working))
    inputs = state.projection_inputs()
    assert inputs.spool_dir is not None
    before = sorted(path.name for path in inputs.spool_dir.iterdir())
    tampered = state.store.put(
        b'{"frame":"invalid-publication-header"}\n', media_type="application/json",
        record_format="publication-bundle-v1", privacy=state.bundle_reference.privacy,
    )
    assert state.store.verify(tampered)
    with pytest.raises(CorrespondenceRefusal, match="PublisherBundleValidator failed") as failure:
        build_captured_text_projection(replace(inputs, bundle_reference=tampered), state.policy)
    assert failure.value.code == CorrespondenceErrorCode.BUNDLE_VALIDATION_FAILED
    assert sorted(path.name for path in inputs.spool_dir.iterdir()) == before
    with pytest.raises(CorrespondenceRefusal, match="stored manifest") as failure:
        build_captured_text_projection(replace(inputs, manifest_reference=tampered), state.policy)
    assert failure.value.code == CorrespondenceErrorCode.STORE_VERIFICATION_FAILED
    portable = inputs.receipt.portable
    assert portable is not None
    wrong_worker = replace(inputs.receipt, portable=replace(portable, worker_capability_identity="different-worker"))
    with pytest.raises(ValueError, match="invalid portable publication binding"):
        build_captured_text_projection(replace(inputs, receipt=wrong_worker), state.policy)


def test_sqlite_real_publication_projection_query_and_stale_advancement_refusal(
    tmp_path: Path,
) -> None:
    """SQLite Local publication binds projection, answers queries, and refuses after generation advancement."""
    wc_gen1 = materialize_mixed_v1_working_copy(tmp_path / "wc_gen1", generation=1)
    sq_home = write_mixed_v1_sqlite_home(tmp_path / "sq_home", wc_gen1)
    state_gen1 = publish_and_load_sqlite_corpus(sq_home)

    projection_gen1 = build_captured_text_projection(
        state_gen1.projection_inputs(), state_gen1.policy
    )
    assert projection_gen1.accepted_reference.backend == "sqlite"
    assert projection_gen1.accepted_reference.accepted_generation == 1
    assert len(projection_gen1.projected_files) > 0

    req = CapturedTextQueryRequest(
        query="ERR_CLOE_MANIFEST_SEAL_MISMATCH_409",
        selected_binding_ids=(binding_id_for_alias("core"),),
        limit=20,
    )
    env = query_captured_text(
        projection_gen1,
        req,
        current_accepted_reference=state_gen1.accepted_reference,
    )
    assert env.capability_state == CapabilityState.AVAILABLE
    assert env.scope_complete is True
    assert len(env.hits) >= 1
    assert any(h.locator.source_relative_path == "pkg/pipeline.py" for h in env.hits)
    assert any(h.locator.canonical_key is not None for h in env.hits)
    assert_canary_free(env.to_dict())
    _check_serialized_contract(env)
    _check_explicit_fallback(projection_gen1, req, state_gen1.accepted_reference, env)
    refused = query_captured_text(projection_gen1, CapturedTextQueryRequest(
        query="arbitrary literal", selected_binding_ids=(binding_id_for_alias("mailbox"),),
    ))
    assert refused.capability_state == CapabilityState.REFUSED
    _check_serialized_contract(refused)

    # Advance the same SQLite home to generation 2 and verify stale projection refusal
    materialize_mixed_v1_working_copy(tmp_path / "wc_gen1", generation=2)
    state_gen2 = publish_and_load_sqlite_corpus(sq_home)
    assert state_gen2.accepted_reference.accepted_generation == 2

    from common_lore_index.ops.config_local import (
        LocalSqliteConfig,
        load_graph_registry_config_home,
    )

    cfg = load_graph_registry_config_home(sq_home)
    assert isinstance(cfg, LocalSqliteConfig)
    cur_acc, _ = read_sqlite_accepted_publication(cfg, MIXED_V1_GRAPH_ID)
    stale_env = query_captured_text(
        projection_gen1,
        req,
        current_accepted_reference=cur_acc,
    )
    assert stale_env.capability_state == CapabilityState.STALE
    assert "stale_detail" in stale_env.provenance
    _check_serialized_contract(stale_env)


def test_postgres_real_publication_projection_query_and_missing_artifact_exclusion(
    tmp_path: Path,
) -> None:
    """PostgreSQL publication binds projection, answers queries, and degrades missing artifacts explicitly."""
    with temporary_postgres() as pg_db:
        wc_gen1 = materialize_mixed_v1_working_copy(tmp_path / "wc_pg1", generation=1)
        pg_home = write_mixed_v1_postgres_home(
            tmp_path / "pg_home",
            wc_gen1,
            host=pg_db.host,
            port=pg_db.port,
            database=pg_db.database,
            user=pg_db.user,
            password=pg_db.password,
        )
        state_pg1 = publish_and_load_postgres_corpus(
            pg_home, psql_command=pg_db.psql_command
        )
        projection_pg1 = build_captured_text_projection(
            state_pg1.projection_inputs(), state_pg1.policy
        )
        assert projection_pg1.accepted_reference.backend == "postgresql"
        assert projection_pg1.accepted_reference.accepted_generation is None

        req = CapturedTextQueryRequest(
            query="execute_pipeline",
            selected_binding_ids=(binding_id_for_alias("core"),),
            limit=20,
        )
        env = query_captured_text(
            projection_pg1,
            req,
            current_accepted_reference=state_pg1.accepted_reference,
        )
        assert env.capability_state == CapabilityState.AVAILABLE
        assert env.scope_complete is True
        assert any(
            h.locator.source_relative_path == "pkg/pipeline.py" for h in env.hits
        )
        assert any(h.locator.canonical_key is not None for h in env.hits)
        assert_canary_free(env.to_dict())
        _check_serialized_contract(env)
        _check_explicit_fallback(projection_pg1, req, state_pg1.accepted_reference, env)

        # Remove one retained object file for core/pkg/pipeline.py and rebuild projection
        pipeline_entry = next(
            e
            for e in state_pg1.manifest.entries
            if e.source_relative_path == "pkg/pipeline.py"
        )
        digest_hex = pipeline_entry.reference.content_digest.split(":", 1)[1]
        obj_file = state_pg1.store.root / "objects" / digest_hex
        saved_bytes = obj_file.read_bytes()
        try:
            obj_file.unlink()
            degraded_proj = build_captured_text_projection(
                state_pg1.projection_inputs(), state_pg1.policy
            )
            assert any(
                o.source_relative_path == "pkg/pipeline.py"
                and o.reason == ExclusionReason.ARTIFACT_MISSING
                for o in degraded_proj.excluded_files
            )
            deg_env = query_captured_text(
                degraded_proj,
                req,
                current_accepted_reference=state_pg1.accepted_reference,
            )
            assert deg_env.capability_state == CapabilityState.PARTIAL
            assert deg_env.scope_complete is False
            _check_serialized_contract(deg_env)
            assert any(
                o.reason_code == ExclusionReason.ARTIFACT_MISSING.value
                for o in deg_env.omissions
            )
        finally:
            obj_file.write_bytes(saved_bytes)

        # Advance PostgreSQL publication to generation 2 and verify stale projection refusal
        materialize_mixed_v1_working_copy(tmp_path / "wc_pg1", generation=2)
        state_pg2 = publish_and_load_postgres_corpus(
            pg_home, psql_command=pg_db.psql_command
        )
        assert state_pg2.accepted_reference.run_id != state_pg1.accepted_reference.run_id

        from common_lore_index.ops.config_local import load_graph_registry_config_home
        from common_lore_index.ops.config_records import OpsConfig

        cfg = load_graph_registry_config_home(pg_home)
        assert isinstance(cfg, OpsConfig)
        cur_pg_acc, _ = read_postgres_accepted_publication(
            cfg, MIXED_V1_GRAPH_ID, psql_command=pg_db.psql_command
        )
        stale_pg_env = query_captured_text(
            projection_pg1,
            req,
            current_accepted_reference=cur_pg_acc,
        )
        assert stale_pg_env.capability_state == CapabilityState.STALE
        assert "stale_detail" in stale_pg_env.provenance
        _check_serialized_contract(stale_pg_env)


def test_empty_selected_aliases_max_projected_files_cap_and_none_current_reference(
    tmp_path: Path,
) -> None:
    """Exercise empty selected_aliases, max_projected_files=1 cap, and lambda: None current reference."""
    wc = materialize_mixed_v1_working_copy(tmp_path / "wc", generation=1)
    sq_home = write_mixed_v1_sqlite_home(tmp_path / "sq_home", wc)
    state_empty = publish_and_load_sqlite_corpus(sq_home, selected_aliases=())
    proj_empty = build_captured_text_projection(
        state_empty.projection_inputs(), state_empty.policy
    )
    assert proj_empty.projected_files == ()
    assert proj_empty.aggregate_input_bytes_read == 0
    assert len(proj_empty.excluded_bindings) == 4

    refused_excl = query_captured_text(
        proj_empty,
        CapturedTextQueryRequest(
            query="token",
            selected_binding_ids=(binding_id_for_alias("mailbox"),),
        ),
        current_accepted_reference=state_empty.accepted_reference,
    )
    assert refused_excl.capability_state == CapabilityState.REFUSED
    assert refused_excl.refusal_code == ExclusionReason.BINDING_PRIVACY_NOT_AUTHORIZED.value

    unknown_b = "bind1:" + ("0" * 64)
    refused_unknown = query_captured_text(
        proj_empty,
        CapturedTextQueryRequest(query="token", selected_binding_ids=(unknown_b,)),
        current_accepted_reference=state_empty.accepted_reference,
    )
    assert refused_unknown.capability_state == CapabilityState.REFUSED
    assert refused_unknown.refusal_code == "unresolved_inherit_policy"

    unavail_empty = query_captured_text(
        proj_empty,
        CapturedTextQueryRequest(query="token", selected_binding_ids=()),
        current_accepted_reference=state_empty.accepted_reference,
    )
    assert unavail_empty.capability_state == CapabilityState.UNAVAILABLE
    assert unavail_empty.unavailable_reason == "projection_absent"
    assert unavail_empty.establishes_absence() is False

    # Normal policy with max_projected_files=1 cap and lambda: None current reference
    state_full = publish_and_load_sqlite_corpus(sq_home)
    policy_cap1 = replace(state_full.policy, max_projected_files=1)
    proj_cap1 = build_captured_text_projection(
        state_full.projection_inputs(), policy_cap1
    )
    assert len(proj_cap1.projected_files) == 1
    budget_omitted = [
        ef
        for ef in proj_cap1.excluded_files
        if ef.reason == ExclusionReason.AGGREGATE_BUDGET_EXCEEDED
    ]
    assert len(budget_omitted) >= 1
    assert all(ef.store_opened is False for ef in budget_omitted)

    partial_env = query_captured_text(
        proj_cap1,
        CapturedTextQueryRequest(query="NONEXISTENT_TOKEN_99999"),
        current_accepted_reference=state_full.accepted_reference,
    )
    assert partial_env.capability_state == CapabilityState.PARTIAL
    assert partial_env.scope_complete is False
    assert partial_env.establishes_absence() is False
    assert any(
        o.reason_code == ExclusionReason.AGGREGATE_BUDGET_EXCEEDED.value
        for o in partial_env.omissions
    )

    stale_none = query_captured_text(
        proj_cap1,
        CapturedTextQueryRequest(query="execute_pipeline"),
        current_accepted_reference=lambda: None,
    )
    assert stale_none.capability_state == CapabilityState.STALE
    assert stale_none.hits == ()
    assert stale_none.scope_complete is False
    assert stale_none.establishes_absence() is False
