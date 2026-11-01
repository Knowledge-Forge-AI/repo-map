"""Focused W3 unit contracts for PostgreSQL metadata admission and wire bounds."""

from __future__ import annotations

import json
from typing import Any

import pytest

from common_lore_index.server._navigation_groups import source_scope_admission
from common_lore_index.server._ops_sanitization import _public_location
from common_lore_index.storage.navigation_search import (
    NODE_SCAN_LIMIT,
    NavigationSearchQuery,
)
from common_lore_index.storage.node_locations import NodeLocationsQuery
from common_lore_index.storage.postgres_navigation_search import (
    read_postgres_navigation_search_with_executor,
)
from common_lore_index.storage.postgres_node_locations import (
    read_postgres_node_locations_with_executor,
)
from common_lore_index.storage.sqlite_local import navigation_queries as sqlite_navigation


_ACCEPTED = {
    "generation": 4,
    "run_id": 17,
    "publication_bundle_id": "bundle1:" + "a" * 64,
}
_BINDING = "bind1:public"
_VECTOR = [{"binding_id": _BINDING, "revision": 7, "snapshot_id": "snap1:public"}]


def _node(node_id: int, key: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "canonical_key": key,
        "kind": "python.module",
        "display_name": key.rsplit(":", 1)[-1],
        "first_seen_run_id": 17,
        "last_seen_run_id": 17,
    }


def _evidence(
    node_id: int,
    path: str,
    *,
    run_id: int = 17,
    binding_id: str = _BINDING,
    metadata_extra: dict[str, Any] | None = None,
    vector: list[Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "binding_id": binding_id,
        "binding_alias": "public",
        "snapshot_id": "snap1:public",
        # The vector is the corroborating source of this revision.
        "source_relative_path": path,
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    return {
        "evidence_key": f"ev1:{node_id}",
        "link_kind": "observed",
        "run_id": run_id,
        "raw_observation_ordinal": node_id,
        "payload_hash": "a" * 64,
        "raw_kind": "python.module",
        "raw_source_id": f"src1:{node_id}",
        "path": path,
        "start_line": 1,
        "end_line": 3,
        "extractor": "fixture",
        "extractor_version": "1",
        "confidence": "extracted",
        "metadata_json": metadata,
        "publication_bundle_id": _ACCEPTED["publication_bundle_id"],
        "snapshot_manifest_id": "snapmanifest1:" + "b" * 64,
        "extraction_receipt_id": "receipt1:" + "c" * 64,
        "graph_candidate_id": "cand1:" + "d" * 64,
        "snapshot_vector_json": _VECTOR if vector is None else vector,
        "evidence_role": "direct",
        "node_id": node_id,
    }


def _navigation_payload(
    nodes: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    *,
    transport_overflow: bool = False,
) -> dict[str, Any]:
    return {
        "has_accepted": True,
        "accepted": _ACCEPTED,
        "candidate_nodes": nodes,
        "direct_evidence": evidence,
        "transport_overflow": transport_overflow,
    }


def _location_payload(
    current_rows: list[dict[str, Any]],
    *,
    historical_rows: list[dict[str, Any]] | None = None,
    metadata_json: dict[str, Any] | None = None,
    selected_run_id: int | None = 17,
) -> dict[str, Any]:
    return {
        "has_accepted": True,
        "accepted": _ACCEPTED,
        "has_node": True,
        "node": {
            "id": 91,
            "metadata_json": metadata_json or {"doc_path": "nested/a..b.md"},
            "first_seen_run_id": 12,
            "last_seen_run_id": 17,
        },
        "selected_run_id": selected_run_id,
        "current_rows": current_rows,
        "historical_rows": historical_rows or [],
    }


def test_scoped_admission_reaches_public_candidate_after_node_scan_prefix() -> None:
    """Out-of-scope/private candidates must not consume the 2,000-node cap."""
    query = NavigationSearchQuery(
        query="needle",
        scope="code",
        source_binding_id=_BINDING,
        source_path_prefix="nested",
        limit=5,
    )
    private_count = NODE_SCAN_LIMIT + 1
    nodes = [_node(index, f"needle:private:{index:04d}") for index in range(private_count)]
    nodes.append(_node(private_count + 1, "needle:public"))
    evidence = [
        _evidence(index, f"[private-path]/secret-{index:04d}.py")
        for index in range(private_count)
    ]
    evidence.append(_evidence(private_count + 1, "nested/a..b.py"))
    admit = source_scope_admission(query, ("[private-path]", "[private-root]", "[REDACTED]"))
    result = read_postgres_navigation_search_with_executor(
        query,
        executor=lambda _sql: _navigation_payload(nodes, evidence),
        admits_location=admit,
        repository_identity="repo:w3",
        root_path="graph:w3",
    )

    assert result["status"] == "ok"
    assert [node["canonical_key"] for node in result["nodes"]] == ["needle:public"]
    assert result["scan"]["complete"] is True
    assert result["scan"]["admission"]["checks"] == private_count + 1
    location = result["nodes"][0]["locations"][0]
    assert location["path"] == "nested/a..b.py"
    assert location["source"]["binding_revision"] == 7
    assert "[private-path]" not in json.dumps(result, ensure_ascii=False)


def test_scoped_admission_count_overflow_is_incomplete_not_complete_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bounded admission count must produce incomplete work, never empty success."""
    monkeypatch.setattr(sqlite_navigation, "ADMISSION_CHECK_LIMIT", 2)
    nodes = [_node(index, f"needle:{index}") for index in range(3)]
    evidence = [_evidence(index, f"nested/{index}.py") for index in range(3)]
    calls: list[str] = []

    def admit(location: dict[str, Any]) -> bool:
        calls.append(str(location["path"]))
        return True

    result = read_postgres_navigation_search_with_executor(
        NavigationSearchQuery(query="needle", source_binding_id=_BINDING, limit=5),
        executor=lambda _sql: _navigation_payload(nodes, evidence),
        admits_location=admit,
        repository_identity="repo:w3",
        root_path="graph:w3",
    )

    assert result["status"] == "incomplete"
    assert result["reason"] == "admission_work_limit"
    assert result["nodes"] == []
    assert result["scan"]["complete"] is False
    assert result["scan"]["admission"]["checks"] == 2
    assert result["scan"]["admission"]["budget_exhausted"] is True
    assert calls == ["nested/0.py", "nested/1.py"]


@pytest.mark.parametrize("source_binding_id", [_BINDING, None])
def test_transport_overflow_short_circuits_python_admission(
    source_binding_id: str | None,
) -> None:
    """SQL overflow is consumed before Python admission for scoped and broad reads."""
    calls: list[dict[str, Any]] = []

    def must_not_admit(location: dict[str, Any]) -> bool:
        calls.append(location)
        raise AssertionError("oversized SQL result reached Python admission")

    result = read_postgres_navigation_search_with_executor(
        NavigationSearchQuery(query="needle", source_binding_id=source_binding_id, limit=5),
        executor=lambda _sql: _navigation_payload(
            [_node(1, "needle:oversized")],
            [_evidence(1, "nested/oversized.py", metadata_extra={"payload": "x" * 4096})],
            transport_overflow=True,
        ),
        admits_location=must_not_admit,
        repository_identity="repo:w3",
        root_path="graph:w3",
    )

    assert result["status"] == "incomplete"
    assert result["reason"] == "admission_work_limit"
    assert result["nodes"] == []
    assert calls == []


def test_navigation_executor_uses_one_request_statement() -> None:
    """One readback request invokes one SQL statement, preserving one snapshot."""
    statements: list[str] = []
    def execute(sql: str) -> dict[str, Any]:
        statements.append(sql)
        return _navigation_payload([_node(1, "needle:one")], [_evidence(1, "nested/a..b.py")])
    result = read_postgres_navigation_search_with_executor(
        NavigationSearchQuery(query="needle", limit=5),
        executor=execute,
        repository_identity="repo:w3",
        root_path="graph:w3",
    )
    assert result["status"] == "ok"
    assert len(statements) == 1


def test_node_locations_preserves_nested_path_revision_fallback_and_history() -> None:
    """Node locations retain SQLite wire facts, including vector-only revisions."""
    current = _evidence(91, "nested/a..b.py")
    historical = _evidence(
        92,
        "nested/old.py",
        run_id=12,
        vector=[{"binding_id": _BINDING, "revision": 6, "snapshot_id": "snap1:old"}],
    )
    result = read_postgres_node_locations_with_executor(
        NodeLocationsQuery(canonical_key="module:needle", evidence_role="direct", limit=5),
        executor=lambda _sql: _location_payload([current], historical_rows=[historical]),
        repository_identity="repo:w3",
        root_path="graph:w3",
    )
    assert result["status"] == "ok"
    assert result["locations"][0]["path"] == "nested/a..b.py"
    assert result["locations"][0]["source"]["binding_revision"] == 7
    assert result["historical_locations"][0]["path"] == "nested/old.py"
    assert result["historical_locations"][0]["publication_relation"] == "historical_run"
    assert result["metadata_location"]["path"] == "nested/a..b.md"


def test_private_location_redaction_does_not_manufacture_identity() -> None:
    """Private markers redact path surfaces and fail closed for source admission."""
    query = NavigationSearchQuery(query="needle", source_binding_id=_BINDING, limit=5)
    result = read_postgres_navigation_search_with_executor(
        query,
        executor=lambda _sql: _navigation_payload(
            [_node(1, "needle:private")], [_evidence(1, "[private-root]/secret.py")]
        ),
        admits_location=source_scope_admission(query, ("[private-root]",)),
        repository_identity="repo:w3",
        root_path="graph:w3",
    )
    assert result["status"] == "ok"
    assert result["nodes"] == []
    assert result["scan"]["complete"] is True
    public = _public_location(
        {
            "path": "[private-root]/secret.py",
            "start_line": 1,
            "end_line": 3,
            "source": {
                "binding_id": _BINDING,
                "binding_revision": 7,
                "snapshot_id": "snap1:public",
                "source_relative_path": "[private-root]/secret.py",
            },
        },
        ("[private-root]",),
    )
    assert public["path"] is None
    assert public["source"]["source_relative_path"] is None
