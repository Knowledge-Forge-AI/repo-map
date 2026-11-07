"""The common predicate preserves non-ASCII bytes before scope/page selection."""
from __future__ import annotations

import pytest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from common_lore_index.retrieval.query_contracts import MatchSurface, OmissionRecord, QueryMode, QueryScope
from retrieval_evaluation_correspondence_observation_records import (
    CurrentObservationQuery, FencedObservationResult, _page_rows,
)
from retrieval_evaluation_graph_pages import GraphPageEvidence
from retrieval_evaluation_graph_records import _build_available_envelope
from retrieval_evaluation_observation_contracts import CurrentObservationReadError


def _row(number: int, text: str, *, invalid: bool = False) -> tuple[dict[str, object], dict[str, object]]:
    return (
        {"ordinal": number, "kind": "fixture", "source_id": "fixture", "path": "fixture"},
        {"text": text, "metadata": {} if invalid else {
            "binding_id": "core", "binding_revision": 1, "snapshot_id": "snap",
            "source_relative_path": f"shared/{number}.py",
        }},
    )


def test_unicode_false_positive_cannot_crowd_out_a_later_literal_match() -> None:
    request = CurrentObservationQuery("W5MATCH_ÄRGER", limit=1, source_path_prefix="shared/").validate()
    rows, omissions, complete, has_more = _page_rows(
        request, (_row(0, "w5match_ärger", invalid=True), _row(1, "w5match_Ärger"), _row(2, "w5match_ÄRGER")),
        {"core": (1, "snap")}, has_more=False,
    )
    assert [row["ordinal"] for row in rows] == [1]
    assert has_more and not complete and omissions


def test_matching_malformed_unicode_row_still_refuses_after_the_page() -> None:
    with pytest.raises(CurrentObservationReadError, match="malformed_observation_metadata"):
        _page_rows(
            CurrentObservationQuery("W5MATCH_ÄRGER", limit=1).validate(),
            (_row(0, "w5match_Ärger"), _row(1, "w5match_ÄRGER", invalid=True)),
            {"core": (1, "snap")}, has_more=False,
        )


def _page(*, omissions: tuple[OmissionRecord, ...] = (), complete: bool = True, more: bool = False) -> FencedObservationResult:
    return FencedObservationResult(
        "sqlite", "fixture", "repository", 1, 1, "publication", "manifest", (),
        omissions=omissions, scope_complete=complete, has_more=more,
    )


def test_graph_result_propagates_omissions_without_claiming_complete_scope() -> None:
    original = OmissionRecord("scope", None, "observation_page_limit", "remaining current observations").validate()
    evidence = GraphPageEvidence()
    evidence.observe(_page(omissions=(original,), complete=False, more=True))
    evidence.observe(_page(omissions=(original,), complete=False, more=True))
    envelope = _build_available_envelope(
        QueryMode.CURRENT_LITERAL_ENUMERATION, MatchSurface.STORED_METADATA,
        QueryScope("fixture", "sqlite", selected_binding_ids=("core",)), [],
        omissions=evidence.omissions, scope_complete=evidence.scope_complete,
    )
    assert envelope.scope_complete is False
    assert envelope.capability_state.value == "partial"
    assert envelope.omissions == (original,)


@pytest.mark.parametrize(("complete", "more"), [(False, False), (True, True), (False, True)])
def test_incomplete_reader_without_omission_still_cannot_become_complete(complete: bool, more: bool) -> None:
    evidence = GraphPageEvidence()
    evidence.observe(_page(complete=complete, more=more))
    assert not evidence.scope_complete
    assert evidence.omissions[0].reason_code == "observation_page_limit"


@pytest.mark.parametrize("relative_path", ["elsewhere/record.py", "sharedness/record.py", "shared"])
def test_graph_cannot_credit_a_reader_that_widens_directory_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative_path: str,
) -> None:
    import retrieval_evaluation_graph as graph
    from repomap_test_support.retrieval_evaluation_fixture import binding_id_for_alias
    from retrieval_evaluation_schema import load_task_catalog

    root = Path(__file__).resolve().parents[5]
    task = next(item for item in load_task_catalog(
        root / "src/test/fixtures/retrieval_evaluation/mixed-v1/tasks/catalog-v1.json",
    ).calibration_tasks() if item.task_id == "cal-23")
    task = replace(task, source_path_prefix="shared/")
    page = replace(_page(), rows=({"metadata": {
        "binding_id": binding_id_for_alias(task.selected_bindings[0], task.graph_id),
        "source_relative_path": relative_path,
    }},))
    monkeypatch.setattr(graph, "load_graph_registry_config_home", lambda _home: object())
    monkeypatch.setattr(graph, "investigation_stores", lambda _config: SimpleNamespace(investigation_store=object))
    monkeypatch.setattr(graph, "_evaluate_graph_body_safety_refusal", lambda *_args: None)
    monkeypatch.setattr(graph.graph_scope, "query_fenced_current_observations", lambda *_args, **_kw: page)
    with pytest.raises(CurrentObservationReadError, match="graph_observation_scope_mismatch"):
        graph._execute_graph_baseline_task(task, tmp_path)
