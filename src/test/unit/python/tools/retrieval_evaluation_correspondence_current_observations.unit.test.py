"""Strict bounded current-observation scope and pagination contracts."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
import ast
import json
from pathlib import Path
from typing import cast

import pytest

from common_lore_index.retrieval.query_contracts import OmissionRecord
from retrieval_evaluation_correspondence_observation_records import (
    CurrentObservationQuery,
    _page_rows,
    _snapshot_map,
)
from retrieval_evaluation_observation_contracts import CurrentObservationReadError
from retrieval_evaluation_current_observations import _scan_sqlite_observations


def _candidate(binding: str, path: str, *, revision: int = 1, snapshot: str = "snap") -> tuple[dict[str, object], dict[str, object]]:
    return (
        {"ordinal": revision, "kind": "python.function", "source_id": binding, "path": path},
        {"metadata": {
            "binding_id": binding, "binding_revision": revision,
            "snapshot_id": snapshot, "source_relative_path": path,
        }, "text": "token"},
    )


def test_selection_and_prefix_are_applied_before_page_limit() -> None:
    request = CurrentObservationQuery(
        "token", limit=1, selected_binding_ids=("companion",), source_path_prefix="pkg"
    ).validate()
    rows, omissions, complete, has_more = _page_rows(
        request,
        (_candidate("core", "pkg/other.py"), _candidate("companion", "pkg/answer.py"),
         _candidate("companion", "docs/answer.md")),
        _snapshot_map((("core", 1, "snap"), ("companion", 1, "snap"))),
        has_more=False,
    )
    assert [row["metadata"]["binding_id"] for row in rows] == ["companion"]
    assert omissions == ()
    assert complete is True and has_more is False


def test_page_limit_discloses_incomplete_scope_after_valid_page() -> None:
    request = CurrentObservationQuery("token", limit=1).validate()
    rows, omissions, complete, has_more = _page_rows(
        request, (_candidate("core", "pkg/answer.py"),),
        _snapshot_map((("core", 1, "snap"),)), has_more=True,
    )
    assert len(rows) == 1
    assert complete is False and has_more is True
    assert omissions == (OmissionRecord(
        "scope", None, "observation_page_limit",
        "bounded current-observation page omitted additional matching rows",
    ).validate(),)


@pytest.mark.parametrize("vector", [(("core", True, "snap"),), (("core", 1),), ("bad",)])
def test_snapshot_vector_malformed_values_refuse(vector: object) -> None:
    with pytest.raises(CurrentObservationReadError, match="malformed_snapshot_vector"):
        _snapshot_map(cast(Sequence[Sequence[object]], vector))


def test_unknown_binding_and_snapshot_mismatch_refuse() -> None:
    request = CurrentObservationQuery("token").validate()
    with pytest.raises(CurrentObservationReadError, match="unknown_selected_binding"):
        _page_rows(
            CurrentObservationQuery("token", selected_binding_ids=("foreign",)).validate(),
            (), _snapshot_map((("core", 1, "snap"),)), has_more=False,
        )
    with pytest.raises(CurrentObservationReadError, match="unknown_observation_binding"):
        _page_rows(request, (_candidate("foreign", "pkg/a.py"),),
                   _snapshot_map((("core", 1, "snap"),)), has_more=False)

def test_missing_metadata_fields_refuse_before_scope_filter() -> None:
    request = CurrentObservationQuery(
        "pkg/a.py", selected_binding_ids=("core",), source_path_prefix="pkg"
    ).validate()
    malformed = ({"ordinal": 1, "kind": "python.function", "source_id": "core", "path": "pkg/a.py"},
                 {"metadata": {"binding_id": "core", "binding_revision": 1, "snapshot_id": "snap"}})
    with pytest.raises(CurrentObservationReadError, match="malformed_observation_metadata"):
        _page_rows(request, (malformed,), _snapshot_map((("core", 1, "snap"),)), has_more=False)
    with pytest.raises(CurrentObservationReadError, match="observation_snapshot_mismatch"):
        _page_rows(request, (_candidate("core", "pkg/a.py", snapshot="wrong"),),
                   _snapshot_map((("core", 1, "snap"),)), has_more=False)


@pytest.mark.parametrize("query_request", [
    CurrentObservationQuery(""), CurrentObservationQuery("x", limit=0),
    CurrentObservationQuery("bad\x00query"),
    CurrentObservationQuery("x" * 201), CurrentObservationQuery("x", limit=True),
    CurrentObservationQuery("x", offset=False), CurrentObservationQuery("x", offset=10001),
    CurrentObservationQuery("x", kind="bad\x00kind"), CurrentObservationQuery("x", path="bad\x00path"),
    CurrentObservationQuery("x", selected_binding_ids=("core", "core")),
    CurrentObservationQuery("x", limit=101), CurrentObservationQuery("x", offset=-1),
    CurrentObservationQuery("x", selected_binding_ids=cast(Sequence[str], "core")),
    CurrentObservationQuery("x", source_path_prefix="../pkg"),
])
def test_request_bounds_and_scope_types_refuse(query_request: CurrentObservationQuery) -> None:
    with pytest.raises(ValueError):
        query_request.validate()



class _Cursor:
    def __init__(self, rows: Sequence[tuple[int, str, str, str, str]]) -> None:
        self._rows = rows
        self.closed = False

    def __iter__(self) -> Iterator[tuple[int, str, str, str, str]]:
        return iter(self._rows)

    def close(self) -> None:
        self.closed = True


def _sqlite_row(ordinal: int, metadata: object) -> tuple[int, str, str, str, str]:
    return (
        ordinal, "python.function", "core", f"core/pkg/{ordinal}.py",
        json.dumps({"metadata": metadata, "text": "B2_LATE_TOKEN"}),
    )


def _sqlite_valid_metadata(ordinal: int) -> dict[str, object]:
    return {
        "binding_id": "core", "binding_revision": 1,
        "snapshot_id": "snap", "source_relative_path": f"pkg/{ordinal}.py",
    }


def test_sqlite_scan_keeps_bounded_page_candidates_and_has_more() -> None:
    request = CurrentObservationQuery(
        "B2_LATE_TOKEN", limit=1, selected_binding_ids=("core",),
        source_path_prefix="pkg",
    ).validate()
    snapshots = _snapshot_map((("core", 1, "snap"),))
    cursor = _Cursor((_sqlite_row(1, _sqlite_valid_metadata(1)),
                      _sqlite_row(2, _sqlite_valid_metadata(2))))
    candidates, has_more, known_bytes = _scan_sqlite_observations(
        cursor, request, snapshots, {"core"}, fetch_limit=2,
    )
    assert cursor.closed and has_more and len(candidates) == 2 and known_bytes > 0
    rows, omissions, complete, page_has_more = _page_rows(
        request, candidates, snapshots, has_more=has_more,
    )
    assert [row["path"] for row in rows] == ["core/pkg/1.py"]
    assert len(omissions) == 1 and complete is False and page_has_more is True


@pytest.mark.parametrize(
    ("metadata", "error"),
    (
        ({}, "malformed_observation_metadata"),
        ({
            "binding_id": "foreign-binding", "binding_revision": 1,
            "snapshot_id": "snap", "source_relative_path": "pkg/late.py",
        }, "unknown_observation_binding"),
    ),
)
def test_sqlite_scan_refuses_late_matching_metadata_after_page_window(
    metadata: object, error: str,
) -> None:
    request = CurrentObservationQuery(
        "B2_LATE_TOKEN", limit=1, selected_binding_ids=("core",),
        source_path_prefix="pkg",
    ).validate()
    snapshots = _snapshot_map((("core", 1, "snap"),))
    cursor = _Cursor((
        _sqlite_row(1, _sqlite_valid_metadata(1)),
        _sqlite_row(2, _sqlite_valid_metadata(2)),
        _sqlite_row(3, metadata),
    ))
    with pytest.raises(CurrentObservationReadError, match=error):
        _scan_sqlite_observations(cursor, request, snapshots, {"core"}, fetch_limit=2)
    assert cursor.closed

def test_candidate_archive_binds_current_reader_and_publication_dependencies() -> None:
    """The archive-before-query closure includes all new executed evaluator owners."""
    from retrieval_evaluation_admission import candidate_source_files

    root = Path(__file__).resolve().parents[5]
    captured = candidate_source_files(root)
    for relative in (
        "tools/retrieval_evaluation_current_observations.py",
        "tools/retrieval_evaluation_correspondence_observation_records.py",
        "tools/retrieval_evaluation_correspondence_graph_scope.py",
        "src/test/support/python/repomap_test_support/retrieval_evaluation_publication_readback.py",
    ):
        assert captured[relative] == (root / relative).read_bytes()
    # Protect direct runtime imports of the current-read boundary, including
    # semantic pin validation outside the older retrieval_evaluation glob.
    owners = (
        "tools/retrieval_evaluation_current_observations.py",
        "tools/retrieval_evaluation_correspondence_observation_records.py",
        "tools/retrieval_evaluation_correspondence_graph_scope.py",
        "tools/retrieval_evaluation_graph.py",
    )
    for owner in owners:
        for node in ast.walk(ast.parse((root / owner).read_text())):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            module = node.module
            if module.startswith("common_lore_index."):
                candidate = "src/main/python/" + module.replace(".", "/")
            elif module.startswith(("retrieval_evaluation", "retrieval_semantic")):
                candidate = "tools/" + module
            else:
                continue
            relative = candidate + ".py" if (root / (candidate + ".py")).is_file() else candidate + "/__init__.py"
            assert relative in captured, (owner, module)
