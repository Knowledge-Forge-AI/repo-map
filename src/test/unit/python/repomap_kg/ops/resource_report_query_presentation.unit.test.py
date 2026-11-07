"""Service-envelope report truth survives CLI output-budget presentation changes."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from common_lore_index.cli.main import main
from common_lore_index.ops import lexical_service
from common_lore_index.retrieval.query_contracts import (
    CapabilityState, EvaluationLocator, MatchSurface, QueryEnvelope, QueryHit, QueryMode, QueryScope,
)
from common_lore_index.storage.lexical_revoke import LexicalRevocationOutcome
from repomap_test_support.resource_report_cli_files import metric, private_directory, report_payload
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, binding_id_for_alias, materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)


def _home(tmp_path: Path) -> Path:
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    return write_mixed_v1_postgres_home(
        tmp_path / "home", working_copy, host="127.0.0.1", port=5432,
        database="unit_fixture", user="fixture",
    )


def _large_envelope() -> QueryEnvelope:
    binding = binding_id_for_alias("core")
    hits = tuple(QueryHit(
        locator=EvaluationLocator(
            binding_id=binding,
            source_relative_path="pkg/" + "long_module_" * 30 + f"/part_{index}.py",
            start_line=index + 1, end_line=index + 2, canonical_key=None,
        ),
        match_surface=MatchSurface.CAPTURED_TEXT, rank=index + 1, score=None,
        snippet_digest="sha256:" + "a" * 64, chunk_id="pchunk1:" + f"{index:064x}",
        representation_version="cloe-lexical-pg-fts-v1", artifact_privacy="public-dev",
    ) for index in range(100))
    return QueryEnvelope(
        contract_version="cloe-retrieval-query-v1", requested_mode=QueryMode.RANKED_DISCOVERY,
        effective_mode=QueryMode.RANKED_DISCOVERY, match_surface=MatchSurface.CAPTURED_TEXT,
        scope=QueryScope(graph_id=MIXED_V1_GRAPH_ID, backend="postgresql", selected_binding_ids=(binding,)),
        ordering_policy_version="ts-rank-cd-deterministic-v1", capability_state=CapabilityState.AVAILABLE,
        hits=hits, omissions=(), scope_complete=False, provenance={"run_id": 1},
    ).validate()


def test_cli_budget_relabel_does_not_change_the_service_resource_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home = _home(tmp_path)
    target = private_directory(tmp_path / "reports") / "query.json"
    envelope = _large_envelope()
    monkeypatch.setattr(lexical_service, "_query_graph_lexical_generation", lambda *_a, **_k: (envelope, False))
    assert main([
        "ops", "lexical-query", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
        "--authorize-body", "--binding", binding_id_for_alias("core"), "--query", "fixture",
        "--limit", "100", "--json", "--resource-report", str(target),
    ]) == 1
    captured = capsys.readouterr()
    presented = json.loads(captured.out)
    assert (presented["status"], presented["reason"], presented["hit_count"]) == (
        "partial", "output_budget_exceeded", 0,
    )
    report = report_payload(
        target, operation="lexical_query", backend="postgresql", outcome="available",
        forbidden=(home, MIXED_V1_GRAPH_ID, "long_module_", "fixture"),
    )
    assert metric(report, "query_hits_returned")["value"] == len(envelope.hits) == 100
    assert "resource-report" not in captured.err


def test_revoke_graph_refusal_precedes_destination_admission(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    home = _home(tmp_path)
    target = private_directory(tmp_path / "reports") / "existing.json"
    target.write_bytes(b"foreign-preserved\n")
    assert main([
        "ops", "lexical-revoke", "--repo-map-home", str(home), "--graph", "absent",
        "--dry-run", "--resource-report", str(target),
    ]) == 1
    captured = capsys.readouterr()
    assert "graph" in captured.err and "resource-report" not in captured.err
    assert captured.out == "" and target.read_bytes() == b"foreign-preserved\n"


def test_default_query_and_revoke_do_not_invoke_report_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = _large_envelope()
    outcome = LexicalRevocationOutcome(
        repository_id=1, revoked_generation_ids=(), authority_rows_removed=0,
        purged_document_count=0, purged_chunk_count=0, purged_omission_count=0,
        reason="operator_revoked", purge_rows=True, graph_id="g",
    )

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("unselected observer hook")

    for name in ("begin", "note_lexical_query_controls", "note_lexical_revoke",
                 "finish_lexical_query", "finish_lexical_revoke"):
        monkeypatch.setattr(lexical_service, name, forbidden)
    monkeypatch.setattr(lexical_service, "_query_graph_lexical_generation", lambda *_a, **_k: (envelope, False))
    monkeypatch.setattr(lexical_service, "_revoke_graph_lexical_generation", lambda *_a, **_k: outcome)
    config: Any = SimpleNamespace()
    request: Any = SimpleNamespace()
    assert lexical_service.query_graph_lexical_generation(config, "g", request) is envelope
    assert lexical_service.revoke_graph_lexical_generation(config, "g") is outcome
