from __future__ import annotations

import hashlib
import json
from typing import Any, cast

import psycopg
import pytest

from repomap_kg.storage.structural_digest import STRUCTURAL_DIGEST_FAMILY_CODES
from scale15_actual_path_readback import _read_semantic_digest
from scale15_terminal_contracts import FINAL_FAMILY_CODES


def _semantic_rows():
    return {
        "files": [
            ("a.py", "python", "source", "a" * 64, False, False, {})
        ],
        "raw_observations": [
            (0, 1, "file", "a.py", "a.py", {"kind": "file"}, "b" * 64)
        ],
        "canonical_nodes": [
            (1, "file:a.py", "file", "a.py", {}, "extracted", False)
        ],
        "canonical_edges": [],
        "canonical_evidence": [],
        "canonical_node_evidence": [],
        "canonical_edge_evidence": [],
    }


def _reference(rows) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class _Cursor:
    def __init__(self, family, rows, events, *, fail=False) -> None:
        self.family = family
        self.rows = rows
        self.events = events
        self.fail = fail

    def execute(self, query, parameters) -> None:
        assert " ORDER BY " in query
        assert parameters in ((7,), (7, 11))
        self.events.append(("execute", self.family))

    def __iter__(self):
        for row in self.rows:
            self.events.append(("row", self.family))
            yield row
        if self.fail:
            raise RuntimeError("private readback failure")

    def close(self) -> None:
        self.events.append(("close", self.family))


class _Connection:
    def __init__(self, rows, *, failing_family=None) -> None:
        self.rows = rows
        self.events: list[tuple[str, str]] = []
        self.failing_family = failing_family

    def cursor(self, *, name):
        prefix = "repomap_structural_digest_"
        assert name.startswith(prefix)
        family = name.removeprefix(prefix)
        open_families = [
            item
            for action, item in self.events
            if action == "open"
            and ("close", item) not in self.events
        ]
        assert open_families == []
        self.events.append(("open", family))
        return _Cursor(
            family,
            self.rows[family],
            self.events,
            fail=family == self.failing_family,
        )


def test_readback_streams_one_ordered_server_cursor_per_family() -> None:
    rows = _semantic_rows()
    connection = _Connection(rows)

    counts, digest = _read_semantic_digest(cast(psycopg.Connection[Any], connection), 7, 11)

    assert counts == {family: len(rows[family]) for family in rows}
    assert tuple(counts) == FINAL_FAMILY_CODES
    assert digest == _reference(rows)
    assert [
        family for action, family in connection.events if action == "open"
    ] == list(STRUCTURAL_DIGEST_FAMILY_CODES)
    assert [
        family for action, family in connection.events if action == "close"
    ] == list(STRUCTURAL_DIGEST_FAMILY_CODES)


def test_readback_closes_the_active_cursor_on_failure() -> None:
    rows = _semantic_rows()
    rows["canonical_edges"] = [
        (1, "source", "kind", "target", {}, "c" * 64, {}, "extracted", False)
    ]
    connection = _Connection(rows, failing_family="canonical_edges")

    with pytest.raises(RuntimeError, match="private readback failure"):
        _read_semantic_digest(cast(psycopg.Connection[Any], connection), 7, 11)

    assert ("close", "canonical_edges") in connection.events
    assert ("open", "canonical_evidence") not in connection.events


def test_readback_closes_the_active_cursor_on_cancellation() -> None:
    connection = _Connection(_semantic_rows())
    checks = 0

    def cancel() -> None:
        nonlocal checks
        checks += 1
        if checks == 8:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _read_semantic_digest(cast(psycopg.Connection[Any], connection), 7, 11, cancellation_check=cancel)

    open_family = next(
        family
        for action, family in reversed(connection.events)
        if action == "open"
    )
    assert ("close", open_family) in connection.events
