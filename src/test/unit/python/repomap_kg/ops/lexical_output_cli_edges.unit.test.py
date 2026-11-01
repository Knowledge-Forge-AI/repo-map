"""Cohesive unit proofs for lexical output formatting and CLI edges."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from common_lore_index.cli.main import main as cli_main
from common_lore_index.cli.ops_lexical_commands import dispatch_ops_lexical_command
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
import common_lore_index.ops.lexical_service as lexical_service
from common_lore_index.ops.lexical_output import (
    format_lexical_build_table,
    format_lexical_query_table,
    format_lexical_revoke_table,
    lexical_query_to_jsonable,
)
from common_lore_index.ops.lexical_publication import LexicalBuildOutcome
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    EvaluationLocator,
    FallbackDisclosure,
    MatchSurface,
    OmissionRecord,
    QueryEnvelope,
    QueryHit,
    QueryMode,
    QueryScope,
)
from common_lore_index.storage.lexical_revoke import LexicalRevocationOutcome
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)


CORE_BINDING_ID = binding_id_for_alias("core")


def _silent_printer(*_args: object, **_kwargs: object) -> None:
    return None


def _refused_build() -> LexicalBuildOutcome:
    return LexicalBuildOutcome(
        graph_id=MIXED_V1_GRAPH_ID,
        database="db",
        result="refused",
        refusal_code="graph_privacy_not_authorized",
        published=None,
        probe=None,
        policy_digest="sha256:" + "0" * 64,
        admitted_binding_ids=(),
        excluded_binding_ids=(CORE_BINDING_ID,),
        omissions=(),
        aggregate_input_bytes=0,
        aggregate_projected_bytes=0,
    )


def _revoke_outcome() -> LexicalRevocationOutcome:
    return LexicalRevocationOutcome(
        repository_id=1,
        revoked_generation_ids=("lexgen1:" + "a" * 64,),
        authority_rows_removed=1,
        purged_document_count=1,
        purged_chunk_count=2,
        purged_omission_count=0,
        reason="operator_revoked",
        purge_rows=True,
        graph_id=MIXED_V1_GRAPH_ID,
    )


def _query_envelope_with_many_hits() -> QueryEnvelope:
    hits = tuple(
        QueryHit(
            locator=EvaluationLocator(
                binding_id=CORE_BINDING_ID,
                source_relative_path=f"pkg/mod_{index}.py",
                start_line=None if index == 0 else index,
                end_line=None if index == 0 else index + 2,
                canonical_key="py:mod" if index == 0 else None,
            ),
            match_surface=MatchSurface.CAPTURED_TEXT,
            rank=index + 1,
            score=1.5 if index == 0 else None,
            snippet_digest="sha256:" + "a" * 64,
            chunk_id="pchunk1:" + f"{index:064x}",
            representation_version="cloe-lexical-pg-fts-v1",
            artifact_privacy="public-dev",
        )
        for index in range(180)
    )
    return QueryEnvelope(
        contract_version="cloe-retrieval-query-v1",
        requested_mode=QueryMode.RANKED_DISCOVERY,
        effective_mode=QueryMode.RANKED_DISCOVERY,
        match_surface=MatchSurface.CAPTURED_TEXT,
        scope=QueryScope(
            graph_id=MIXED_V1_GRAPH_ID,
            backend="postgresql",
            selected_binding_ids=(CORE_BINDING_ID,),
        ),
        ordering_policy_version="ts-rank-cd-deterministic-v1",
        capability_state=CapabilityState.AVAILABLE,
        hits=hits,
        omissions=(
            OmissionRecord(CORE_BINDING_ID, "pkg/a.py", "trunc", "d"),
            OmissionRecord(CORE_BINDING_ID, None, "graph_note", "g"),
        ),
        scope_complete=False,
        provenance={"run_id": 1},
    ).validate()


def _ops_home(tmp_path: Path) -> Path:
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
    assert lexical_service._fresh_ops_config(config) is not None
    return home


def test_lexical_output_tables_and_hit_stripping_truncation() -> None:
    refused = _refused_build()
    assert "refusal_code: graph_privacy_not_authorized" in format_lexical_build_table(refused)
    assert "revoked_generations: 1" in format_lexical_revoke_table(
        _revoke_outcome(), database="db"
    )

    envelope = _query_envelope_with_many_hits()
    table = format_lexical_query_table(MIXED_V1_GRAPH_ID, "ranked_terms", envelope)
    assert "rank | binding_id | path | lines | score | canonical_key" in table
    assert "omission_binding | path | reason_code" in table
    assert "py:mod" in table

    truncated = lexical_query_to_jsonable(MIXED_V1_GRAPH_ID, "ranked_terms", envelope)
    assert truncated["status"] == "partial"
    assert truncated["reason"] == "output_budget_exceeded"
    assert truncated["hit_count"] == 0
    assert truncated["envelope"]["hits"] == []


def test_ops_lexical_dispatch_ignores_unknown_commands() -> None:
    commands: Any = SimpleNamespace()
    assert dispatch_ops_lexical_command(
        Namespace(command="other"), commands, _silent_printer
    ) is None
    assert dispatch_ops_lexical_command(
        Namespace(command="ops", ops_command="other"), commands, _silent_printer
    ) is None


def test_ops_lexical_cli_rejects_authorization_and_fallback_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _ops_home(tmp_path)
    bad_arguments = (
        [
            "ops",
            "lexical-build",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
            "--binding",
            CORE_BINDING_ID,
        ],
        [
            "ops",
            "lexical-build",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
            "--authorize-body",
        ],
        [
            "ops",
            "lexical-query",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
            "--query",
            "x",
            "--binding",
            CORE_BINDING_ID,
        ],
        [
            "ops",
            "lexical-query",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
            "--query",
            "x",
            "--authorize-body",
        ],
        [
            "ops",
            "lexical-query",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
            "--query",
            "x",
            "--authorize-body",
            "--binding",
            CORE_BINDING_ID,
            "--fallback-from-mode",
            "ranked_discovery",
        ],
        [
            "ops",
            "lexical-revoke",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
            "--dry-run",
            "--yes",
        ],
        [
            "ops",
            "lexical-revoke",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
        ],
    )
    for arguments in bad_arguments:
        assert cli_main(arguments) == 1
        capsys.readouterr()


def test_ops_lexical_cli_prints_available_query_and_revoke_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = _ops_home(tmp_path)
    ready = QueryEnvelope(
        contract_version="cloe-retrieval-query-v1",
        requested_mode=QueryMode.GRAPH_INVESTIGATION,
        effective_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        match_surface=MatchSurface.CAPTURED_TEXT,
        scope=QueryScope(
            graph_id=MIXED_V1_GRAPH_ID,
            backend="postgresql",
            selected_binding_ids=(CORE_BINDING_ID,),
        ),
        ordering_policy_version="literal-capture-order-v1",
        capability_state=CapabilityState.AVAILABLE,
        fallback=FallbackDisclosure(
            caller_selected=True,
            from_mode=QueryMode.GRAPH_INVESTIGATION,
            to_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            reason_code="fb",
        ),
    ).validate()
    monkeypatch.setattr(
        lexical_service,
        "query_graph_lexical_generation",
        lambda *_args, **_kwargs: ready,
    )
    assert cli_main(
        [
            "ops",
            "lexical-query",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
            "--query",
            "x",
            "--query-style",
            "literal_captured_text",
            "--authorize-body",
            "--binding",
            CORE_BINDING_ID,
            "--fallback-from-mode",
            "graph_investigation",
            "--fallback-reason",
            "fb",
        ]
    ) == 0
    assert "available" in capsys.readouterr().out

    monkeypatch.setattr(
        lexical_service,
        "revoke_graph_lexical_generation",
        lambda *_args, **_kwargs: LexicalRevocationOutcome(
            1,
            (),
            0,
            0,
            0,
            0,
            "operator_revoked",
            False,
            MIXED_V1_GRAPH_ID,
        ),
    )
    assert cli_main(
        [
            "ops",
            "lexical-revoke",
            "--repo-map-home",
            str(home),
            "--graph",
            MIXED_V1_GRAPH_ID,
            "--dry-run",
        ]
    ) == 0
    assert "revoked_generations: 0" in capsys.readouterr().out
