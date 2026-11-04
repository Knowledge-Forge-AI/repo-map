"""Unit contracts for evaluator graph navigation scope and completeness."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.retrieval.query_contracts import (
    MatchSurface, OmissionRecord, QueryMode, QueryScope,
)
from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT, binding_id_for_alias
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
from common_lore_index.server.investigation_read_store import ConfiguredNeighborhoodQuery
from retrieval_evaluation_accounting import ByteLayerAccounting
from retrieval_evaluation_graph import (
    _execute_direct_handoff, _execute_navigation_or_locations_mode,
)
import retrieval_evaluation_correspondence_graph_scope as graph_scope
from retrieval_evaluation_correspondence_observation_records import FencedObservationResult
from retrieval_evaluation_graph_records import _build_available_envelope
from retrieval_evaluation_graph_pages import GraphPageEvidence
from retrieval_evaluation_graph_traversal import _traverse_graph_neighborhood
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import load_task_catalog


_CATALOG = MIXED_V1_FIXTURE_ROOT / "tasks/catalog-v1.json"


def _task(task_id: str, **changes: Any):
    catalog = load_task_catalog(_CATALOG)
    task = next(item for item in catalog.tasks if item.task_id == task_id)
    return replace(task, **changes).validate()


def _scope(task, backend: str = "sqlite") -> QueryScope:
    return QueryScope(
        graph_id=task.graph_id, backend=backend,
        selected_binding_ids=tuple(sorted(binding_id_for_alias(a, task.graph_id) for a in task.selected_bindings)),
        source_path_prefix=task.source_path_prefix,
    ).validate()


def _location(binding_id: str, relative_path: str) -> dict[str, object]:
    return {"source": {"binding_id": binding_id, "source_relative_path": relative_path}, "start_line": 1, "end_line": 1}


class _NavigationStore:
    def __init__(self, result: Mapping[str, Any]) -> None:
        self.result = result

    def navigation_search(self, _graph_id: str, _query: NavigationSearchQuery) -> Mapping[str, Any]:
        return self.result


class _LocationsStore:
    def __init__(self, result: Mapping[str, Any]) -> None:
        self.result = result

    def node_locations(self, _graph_id: str, _query: NodeLocationsQuery) -> Mapping[str, Any]:
        return self.result


class _TraversalStore:
    def configured_neighborhood(self, query: ConfiguredNeighborhoodQuery) -> Mapping[str, Any]:
        if query.node == "file:core/a.py":
            return {
                "center": {"canonical_key": "file:core/a.py"},
                "nodes": [{"canonical_key": "file:core/b.py"}], "edges": [],
            }
        return {"center": {"canonical_key": query.node}, "nodes": [], "edges": []}


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [("shared", ["shared", "shared/status_codes.py"]), ("shared/", ["shared/status_codes.py"])],
)
def test_navigation_uses_literal_directory_prefix_boundary(prefix: str, expected: list[str]) -> None:
    task = _task(
        "cal-13", selected_bindings=("core",), source_path_prefix=prefix,
        permitted_query_plan={"query": "status", "graph_query": "status", "limit": 10},
    )
    binding_id = binding_id_for_alias("core", task.graph_id)
    store = _NavigationStore({
        "status": "ok", "scan": {"complete": True}, "nodes": [{
            "canonical_key": "node:status", "locations": [
                _location(binding_id, "shared"),
                _location(binding_id, "shared/status_codes.py"),
                _location(binding_id, "shared2/wrong.py"),
            ],
        }],
    })
    state, envelope, _elapsed, _accounting = _execute_navigation_or_locations_mode(
        store, task, _scope(task), QueryMode.RANKED_DISCOVERY,
    )
    assert state is ExecutionState.COMPLETED
    assert [hit.locator.source_relative_path for hit in envelope.hits] == expected
    assert envelope.scope_complete


def test_navigation_scan_incomplete_is_partial_without_absence_claim() -> None:
    task = _task("cal-13", selected_bindings=("core",), permitted_query_plan={"query": "status", "limit": 10})
    store = _NavigationStore({
        "status": "incomplete", "reason": "node_scan_limit", "nodes": [],
        "scan": {"complete": False},
    })
    _state, envelope, _elapsed, _accounting = _execute_navigation_or_locations_mode(
        store, task, _scope(task), QueryMode.RANKED_DISCOVERY,
    )
    assert envelope.capability_state.value == "partial"
    assert not envelope.scope_complete and not envelope.hits
    assert [item.reason_code for item in envelope.omissions] == ["node_scan_limit"]


def test_navigation_local_result_limit_is_disclosed() -> None:
    task = _task(
        "cal-13", selected_bindings=("core",), permitted_query_plan={"query": "status", "limit": 1},
    )
    binding_id = binding_id_for_alias("core", task.graph_id)
    store = _NavigationStore({
        "status": "ok", "scan": {"complete": True}, "nodes": [
            {"canonical_key": "node:first", "locations": [_location(binding_id, "shared/first.py")]},
            {"canonical_key": "node:second", "locations": [_location(binding_id, "shared/second.py")]},
        ],
    })
    _state, envelope, _elapsed, _accounting = _execute_navigation_or_locations_mode(
        store, task, _scope(task), QueryMode.RANKED_DISCOVERY,
    )
    assert len(envelope.hits) == 1
    assert envelope.capability_state.value == "partial"
    assert envelope.omissions[0].reason_code == "graph_result_limit"


def test_direct_handoff_has_more_is_partial_and_keeps_literal_scope() -> None:
    task = _task("cal-24", selected_bindings=("core",), source_path_prefix="shared")
    binding_id = binding_id_for_alias("core", task.graph_id)
    store = _LocationsStore({
        "status": "ok", "has_more": True, "locations": [
            _location(binding_id, "shared"),
            _location(binding_id, "shared/status_codes.py"),
            _location(binding_id, "shared2/wrong.py"),
        ],
    })
    _state, envelope, _elapsed, _accounting = _execute_direct_handoff(
        store, task, _scope(task), QueryMode.EXACT_IDENTITY, (binding_id,),
    )
    assert [hit.locator.source_relative_path for hit in envelope.hits] == [
        "shared", "shared/status_codes.py",
    ]
    assert envelope.capability_state.value == "partial"
    assert envelope.omissions[0].reason_code == "direct_location_limit"


def test_graph_scope_wrapper_deduplicates_reader_omission(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = _task("cal-23", selected_bindings=("core",))
    omission = OmissionRecord("scope", None, "observation_page_limit", "bounded page").validate()
    read = FencedObservationResult(
        "sqlite", "fixture", "repository", 1, 1, "publication", "manifest", (),
        omissions=(omission,), scope_complete=False, has_more=True,
    )
    monkeypatch.setattr(graph_scope, "_query", lambda *_args, **_kwargs: read)

    def execute(_task, _home, *, psql_command="psql", expected_pin=None):
        graph_scope.query_fenced_current_observations(
            object(), graph_id=task.graph_id, query="x", task_scope=task,
        )
        envelope = _build_available_envelope(
            QueryMode.CURRENT_LITERAL_ENUMERATION, MatchSurface.STORED_METADATA, _scope(task), [],
            omissions=(omission,), scope_complete=False,
        )
        return ExecutionState.COMPLETED, envelope, 1, ByteLayerAccounting(0)

    _state, envelope, _elapsed, _accounting = graph_scope.bind_graph_execution(execute)(task, tmp_path)
    assert envelope.omissions == (omission,)


def test_graph_traversal_discloses_rows_dropped_inside_final_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task("cal-09", selected_bindings=("core",))
    binding_id = binding_id_for_alias("core", task.graph_id)

    def page(relative_path: str, count: int) -> FencedObservationResult:
        rows = tuple({
            "ordinal": index,
            "metadata": {
                "binding_id": binding_id, "source_relative_path": relative_path,
                "start_line": index + 1, "end_line": index + 1,
            },
        } for index in range(count))
        return FencedObservationResult(
            "sqlite", "mixed-v1", "fixture", 1, 1, "publication", "manifest", rows,
            scope_complete=True, has_more=False,
        )

    pages = {
        "core/a.py": page("a.py", 6),
        "core/b.py": page("b.py", 8),
    }
    monkeypatch.setattr(
        graph_scope, "query_fenced_current_observations",
        lambda *_args, **kwargs: pages[kwargs["path"]],
    )
    evidence = GraphPageEvidence()
    hits, _payload_bytes = _traverse_graph_neighborhood(
        _TraversalStore(), object(), task, "file:core/a.py", "query", 10, (binding_id,),
        page_evidence=evidence,
    )
    assert len(hits) == 10
    assert not evidence.scope_complete
    assert [item.reason_code for item in evidence.omissions] == ["graph_result_limit"]
