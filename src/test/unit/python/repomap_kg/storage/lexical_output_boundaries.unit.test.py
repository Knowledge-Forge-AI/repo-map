"""Unit proofs for bounded cloe_lexical JSON and CLI output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common_lore_index.cli.main import main as cli_main
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.lexical_output import (
    MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES,
    lexical_build_to_jsonable,
    lexical_query_to_jsonable,
    lexical_revoke_to_jsonable,
)
from common_lore_index.ops.lexical_publication import LexicalBuildOutcome
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    MatchSurface,
    OmissionRecord,
    QueryEnvelope,
    QueryMode,
    QueryScope,
)
from common_lore_index.storage.lexical_driver import LexicalStorageError
from common_lore_index.storage.lexical_lifecycle import PublishedLexicalGeneration
from common_lore_index.storage.lexical_revoke import LexicalRevocationOutcome
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)


def _assert_json_line_budget(payload: dict[str, object]) -> str:
    text = json.dumps(payload, sort_keys=True)
    assert len((text + "\n").encode("utf-8")) <= MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES
    return text


def _published(generation_id: str = "lexgen1:" + "a" * 64) -> PublishedLexicalGeneration:
    return PublishedLexicalGeneration(
        lexical_generation_id=generation_id,
        repository_id=1,
        run_id=2,
        publication_bundle_id="bundle1:" + "b" * 64,
        snapshot_manifest_id="snapmanifest1:" + "c" * 64,
        extraction_receipt_id="receipt1:" + "d" * 64,
        graph_candidate_id="cand1:" + "e" * 64,
        policy_digest="sha256:" + "f" * 64,
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


def _build_outcome(
    *,
    omissions: tuple[OmissionRecord, ...] = (),
    generation_id: str | None = None,
) -> LexicalBuildOutcome:
    return LexicalBuildOutcome(
        graph_id=MIXED_V1_GRAPH_ID,
        database="fixture_output_db",
        result="published",
        refusal_code=None,
        published=_published(generation_id or "lexgen1:" + "a" * 64),
        probe=None,
        policy_digest="sha256:" + "f" * 64,
        admitted_binding_ids=(binding_id_for_alias("core"),),
        excluded_binding_ids=(),
        omissions=omissions,
        aggregate_input_bytes=1024,
        aggregate_projected_bytes=1024,
    )


def _revoke_outcome(count: int = 1) -> LexicalRevocationOutcome:
    return LexicalRevocationOutcome(
        repository_id=1,
        revoked_generation_ids=tuple(f"lexgen1:{index:064x}" for index in range(count)),
        authority_rows_removed=1,
        purged_document_count=4,
        purged_chunk_count=8,
        purged_omission_count=1,
        reason="operator_revoked",
        purge_rows=True,
        graph_id=MIXED_V1_GRAPH_ID,
    )


def _query_envelope(*, oversized: bool = False) -> QueryEnvelope:
    binding_id = binding_id_for_alias("core")
    sentinel = "OVERSIZED_LEXICAL_OUTPUT_SENTINEL"
    value = sentinel * 4000 if oversized else "accepted-run"
    return QueryEnvelope(
        contract_version="cloe-retrieval-query-v1",
        requested_mode=QueryMode.RANKED_DISCOVERY,
        effective_mode=QueryMode.RANKED_DISCOVERY,
        match_surface=MatchSurface.CAPTURED_TEXT,
        scope=QueryScope(
            graph_id=value if oversized else MIXED_V1_GRAPH_ID,
            backend="postgresql",
            selected_binding_ids=(binding_id,),
        ),
        ordering_policy_version="ts-rank-cd-deterministic-v1",
        capability_state=CapabilityState.PARTIAL,
        omissions=(
            OmissionRecord(
                binding_id=binding_id,
                source_relative_path=None,
                reason_code="transport_stress",
                detail=value,
            ),
        ),
        scope_complete=False,
        provenance={"accepted_identity": value},
    ).validate()


def _postgres_home(tmp_path: Path) -> Path:
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    home = write_mixed_v1_postgres_home(
        tmp_path / "home",
        working_copy,
        host="127.0.0.1",
        port=55433,
        database="fixture_output_db",
        user="fixture_output_owner",
        declared_aliases=("core", "companion"),
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, OpsConfig)
    return home


def test_output_formatters_bound_json_plus_newline_and_reject_untruthful_identity() -> None:
    """Normal and partial payloads fit; oversized truthful identity cannot be fabricated."""
    normal_build = lexical_build_to_jsonable(_build_outcome())
    assert normal_build["status"] == "ready"
    _assert_json_line_budget(normal_build)

    build_omissions = tuple(
        OmissionRecord(
            binding_id=binding_id_for_alias("core"),
            source_relative_path=f"pkg/{index}.py",
            reason_code="fixture_omission",
            detail="bounded omission",
        )
        for index in range(1800)
    )
    partial_build = lexical_build_to_jsonable(_build_outcome(omissions=build_omissions))
    assert partial_build["status"] == "partial"
    assert partial_build["reason"] == "output_budget_exceeded"
    assert partial_build["output_truncated"] is True
    _assert_json_line_budget(partial_build)

    huge_identity = "lexgen1:" + "IDENTITY_TOO_LARGE_" * 5000
    with pytest.raises(LexicalStorageError) as build_error:
        lexical_build_to_jsonable(_build_outcome(generation_id=huge_identity))
    assert build_error.value.code == "output_budget_exceeded"
    assert "IDENTITY_TOO_LARGE" not in str(build_error.value)

    partial_revoke = lexical_revoke_to_jsonable(
        _revoke_outcome(1800), database="fixture_output_db"
    )
    assert partial_revoke["status"] == "partial"
    assert partial_revoke["reason"] == "output_budget_exceeded"
    assert partial_revoke["output_truncated"] is True
    _assert_json_line_budget(partial_revoke)

    normal_query = lexical_query_to_jsonable(
        MIXED_V1_GRAPH_ID, "ranked_terms", _query_envelope()
    )
    _assert_json_line_budget(normal_query)

    with pytest.raises(LexicalStorageError) as query_error:
        lexical_query_to_jsonable(
            MIXED_V1_GRAPH_ID, "ranked_terms", _query_envelope(oversized=True)
        )
    assert query_error.value.code == "output_budget_exceeded"
    assert "OVERSIZED_LEXICAL_OUTPUT_SENTINEL" not in str(query_error.value)


def test_cli_partial_outputs_exit_one_and_query_overflow_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI partial JSON is parseable; query serialization refusal is bounded stderr."""
    home = _postgres_home(tmp_path)
    core_id = binding_id_for_alias("core")

    import common_lore_index.ops.lexical_service as lexical_service

    build_omissions = tuple(
        OmissionRecord(core_id, f"pkg/{index}.py", "fixture_omission", "bounded")
        for index in range(1800)
    )
    monkeypatch.setattr(
        lexical_service,
        "build_graph_lexical_generation",
        lambda *_args, **_kwargs: _build_outcome(omissions=build_omissions),
    )
    build_rc = cli_main(
        [
            "ops",
            "lexical-build",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
            "--authorize-body",
            "--binding",
            core_id,
            "--json",
        ]
    )
    build_capture = capsys.readouterr()
    assert build_rc == 1
    build_payload = json.loads(build_capture.out)
    assert build_payload["status"] == "partial"
    assert build_payload["reason"] == "output_budget_exceeded"
    _assert_json_line_budget(build_payload)
    assert build_capture.err == ""

    monkeypatch.setattr(
        lexical_service,
        "revoke_graph_lexical_generation",
        lambda *_args, **_kwargs: _revoke_outcome(1800),
    )
    revoke_rc = cli_main(
        [
            "ops",
            "lexical-revoke",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
            "--dry-run",
            "--json",
        ]
    )
    revoke_capture = capsys.readouterr()
    assert revoke_rc == 1
    revoke_payload = json.loads(revoke_capture.out)
    assert revoke_payload["status"] == "partial"
    assert revoke_payload["reason"] == "output_budget_exceeded"
    _assert_json_line_budget(revoke_payload)
    assert revoke_capture.err == ""

    monkeypatch.setattr(
        lexical_service,
        "query_graph_lexical_generation",
        lambda *_args, **_kwargs: _query_envelope(oversized=True),
    )
    query_rc = cli_main(
        [
            "ops",
            "lexical-query",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
            "--query",
            "pipeline",
            "--authorize-body",
            "--binding",
            core_id,
            "--json",
        ]
    )
    query_capture = capsys.readouterr()
    assert query_rc == 1
    assert query_capture.out == ""
    assert "output_budget_exceeded" in query_capture.err
    assert "OVERSIZED_LEXICAL_OUTPUT_SENTINEL" not in query_capture.err
    assert "Traceback" not in query_capture.err
    assert len(query_capture.err.encode("utf-8")) <= MAX_SERIALIZED_LEXICAL_OUTPUT_BYTES
