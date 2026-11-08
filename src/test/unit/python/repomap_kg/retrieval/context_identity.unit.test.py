"""Accepted-publication identity and bounded PostgreSQL context readbacks."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.server.context_read_postgres import PostgresContextReadAdapter
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.errors import StorageSchemaError

from common_lore_index.retrieval.context_identity import (
    ContextIdentityError,
    attach_vector_status,
    normalize_accepted_publication,
    parse_snapshot_vector,
    validate_accepted_pin_mapping,
)


BINDING = "bind1:context-identity"
SNAPSHOT = "snap1:context-identity"


def _accepted(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "generation": 1, "accepted_run_id": 1,
        "run_id": 1, "publication_bundle_id": "bundle1:context-identity",
        "snapshot_manifest_id": "manifest1:context-identity",
        "extraction_receipt_id": "receipt1:context-identity",
        "job_id": "job-context-identity", "publication_job_id": "job-context-identity",
        "attempt": 1, "publication_attempt": 1,
        "snapshot_vector": [[BINDING, 1, SNAPSHOT]],
    }
    value.update(overrides)
    return value


def test_parse_snapshot_vector_accepts_equal_compatibility_aliases() -> None:
    raw = [{
        "binding_id": BINDING, "source_binding_id": BINDING,
        "revision": 3, "binding_revision": 3,
        "snapshot_id": SNAPSHOT,
    }]
    assert parse_snapshot_vector(raw) == ((BINDING, 3, SNAPSHOT),)


@pytest.mark.parametrize(
    "raw",
    [
        [{"binding_id": BINDING, "source_binding_id": "bind1:other", "revision": 1, "snapshot_id": SNAPSHOT}],
        [{"binding_id": BINDING, "revision": 1, "binding_revision": 2, "snapshot_id": SNAPSHOT}],
        [{"binding_id": BINDING, "revision": 1, "snapshot_id": SNAPSHOT, "extra": True}],
        [[BINDING, True, SNAPSHOT]],
        [[BINDING, 0, SNAPSHOT]],
        [[BINDING, 1, ""]],
    ],
)
def test_parse_snapshot_vector_refuses_conflicting_or_noncanonical_entries(raw: Any) -> None:
    with pytest.raises(ContextIdentityError):
        parse_snapshot_vector(raw)


@pytest.mark.parametrize(
    "raw",
    [
        [],
        [[BINDING, 1, SNAPSHOT], [BINDING, 1, SNAPSHOT]],
        {"binding_id": BINDING},
        "not-a-vector",
    ],
)
def test_parse_snapshot_vector_refuses_empty_duplicate_and_wrong_shapes(raw: Any) -> None:
    with pytest.raises(ContextIdentityError):
        parse_snapshot_vector(raw)


def test_normalize_accepted_publication_canonicalizes_json_and_optional_provenance() -> None:
    accepted = _accepted(
        snapshot_vector_json=json.dumps([[BINDING, 1, SNAPSHOT]], separators=(",", ":")),
    )
    accepted.pop("snapshot_vector")
    normalized = normalize_accepted_publication(accepted)
    assert normalized["accepted_run_id"] == normalized["run_id"] == 1
    assert normalized["job_id"] == normalized["publication_job_id"] == "job-context-identity"
    assert normalized["attempt"] == normalized["publication_attempt"] == 1
    assert normalized["snapshot_vector"] == ((BINDING, 1, SNAPSHOT),)

    unpinned = _accepted()
    for key in ("job_id", "publication_job_id", "attempt", "publication_attempt"):
        unpinned.pop(key)
    optional = normalize_accepted_publication(unpinned)
    assert optional["job_id"] is None and optional["attempt"] is None
    assert optional["snapshot_vector"] == ((BINDING, 1, SNAPSHOT),)


def test_normalize_accepted_publication_requires_strong_pin_and_preserves_no_vector_mode() -> None:
    unpinned = _accepted()
    for key in ("job_id", "publication_job_id", "attempt", "publication_attempt"):
        unpinned.pop(key)
    with pytest.raises(ContextIdentityError, match="job/attempt provenance"):
        normalize_accepted_publication(unpinned, require_pin=True)

    no_vector = _accepted()
    no_vector.pop("snapshot_vector")
    no_vector.pop("job_id")
    no_vector.pop("publication_job_id")
    no_vector.pop("attempt")
    no_vector.pop("publication_attempt")
    normalized = validate_accepted_pin_mapping(_accepted())
    assert normalized["snapshot_vector"] == ((BINDING, 1, SNAPSHOT),)
    assert normalize_accepted_publication(no_vector, require_vector=False)["snapshot_vector"] == ()


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [("generation", True), ("accepted_run_id", 1.0), ("run_id", 0), ("publication_bundle_id", "")],
)
def test_normalize_accepted_publication_refuses_invalid_required_fields(
    field: str, bad_value: Any,
) -> None:
    accepted = _accepted(**{field: bad_value})
    with pytest.raises(ContextIdentityError):
        normalize_accepted_publication(accepted)


def test_normalize_accepted_publication_refuses_non_mapping_input() -> None:
    with pytest.raises(ContextIdentityError, match="must be a mapping"):
        normalize_accepted_publication(cast(Any, []))


def test_normalize_accepted_publication_refuses_alias_and_vector_disagreement() -> None:
    aliases = _accepted(run_id=2)
    with pytest.raises(ContextIdentityError, match="disagrees with run_id"):
        normalize_accepted_publication(aliases)

    vectors = _accepted(snapshot_vector_json=[[BINDING, 2, SNAPSHOT]])
    with pytest.raises(ContextIdentityError, match="snapshot_vector_json"):
        normalize_accepted_publication(vectors)


def test_attach_vector_status_backfills_matching_revision_and_accepts_mapping_aliases() -> None:
    location: dict[str, Any] = {
        "source": {"binding_id": BINDING, "snapshot_id": SNAPSHOT},
    }
    result = attach_vector_status(
        location,
        [{
            "source_binding_id": BINDING,
            "binding_revision": 4,
            "snapshot_id": SNAPSHOT,
        }],
    )
    assert result["source_identity_status"] == "verified_vector"
    assert result["source"]["binding_revision"] == 4


@pytest.mark.parametrize(
    "location",
    [
        {"source": {"binding_id": BINDING, "snapshot_id": SNAPSHOT, "binding_revision": 2}},
        {"source": {"binding_id": BINDING, "snapshot_id": "snap1:other", "binding_revision": 1}},
        {"source": {"binding_id": "bind1:other", "snapshot_id": SNAPSHOT, "binding_revision": 1}},
        {"source": [BINDING, 1, SNAPSHOT]},
    ],
)
def test_attach_vector_status_refuses_conflicting_source_identity(location: dict[str, Any]) -> None:
    result = attach_vector_status(location, [(BINDING, 1, SNAPSHOT)])
    assert result["source_identity_status"] == "unbound_or_conflicting_vector"


def test_attach_vector_status_preserves_existing_status_and_malformed_vectors() -> None:
    existing: dict[str, Any] = {
        "source_identity_status": "withheld",
        "source": {"binding_id": BINDING, "snapshot_id": SNAPSHOT},
    }
    assert attach_vector_status(existing, [(BINDING, 1, SNAPSHOT)]) is existing
    assert existing["source_identity_status"] == "withheld"

    malformed = attach_vector_status(
        {"source": {"binding_id": BINDING, "snapshot_id": SNAPSHOT}},
        [[BINDING, True, SNAPSHOT]],
    )
    assert malformed["source_identity_status"] == "unbound_or_conflicting_vector"


_VECTOR = [["binding:public", 7, "snapshot:public"]]

_ACCEPTED = {
    "repository_id": 91, "generation": 4, "run_id": 17,
    "publication_bundle_id": "bundle:public",
    "snapshot_manifest_id": "manifest:public",
    "extraction_receipt_id": "receipt:public",
    "graph_candidate_id": "candidate:public",
    "publication_job_id": "job:public",
    "publication_attempt": 1,
    "snapshot_vector_json": _VECTOR,
}

_EXPECTED = {
    "repository_id": 91,
    "generation": 4,
    "accepted_run_id": 17,
    "publication_bundle_id": "bundle:public",
    "snapshot_manifest_id": "manifest:public",
    "extraction_receipt_id": "receipt:public",
    "job_id": "job:public",
    "attempt": 1,
    "snapshot_vector": _VECTOR,
}


def _payload(edges: list[dict[str, Any]], *, overflow: bool = False) -> dict[str, Any]:
    return {
        "has_accepted": True,
        "transport_overflow": overflow,
        "accepted": _ACCEPTED,
        "truncated_seeds": 0,
        "relation_limit_hits": 0,
        "node_limit_hits": 0,
        "edges": edges,
        "evidence": [],
    }


def _evidence(node_id: int = 101) -> dict[str, Any]:
    return {
        "evidence_key": "evidence:public", "link_kind": "observed",
        "run_id": 17, "raw_observation_ordinal": 1,
        "payload_hash": "hash:public", "raw_kind": "python.function",
        "raw_source_id": "source:public", "path": "src/example.py",
        "start_line": 1, "end_line": 2,
        "extractor": "fixture", "extractor_version": "1",
        "confidence": "extracted",
        "metadata_json": {
            "binding_id": "binding:public", "binding_alias": "public",
            "binding_revision": 7, "snapshot_id": "snapshot:public",
            "source_relative_path": "src/example.py",
        },
        "publication_bundle_id": "bundle:public", "snapshot_manifest_id": "manifest:public",
        "extraction_receipt_id": "receipt:public", "graph_candidate_id": "candidate:public",
        "snapshot_vector_json": _VECTOR, "evidence_role": "direct",
        "node_id": node_id, "subject_canonical_key": "repo:seed",
    }


def _navigation_payload(
    *, accepted: dict[str, Any] | None = None, has_accepted: bool = True,
    transport_overflow: bool = False,
) -> dict[str, Any]:
    return {
        "has_accepted": has_accepted,
        "accepted": _ACCEPTED if accepted is None else accepted,
        "candidate_nodes": [], "direct_evidence": [],
        "transport_overflow": transport_overflow,
    }


def _node_payload(
    *, accepted: dict[str, Any] | None = None, has_accepted: bool = True,
    has_node: bool = True, current_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "has_accepted": has_accepted,
        "accepted": _ACCEPTED if accepted is None else accepted,
        "transport_overflow": False,
        "has_node": has_node,
        "node": {
            "id": 101, "metadata_json": {}, "first_seen_run_id": 12,
            "last_seen_run_id": 17, "kind": "python.function", "display_name": "fn",
        },
        "selected_run_id": 17,
        "current_rows": [_evidence(101)] if current_rows is None else current_rows,
        "historical_rows": [],
    }


def test_postgres_adapter_identity_and_expansion_use_bounded_executor() -> None:
    identity_calls: list[str] = []

    def identity_executor(sql: str) -> dict[str, Any]:
        identity_calls.append(sql)
        return {"has_accepted": True, "accepted": _ACCEPTED}

    adapter = PostgresContextReadAdapter(
        graph_id="graph:test", repository_id="repo:public", executor=identity_executor,
    )
    identity_ledger = WorkLedger(backend="postgresql")
    identity = adapter.read_initial_identity(identity_ledger)
    assert identity["status"] == "ok"
    assert identity["accepted_publication"]["accepted_run_id"] == 17
    assert identity_ledger.sql_statements_executed == 1
    assert len(identity_calls) == 1
    expansion_calls: list[str] = []

    def execute(sql: str) -> dict[str, Any]:
        expansion_calls.append(sql)
        return _payload([])
    expansion = PostgresContextReadAdapter(
        graph_id="graph:test", repository_id="repo:public",
        executor=execute,
    )
    expansion_ledger = WorkLedger(backend="postgresql")
    result = expansion.expand_seeds_depth1(
        ("repo:seed",), edge_kinds=("calls",), node_limit=4, edge_limit=3,
        ledger=expansion_ledger, expected_identity=_EXPECTED,
    )
    assert result["status"] == "ok"
    assert result["seeds_expanded"] == 1
    assert expansion_ledger.seed_expansions_executed == 1
    assert len(expansion_calls) == 1


def test_postgres_adapter_budget_is_checked_before_io() -> None:
    calls: list[str] = []

    def execute(sql: str) -> dict[str, Any]:
        calls.append(sql)
        return _payload([])

    adapter = PostgresContextReadAdapter(
        graph_id="graph:test", repository_id="repo:public",
        executor=execute,
    )
    result = adapter.expand_seeds_depth1(
        ("repo:seed",), edge_kinds=("calls",), node_limit=4, edge_limit=3,
        ledger=WorkLedger(backend="postgresql", max_sql_statements=0),
        expected_identity=_EXPECTED,
    )
    assert result["status"] == "partial"
    assert result["reason"] == "statement_limit"
    assert calls == []


@pytest.mark.parametrize(
    ("error", "reason"),
    ((RuntimeError("driver down"), "database_unavailable"),
     (StorageSchemaError("bad JSON"), "accepted_publication_unverified")),
)
def test_postgres_adapter_translates_identity_driver_failures(
    error: Exception, reason: str,
) -> None:
    def execute(_sql: str) -> Any:
        raise error

    adapter = PostgresContextReadAdapter(
        graph_id="graph:test", repository_id="repo:public", executor=execute,
    )
    assert adapter.read_initial_identity(WorkLedger(backend="postgresql")) == {
        "status": "unavailable", "reason": reason,
    }


def test_postgres_adapter_navigation_rechecks_identity_and_accounts_scan() -> None:
    query = NavigationSearchQuery(query="needle", source_binding_id="binding:public")
    adapter = PostgresContextReadAdapter(
        graph_id="graph:test", repository_id="repo:public",
        executor=lambda _sql: _navigation_payload(),
    )
    ledger = WorkLedger(backend="postgresql")
    result = adapter.query_candidates_unit(query, ledger=ledger, expected_identity=_EXPECTED)
    assert result["status"] == "ok"
    assert result["scan"]["complete"] is True
    assert ledger.scan_units_executed == 1
    changed = dict(_ACCEPTED, run_id=18)
    stale_adapter = PostgresContextReadAdapter(
        graph_id="graph:test", repository_id="repo:public",
        executor=lambda _sql: _navigation_payload(accepted=changed),
    )
    stale = stale_adapter.query_candidates_unit(
        NavigationSearchQuery(query="needle"), ledger=WorkLedger(backend="postgresql"),
        expected_identity=_EXPECTED,
    )
    assert stale == {
        "status": "stale", "reason": "publication_advanced_during_assembly",
    }


def test_postgres_adapter_node_locations_handles_verified_and_absent_nodes() -> None:
    adapter = PostgresContextReadAdapter(
        graph_id="graph:test", repository_id="repo:public",
        executor=lambda _sql: _node_payload(),
    )
    result = adapter.query_node_by_canonical_key(
        "repo:neighbor", ledger=WorkLedger(backend="postgresql"),
        expected_identity=_EXPECTED,
    )
    assert result["status"] == "ok"
    assert result["node"]["locations"][0]["source_identity_status"] == "verified_vector"
    absent = PostgresContextReadAdapter(
        graph_id="graph:test", repository_id="repo:public",
        executor=lambda _sql: _node_payload(has_node=False),
    ).query_node_by_canonical_key(
        "repo:missing", ledger=WorkLedger(backend="postgresql"),
        expected_identity=_EXPECTED,
    )
    assert absent == {"status": "ok", "node": None}
