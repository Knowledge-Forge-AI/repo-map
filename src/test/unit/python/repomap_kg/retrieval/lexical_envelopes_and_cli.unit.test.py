"""Unit tests for lexical query envelopes, output formatters, restore reconciliation, and CLI dispatch (Unit 1)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess

import pytest

from common_lore_index.cli.main import main as cli_main
from common_lore_index.graph.multi_source import SourceKind
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.ops.lexical_output import (
    format_lexical_build_table,
    format_lexical_revoke_table,
    lexical_build_to_jsonable,
    lexical_revoke_to_jsonable,
)
from common_lore_index.ops.lexical_publication import LexicalBuildOutcome
from common_lore_index.retrieval.lexical_envelopes import (
    FTS_ORDERING_POLICY_VERSION,
    LexicalQueryRequest,
    build_lexical_query_envelope,
    resolve_lexical_query_scope,
)
from common_lore_index.retrieval.lexical_policy import build_lexical_generation_policy
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    DEFAULT_ORDERING_POLICY_VERSION,
    FallbackDisclosure,
    OmissionRecord,
    QueryMode,
)
from common_lore_index.runtime._lexical_restore import (
    reconcile_restored_graph_lexical_roles,
    render_lexical_restore_reconciliation_sql,
)
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.lexical_lifecycle import PublishedLexicalGeneration
from common_lore_index.storage.lexical_probe import LexicalRuntimeProbe
from common_lore_index.storage.lexical_query_sql import RawLexicalQueryRow
from common_lore_index.storage.lexical_revoke import LexicalRevocationOutcome
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_sqlite_home,
)


def _sample_graph_and_policy(tmp_path: Path):
    core_b = OpsGraphSourceBindingConfig(
        1, binding_id_for_alias("core"), "src1:" + ("a" * 64), "core", 1, SourceKind.FOLDER,
        str(tmp_path), str(tmp_path), "core", "core", "public-dev", "full-authorized",
        "default", (), (), "sel1:" + ("a" * 64), "pinned", True, "primary",
    )
    mail_b = OpsGraphSourceBindingConfig(
        1, binding_id_for_alias("mailbox"), "src1:" + ("b" * 64), "mailbox", 1, SourceKind.FOLDER,
        str(tmp_path), str(tmp_path), "mailbox", "mailbox", "private-memory", "redacted-hash",
        "default", (), (), "sel1:" + ("b" * 64), "pinned", True, "mailbox",
    )
    graph = OpsGraphConfig(
        id=MIXED_V1_GRAPH_ID, name=MIXED_V1_GRAPH_ID, root_path=str(tmp_path),
        root_path_expanded=str(tmp_path), repository_name=MIXED_V1_GRAPH_ID,
        privacy="public-dev", enabled=True, mcp_visible=True, extractor_profile="default",
        refresh_policy="manual", database="repomap_mixed_v1",
        source_bindings=(core_b, mail_b), explicit_source_bindings=True,
    )
    return graph, build_lexical_generation_policy(graph)


def test_lexical_query_request_validation_and_envelope_states(tmp_path: Path) -> None:
    """Validate LexicalQueryRequest styles, fallbacks, and all fence status classifications."""
    _, policy = _sample_graph_and_policy(tmp_path)
    core_id = binding_id_for_alias("core")
    mail_id = binding_id_for_alias("mailbox")

    req_ranked = LexicalQueryRequest(
        query="RetrievalExecutionPipeline",
        query_style="ranked_terms",
        selected_binding_ids=(core_id,),
        limit=10,
    ).validate()
    res = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID,
        lexical_policy=policy,
        request=req_ranked,
    )
    assert res.immediate_envelope is None

    ok_row = RawLexicalQueryRow(
        fence_status="ok",
        lexical_generation_id="lexgen1:" + ("1" * 64),
        latest_generation_id="lexgen1:" + ("1" * 64),
        latest_revocation_reason=None,
        run_id=5,
        publication_bundle_id="bundle1:" + ("2" * 64),
        snapshot_manifest_id="manifest1:" + ("3" * 64),
        extraction_receipt_id="receipt1:" + ("4" * 64),
        graph_candidate_id="cand1:" + ("5" * 64),
        empty_tsquery=False,
        total_matches=1,
        capped_files=(),
        omissions=(),
        hits=(
            {
                "binding_id": core_id,
                "source_relative_path": "pkg/pipeline.py",
                "start_line": 13,
                "end_line": 30,
                "score": 0.42,
                "chunk_id": "pchunk1:" + ("6" * 64),
                "chunk_sha256": "sha256:" + ("7" * 64),
                "representation_version": "cloe-lexical-pg-fts-v1",
                "artifact_privacy": "public-dev",
                "canonical_key": "class:pkg/pipeline.py:RetrievalExecutionPipeline",
                "evidence_key": "ev1",
                "link_kind": "defined_by",
            },
        ),
    )
    env_ok = build_lexical_query_envelope(
        resolution=res,
        lexical_policy=policy,
        request=req_ranked,
        raw_row=ok_row,
    )
    assert env_ok.capability_state == CapabilityState.AVAILABLE
    assert env_ok.ordering_policy_version == FTS_ORDERING_POLICY_VERSION
    assert len(env_ok.hits) == 1
    assert env_ok.hits[0].locator.canonical_key == "class:pkg/pipeline.py:RetrievalExecutionPipeline"
    union_request = replace(req_ranked, path_prefixes=("missing", "pkg"))
    union_resolution = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID, lexical_policy=policy, request=union_request,
    )
    union_envelope = build_lexical_query_envelope(
        resolution=union_resolution, lexical_policy=policy, request=union_request, raw_row=ok_row,
    )
    assert union_envelope.scope.source_path_prefix is None
    assert union_envelope.provenance["path_prefixes"] == ["missing", "pkg"]
    assert union_envelope.provenance["path_prefix_match"] == "any"
    assert union_envelope.hits[0].locator.source_relative_path.startswith("pkg/")

    # Literal query style uses DEFAULT_ORDERING_POLICY_VERSION and handles capped_files
    req_lit = LexicalQueryRequest(
        query="ERR_409",
        query_style="literal_captured_text",
        selected_binding_ids=(core_id,),
        limit=1,
        fallback=FallbackDisclosure(
            caller_selected=True,
            from_mode=QueryMode.CURRENT_LITERAL_ENUMERATION,
            to_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            reason_code="literal_scan",
        ),
    ).validate()
    res_lit = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID,
        lexical_policy=policy,
        request=req_lit,
    )
    lit_row = RawLexicalQueryRow(
        fence_status="ok",
        lexical_generation_id="lexgen1:" + ("1" * 64),
        latest_generation_id="lexgen1:" + ("1" * 64),
        latest_revocation_reason=None,
        run_id=5,
        publication_bundle_id="bundle1:" + ("2" * 64),
        snapshot_manifest_id="manifest1:" + ("3" * 64),
        extraction_receipt_id="receipt1:" + ("4" * 64),
        graph_candidate_id="cand1:" + ("5" * 64),
        empty_tsquery=False,
        total_matches=3,
        capped_files=((core_id, "pkg/pipeline.py"),),
        omissions=(),
        hits=ok_row.hits,
    )
    env_lit = build_lexical_query_envelope(
        resolution=res_lit,
        lexical_policy=policy,
        request=req_lit,
        raw_row=lit_row,
    )
    assert env_lit.capability_state == CapabilityState.PARTIAL
    assert env_lit.ordering_policy_version == DEFAULT_ORDERING_POLICY_VERSION
    assert any(o.reason_code == "literal_occurrence_cap_exceeded" for o in env_lit.omissions)
    assert any(o.reason_code == "result_page_bounded" for o in env_lit.omissions)

    # Pre-query refusal on private binding
    res_priv = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID,
        lexical_policy=policy,
        request=LexicalQueryRequest(query="secret", selected_binding_ids=(mail_id,)),
    )
    assert res_priv.immediate_envelope is not None
    assert res_priv.immediate_envelope.capability_state == CapabilityState.REFUSED

    # Unavailable, stale, reclassified, and empty_tsquery fence rows
    for fence_status, expected_cap in (
        ("unavailable_lexical_authority_absent", CapabilityState.UNAVAILABLE),
        ("unavailable_requested_binding_not_projected", CapabilityState.UNAVAILABLE),
        ("stale_run_id_mismatch", CapabilityState.STALE),
        ("refused_reclassified:binding_privacy_not_authorized", CapabilityState.REFUSED),
        ("refused_non_public_lexical_generation", CapabilityState.REFUSED),
    ):
        row = RawLexicalQueryRow(
            fence_status=fence_status,
            lexical_generation_id=None,
            latest_generation_id="lexgen1:old",
            latest_revocation_reason="operator_revoked",
            run_id=5,
            publication_bundle_id=None,
            snapshot_manifest_id=None,
            extraction_receipt_id=None,
            graph_candidate_id=None,
            empty_tsquery=False,
            total_matches=0,
            capped_files=(),
            omissions=(),
            hits=(),
        )
        env = build_lexical_query_envelope(
            resolution=res, lexical_policy=policy, request=req_ranked, raw_row=row
        )
        assert env.capability_state == expected_cap

    # Candidate overflow produces PARTIAL with scope_complete=False (B7)
    overflow_row = RawLexicalQueryRow(
        fence_status="ok",
        lexical_generation_id="lexgen1:" + ("1" * 64),
        latest_generation_id="lexgen1:" + ("1" * 64),
        latest_revocation_reason=None,
        run_id=5,
        publication_bundle_id="bundle1:" + ("2" * 64),
        snapshot_manifest_id="manifest1:" + ("3" * 64),
        extraction_receipt_id="receipt1:" + ("4" * 64),
        graph_candidate_id="cand1:" + ("5" * 64),
        empty_tsquery=False,
        total_matches=1,
        capped_files=(),
        omissions=(),
        hits=ok_row.hits,
        candidate_overflow=True,
    )
    env_overflow = build_lexical_query_envelope(
        resolution=res, lexical_policy=policy, request=req_ranked, raw_row=overflow_row
    )
    assert env_overflow.capability_state == CapabilityState.PARTIAL
    assert env_overflow.scope_complete is False
    assert any(o.reason_code == "ranked_candidate_budget_exceeded" for o in env_overflow.omissions)

    # Empty selected_binding_ids is rejected (B2)
    with pytest.raises(ValueError, match="selected_binding_ids must be a non-empty"):
        LexicalQueryRequest(query="alpha", selected_binding_ids=()).validate()


def test_lexical_output_formatters_and_restore_reconciliation_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify JSON/table output formatters and _lexical_restore SQL generation and error handling."""
    pub = PublishedLexicalGeneration(
        lexical_generation_id="lexgen1:abc",
        repository_id=1,
        run_id=2,
        publication_bundle_id="bundle1:abc",
        snapshot_manifest_id="manifest1:abc",
        extraction_receipt_id="receipt1:abc",
        graph_candidate_id="cand1:abc",
        policy_digest="sha256:abc",
        representation_version="cloe-lexical-pg-fts-v1",
        text_config_regconfig="pg_catalog.simple",
        ranking_function="ts_rank_cd",
        normalization_flags=32,
        alias_split_rule_version="identifier-path-split-v1",
        projected_document_count=4,
        projected_chunk_count=8,
        omitted_record_count=1,
        aggregate_input_bytes=1024,
        aggregate_projected_bytes=1024,
        superseded_generation_count=0,
    )
    probe = LexicalRuntimeProbe(
        ready=True,
        server_version_num=160004,
        schema_exists=True,
        schema_comment="cloe-lexical-schema:1",
        has_simple_config=True,
        table_count=5,
        gin_index_count=2,
        fts_smoke_ok=True,
    )
    build_out = LexicalBuildOutcome(
        graph_id="mixed-v1",
        database="repomap_mixed_v1",
        result="published",
        refusal_code=None,
        published=pub,
        probe=probe,
        policy_digest="sha256:abc",
        admitted_binding_ids=("bind1:core",),
        excluded_binding_ids=("bind1:mail",),
        omissions=(OmissionRecord("bind1:mail", None, "binding_privacy_not_authorized", "excluded"),),
        aggregate_input_bytes=1024,
        aggregate_projected_bytes=1024,
    )
    assert lexical_build_to_jsonable(build_out)["result"] == "published"
    assert "lexical_generation_id: lexgen1:abc" in format_lexical_build_table(build_out)

    rev_out = LexicalRevocationOutcome(
        repository_id=1,
        revoked_generation_ids=("lexgen1:abc",),
        authority_rows_removed=1,
        purged_document_count=4,
        purged_chunk_count=8,
        purged_omission_count=1,
        reason="operator_revoked",
        purge_rows=True,
        graph_id="mixed-v1",
    )
    assert lexical_revoke_to_jsonable(rev_out, database="db")["revoked_generation_count"] == 1
    assert "revoked_generations: 1" in format_lexical_revoke_table(rev_out, database="db")
    assert "lexical-revoke mixed-v1: dry_run" in format_lexical_revoke_table(rev_out, database="db", dry_run=True)

    # Output ceiling guard (M3)
    huge_rev = LexicalRevocationOutcome(
        repository_id=1,
        revoked_generation_ids=tuple(f"lexgen1:{i:064x}" for i in range(1200)),
        authority_rows_removed=1,
        purged_document_count=4,
        purged_chunk_count=8,
        purged_omission_count=1,
        reason="operator_revoked",
        purge_rows=True,
        graph_id="mixed-v1",
    )
    huge_out = lexical_revoke_to_jsonable(huge_rev, database="db")
    assert huge_out["status"] == "partial"
    assert huge_out["reason"] == "output_budget_exceeded"
    assert huge_out["output_truncated"] is True

    sql = render_lexical_restore_reconciliation_sql()
    assert "REVOKE ALL ON SCHEMA cloe_lexical FROM PUBLIC" in sql
    assert "restored_snapshot_unverified_lexical_index_invalidated" in sql

    def _ok_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(["psql"], 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _ok_run)
    reconcile_restored_graph_lexical_roles(["-d", "db"], psql_command="psql")

    def _fail_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(
            1, ["psql"], stderr="ERROR: cloe_lexical schema or object custody is not owned by the database owner"
        )

    monkeypatch.setattr(subprocess, "run", _fail_run)
    with pytest.raises(StorageSchemaError, match="custody"):
        reconcile_restored_graph_lexical_roles(["-d", "db"], psql_command="psql")


def test_sqlite_cli_refuses_lexical_commands_with_postgres_home_required(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SQLite Local homes refuse cloe ops lexical-build/query/revoke with postgres-home-required."""
    wc = materialize_mixed_v1_working_copy(tmp_path / "wc", generation=1)
    sq_home = write_mixed_v1_sqlite_home(tmp_path / "sq_home", wc)

    for sub_args in (
        ["ops", "lexical-build", "--repo-map-home", str(sq_home), "--graph", MIXED_V1_GRAPH_ID],
        ["ops", "lexical-query", "--repo-map-home", str(sq_home), "--graph", MIXED_V1_GRAPH_ID, "--query", "x"],
        ["ops", "lexical-revoke", "--repo-map-home", str(sq_home), "--graph", MIXED_V1_GRAPH_ID],
    ):
        rc = cli_main(sub_args)
        captured = capsys.readouterr()
        assert rc == 1
        assert "postgres-home-required: lexical commands require PostgreSQL storage" in captured.err
