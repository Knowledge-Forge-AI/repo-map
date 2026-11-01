"""Cohesive unit proofs for lexical request, scope, and envelope states."""

from __future__ import annotations

from pathlib import Path

import pytest

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_publication import resolve_ops_graph
from common_lore_index.retrieval.lexical_envelopes import (
    LexicalQueryRequest,
    LexicalScopeResolution,
    build_lexical_query_envelope,
    resolve_lexical_query_scope,
)
from common_lore_index.retrieval.lexical_policy import (
    LexicalGenerationPolicy,
    build_lexical_generation_policy,
)
from common_lore_index.retrieval.query_contracts import FallbackDisclosure, QueryMode
from common_lore_index.storage.lexical_query_sql import RawLexicalQueryRow
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)


CORE_BINDING_ID = binding_id_for_alias("core")
MAILBOX_BINDING_ID = binding_id_for_alias("mailbox")
LITERAL_FALLBACK = FallbackDisclosure(
    caller_selected=True,
    from_mode=QueryMode.GRAPH_INVESTIGATION,
    to_mode=QueryMode.LITERAL_CAPTURED_TEXT,
    reason_code="fallback",
).validate()


def _mixed_policies(tmp_path: Path) -> tuple[LexicalGenerationPolicy, LexicalGenerationPolicy]:
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    home = write_mixed_v1_postgres_home(
        tmp_path / "home",
        working_copy,
        host="127.0.0.1",
        port=5432,
        database="db",
        user="u",
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, OpsConfig)
    private_graph = resolve_ops_graph(config, MIXED_V1_GRAPH_ID)
    private_policy = build_lexical_generation_policy(private_graph)

    config_text = (home / "repomap.rpl.toml").read_text(encoding="utf-8")
    (home / "repomap.rpl.toml").write_text(
        config_text.replace('privacy = "private-memory"', 'privacy = "public-dev"', 1),
        encoding="utf-8",
    )
    public_config = load_graph_registry_config_home(home)
    assert isinstance(public_config, OpsConfig)
    public_graph = resolve_ops_graph(public_config, MIXED_V1_GRAPH_ID)
    return private_policy, build_lexical_generation_policy(public_graph)


def _public_scope(
    tmp_path: Path,
) -> tuple[LexicalGenerationPolicy, LexicalScopeResolution, LexicalScopeResolution]:
    _, public_policy = _mixed_policies(tmp_path)
    ranked_request = LexicalQueryRequest(
        query="needle",
        selected_binding_ids=(CORE_BINDING_ID,),
    ).validate()
    mixed_request = LexicalQueryRequest(
        query="needle",
        selected_binding_ids=(CORE_BINDING_ID, MAILBOX_BINDING_ID),
    ).validate()
    ranked_scope = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID,
        lexical_policy=public_policy,
        request=ranked_request,
    )
    mixed_scope = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID,
        lexical_policy=public_policy,
        request=mixed_request,
    )
    return public_policy, ranked_scope, mixed_scope


def _raw_row(
    *,
    fence_status: str,
    empty_tsquery: bool = False,
    total_matches: int = 0,
    capped_files: tuple[tuple[str, str], ...] = (),
    omissions: tuple[dict[str, str], ...] = (),
    candidate_overflow: bool = False,
) -> RawLexicalQueryRow:
    return RawLexicalQueryRow(
        fence_status=fence_status,
        lexical_generation_id=None if fence_status != "ok" else "lexgen1:" + "1" * 64,
        latest_generation_id="lexgen1:" + "1" * 64,
        latest_revocation_reason="operator_revoked" if fence_status != "ok" else None,
        run_id=1,
        publication_bundle_id="b",
        snapshot_manifest_id="m",
        extraction_receipt_id="r",
        graph_candidate_id="c",
        empty_tsquery=empty_tsquery,
        total_matches=total_matches,
        capped_files=capped_files,
        omissions=omissions,
        hits=(),
        candidate_overflow=candidate_overflow,
    )


def test_lexical_query_request_accepts_literal_fallback() -> None:
    request = LexicalQueryRequest(
        query="needle",
        selected_binding_ids=(CORE_BINDING_ID,),
        query_style="literal_captured_text",
        fallback=LITERAL_FALLBACK,
    ).validate()
    assert request.effective_query_mode() == QueryMode.LITERAL_CAPTURED_TEXT
    assert request.resolved_requested_mode() == QueryMode.GRAPH_INVESTIGATION


@pytest.mark.parametrize(
    "query_request",
    (
        LexicalQueryRequest(query="", selected_binding_ids=(CORE_BINDING_ID,)),
        LexicalQueryRequest(query="a\x00b", selected_binding_ids=(CORE_BINDING_ID,)),
        LexicalQueryRequest(query="a", selected_binding_ids=()),
        LexicalQueryRequest(query="a", selected_binding_ids=(CORE_BINDING_ID,), query_style="regex"),
        LexicalQueryRequest(
            query="a",
            selected_binding_ids=(CORE_BINDING_ID,),
            query_style="ranked_terms",
            fallback=LITERAL_FALLBACK,
        ),
        LexicalQueryRequest(
            query="a",
            selected_binding_ids=(CORE_BINDING_ID,),
            query_style="literal_captured_text",
            requested_mode=QueryMode.RANKED_DISCOVERY,
            fallback=LITERAL_FALLBACK,
        ),
        LexicalQueryRequest(
            query="a",
            selected_binding_ids=(CORE_BINDING_ID,),
            query_style="literal_captured_text",
            requested_mode=QueryMode.RANKED_DISCOVERY,
        ),
    ),
    ids=(
        "empty-query",
        "nul-query",
        "empty-binding-selection",
        "unknown-style",
        "fallback-style-mismatch",
        "fallback-requested-mode-mismatch",
        "missing-fallback-disclosure",
    ),
)
def test_lexical_query_request_rejects_invalid_contracts(
    query_request: LexicalQueryRequest,
) -> None:
    with pytest.raises(ValueError):
        query_request.validate()


def test_lexical_query_scope_refuses_private_and_reclassifies_bindings(tmp_path: Path) -> None:
    private_policy, public_policy = _mixed_policies(tmp_path)
    request = LexicalQueryRequest(query="needle", selected_binding_ids=(CORE_BINDING_ID,)).validate()
    private_scope = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID,
        lexical_policy=private_policy,
        request=request,
    )
    assert private_scope.immediate_envelope is not None
    assert private_scope.immediate_envelope.refusal_code == "graph_privacy_not_authorized"

    unknown_scope = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID,
        lexical_policy=public_policy,
        request=LexicalQueryRequest(
            query="x",
            selected_binding_ids=("bind1:" + "f" * 64,),
        ),
    )
    assert unknown_scope.immediate_envelope is not None
    assert unknown_scope.immediate_envelope.refusal_code == "unresolved_inherit_policy"

    mixed_scope = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID,
        lexical_policy=public_policy,
        request=LexicalQueryRequest(
            query="x",
            selected_binding_ids=(CORE_BINDING_ID, MAILBOX_BINDING_ID),
        ),
    )
    assert mixed_scope.admitted_binding_ids == (CORE_BINDING_ID,)
    assert mixed_scope.immediate_envelope is None
    assert len(mixed_scope.pre_omissions) == 1


@pytest.mark.parametrize(
    ("fence_status", "expected_state"),
    (
        ("refused_non_public_lexical_generation", "refused"),
        ("refused_reclassified:email_body_forbidden", "refused"),
        ("unavailable_no_published_lexical_generation", "unavailable"),
        ("stale_publication_fence_mismatch", "stale"),
    ),
    ids=("non-public", "reclassified", "unavailable", "stale"),
)
def test_lexical_query_envelope_maps_fence_states(
    tmp_path: Path,
    fence_status: str,
    expected_state: str,
) -> None:
    public_policy, ranked_scope, _ = _public_scope(tmp_path)
    request = LexicalQueryRequest(query="needle", selected_binding_ids=(CORE_BINDING_ID,)).validate()
    envelope = build_lexical_query_envelope(
        resolution=ranked_scope,
        lexical_policy=public_policy,
        request=request,
        raw_row=_raw_row(fence_status=fence_status),
    )
    assert envelope.capability_state.value == expected_state


def test_lexical_query_envelope_reports_empty_and_candidate_caps(tmp_path: Path) -> None:
    public_policy, ranked_scope, mixed_scope = _public_scope(tmp_path)
    ranked_request = LexicalQueryRequest(query="needle", selected_binding_ids=(CORE_BINDING_ID,)).validate()
    literal_request = LexicalQueryRequest(
        query="needle",
        selected_binding_ids=(CORE_BINDING_ID,),
        query_style="literal_captured_text",
        fallback=LITERAL_FALLBACK,
    ).validate()
    literal_scope = resolve_lexical_query_scope(
        graph_id=MIXED_V1_GRAPH_ID,
        lexical_policy=public_policy,
        request=literal_request,
    )

    empty_envelope = build_lexical_query_envelope(
        resolution=mixed_scope,
        lexical_policy=public_policy,
        request=ranked_request,
        raw_row=_raw_row(fence_status="ok", empty_tsquery=True),
    )
    assert empty_envelope.refusal_code == "empty_lexical_tsquery"

    capped_row = _raw_row(
        fence_status="ok",
        total_matches=100,
        capped_files=((CORE_BINDING_ID, "a.py"),),
        omissions=(
            {
                "binding_id": CORE_BINDING_ID,
                "source_relative_path": "a.py",
                "reason_code": "trunc",
                "detail": "d",
            },
        ),
        candidate_overflow=True,
    )
    literal_envelope = build_lexical_query_envelope(
        resolution=literal_scope,
        lexical_policy=public_policy,
        request=literal_request,
        raw_row=capped_row,
    )
    ranked_envelope = build_lexical_query_envelope(
        resolution=ranked_scope,
        lexical_policy=public_policy,
        request=ranked_request,
        raw_row=capped_row,
    )
    literal_reasons = {omission.reason_code for omission in literal_envelope.omissions}
    assert literal_reasons >= {
        "literal_occurrence_cap_exceeded",
        "result_page_bounded",
        "literal_scan_budget_exceeded",
    }
    assert "ranked_candidate_budget_exceeded" in {
        omission.reason_code for omission in ranked_envelope.omissions
    }
