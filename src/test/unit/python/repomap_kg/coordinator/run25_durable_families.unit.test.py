"""Unit tests for run25_durable_families assertion helpers and contracts."""

from __future__ import annotations

from dataclasses import asdict
import sqlite3
from typing import Any, Mapping, Sequence
from unittest.mock import MagicMock

import pytest

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES
from repomap_kg.storage.staging_family_contracts import StageFamily
from repomap_test_support.portable_publication_fixtures import _seven_family_bundle
from repomap_test_support.run25_durable_families import (
    ConflictingPayloadError,
    DuplicateIdentityError,
    DurableFamilyVerificationError,
    ExtraIdentityError,
    FamilyVerificationCounts,
    MissingIdentityError,
    StaleLastSeenError,
    _SPECS,
    assert_durable_families,
    verify_family_rows,
)


def _make_db_rows_from_bundle(
    family: str,
    bundle_rows: Sequence[Mapping[str, object]],
    run_id: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for b_row in bundle_rows:
        r = dict(b_row)
        if family == "files":
            r.pop("confidence", None)
            r["last_seen_run_id"] = run_id
        elif family == "raw_observations":
            r["ordinal"] = r.pop("source_ordinal")
            r["run_id"] = run_id
        elif family in ("canonical_nodes", "canonical_edges"):
            r["last_seen_run_id"] = run_id
        elif family == "canonical_evidence":
            r["run_id"] = run_id
        rows.append(r)
    return rows


def test_family_verification_counts_contract() -> None:
    counts = FamilyVerificationCounts("files", 5, 4, 4, 4)
    assert counts.family == "files"
    assert counts.input_rows == 5
    assert counts.expected_distinct == 4
    assert counts.persisted_rows == 4
    assert counts.persisted_distinct == 4
    assert asdict(counts) == {
        "family": "files",
        "input_rows": 5,
        "expected_distinct": 4,
        "persisted_rows": 4,
        "persisted_distinct": 4,
    }
    with pytest.raises(AttributeError):
        setattr(counts, "input_rows", 10)


def test_verify_family_rows_success_all_seven_families() -> None:
    bundle = _seven_family_bundle()
    run_id = 42
    recorded: dict[str, Any] = {}

    def record_prop(k: str, v: Any) -> None:
        recorded[k] = v

    for family in PUBLICATION_FAMILIES:
        bundle_rows = bundle.families[family]
        assert bundle_rows, f"Expected non-empty fixture for {family}"
        db_rows = _make_db_rows_from_bundle(family, bundle_rows, run_id)

        # Dict rows verification
        counts = verify_family_rows(
            family, bundle_rows, db_rows, run_id, record_property=record_prop
        )
        assert counts.input_rows == len(bundle_rows)
        assert counts.expected_distinct == len(bundle_rows)
        assert counts.persisted_rows == len(bundle_rows)
        assert counts.persisted_distinct == len(bundle_rows)
        assert recorded[f"durable_{family}_counts"] == asdict(counts)

        # Sequence/tuple rows verification with column_names
        spec = _SPECS[family]
        col_names = spec.query_columns
        tuple_rows = [tuple(r.get(c) for c in col_names) for r in db_rows]
        tuple_counts = verify_family_rows(
            family, bundle_rows, tuple_rows, run_id, column_names=col_names
        )
        assert tuple_counts == counts


def test_verify_family_rows_rejects_missing_identities() -> None:
    bundle = _seven_family_bundle()
    run_id = 10

    # Test has_last_seen=True family
    nodes = bundle.families["canonical_nodes"]
    assert len(nodes) >= 2
    partial_db_nodes = _make_db_rows_from_bundle("canonical_nodes", nodes[:1], run_id)
    with pytest.raises(MissingIdentityError) as exc_info:
        verify_family_rows("canonical_nodes", nodes, partial_db_nodes, run_id)
    assert issubclass(MissingIdentityError, DurableFamilyVerificationError)
    assert "missing identities" in str(exc_info.value)

    # Test has_last_seen=False family
    raws = bundle.families["raw_observations"]
    with pytest.raises(MissingIdentityError):
        verify_family_rows("raw_observations", raws, [], run_id)


def test_verify_family_rows_rejects_extra_identities() -> None:
    bundle = _seven_family_bundle()
    run_id = 10

    # has_last_seen=True: extra row with current last_seen_run_id raises ExtraIdentityError
    files = bundle.families["files"]
    db_files = _make_db_rows_from_bundle("files", files, run_id)
    extra_file = dict(db_files[0], path="extra/untracked.py")
    with pytest.raises(ExtraIdentityError) as exc_info:
        verify_family_rows("files", files, [*db_files, extra_file], run_id)
    assert "extra identities" in str(exc_info.value)

    # But an extra row with an older last_seen_run_id should be ignored
    older_file = dict(db_files[0], path="older/prev_run.py", last_seen_run_id=run_id - 1)
    counts = verify_family_rows("files", files, [*db_files, older_file], run_id)
    assert counts.persisted_rows == len(files)

    # has_last_seen=False: extra row in run raises ExtraIdentityError
    raws = bundle.families["raw_observations"]
    db_raws = _make_db_rows_from_bundle("raw_observations", raws, run_id)
    extra_raw = dict(db_raws[0], ordinal=999)
    with pytest.raises(ExtraIdentityError):
        verify_family_rows("raw_observations", raws, [*db_raws, extra_raw], run_id)


def test_verify_family_rows_rejects_duplicate_identities() -> None:
    bundle = _seven_family_bundle()
    run_id = 10

    # has_last_seen=True: duplicate identity in persisted rows
    nodes = bundle.families["canonical_nodes"]
    db_nodes = _make_db_rows_from_bundle("canonical_nodes", nodes, run_id)
    dup_db_nodes = [*db_nodes, dict(db_nodes[0])]
    with pytest.raises(DuplicateIdentityError) as exc_info:
        verify_family_rows("canonical_nodes", nodes, dup_db_nodes, run_id)
    assert "duplicate identities" in str(exc_info.value)

    # has_last_seen=False: duplicate identity in persisted rows
    raws = bundle.families["raw_observations"]
    db_raws = _make_db_rows_from_bundle("raw_observations", raws, run_id)
    dup_db_raws = [*db_raws, dict(db_raws[0])]
    with pytest.raises(DuplicateIdentityError):
        verify_family_rows("raw_observations", raws, dup_db_raws, run_id)


def test_verify_family_rows_rejects_conflicting_payload_representative() -> None:
    bundle = _seven_family_bundle()
    run_id = 10

    # Files nonidentity payload conflict
    files = bundle.families["files"]
    db_files = _make_db_rows_from_bundle("files", files, run_id)
    db_files[0]["content_hash"] = "conflict:sha256:" + "0" * 64
    with pytest.raises(ConflictingPayloadError) as exc_info:
        verify_family_rows("files", files, db_files, run_id)
    assert "conflicting payload representative" in str(exc_info.value)

    # JSON normalization test: string JSON vs loaded dict matches
    nodes = bundle.families["canonical_nodes"]
    db_nodes = _make_db_rows_from_bundle("canonical_nodes", nodes, run_id)
    db_nodes[0]["metadata_json"] = '{"custom": "value", "parsed": true}'
    bundle_node = dict(nodes[0], metadata_json={"custom": "value", "parsed": True})
    counts = verify_family_rows("canonical_nodes", [bundle_node], [db_nodes[0]], run_id)
    assert counts.persisted_rows == 1

    # Conflict in parsed JSON
    db_nodes[0]["metadata_json"] = '{"custom": "other"}'
    with pytest.raises(ConflictingPayloadError):
        verify_family_rows("canonical_nodes", [bundle_node], [db_nodes[0]], run_id)


def test_verify_family_rows_collapsible_bundle_rows() -> None:
    bundle = _seven_family_bundle()
    run_id = 10

    # Identical duplicates in bundle collapse cleanly
    nodes = bundle.families["canonical_nodes"]
    collapsible_input = [nodes[0], dict(nodes[0])]
    db_nodes = _make_db_rows_from_bundle("canonical_nodes", [nodes[0]], run_id)
    counts = verify_family_rows("canonical_nodes", collapsible_input, db_nodes, run_id)
    assert counts.input_rows == 2
    assert counts.expected_distinct == 1
    assert counts.persisted_rows == 1
    assert counts.persisted_distinct == 1

    # Conflicting duplicates in bundle for IDENTICAL_ONLY raise ConflictingPayloadError
    conflicting_input = [nodes[0], dict(nodes[0], display_name="divergent_name")]
    with pytest.raises(ConflictingPayloadError) as exc_info:
        verify_family_rows("canonical_nodes", conflicting_input, db_nodes, run_id)
    assert "collapsible rows conflict" in str(exc_info.value)


@pytest.mark.parametrize(("family", "column", "different"), (
    ("files", "content_hash", "b" * 64),
    ("canonical_nodes", "display_name", "different-name"),
    ("canonical_edges", "confidence", "unknown"),
    ("canonical_evidence", "path", "different/path.py"),
))
def test_identical_only_families_reject_input_and_persisted_payload_drift(
    family: StageFamily, column: str, different: str,
) -> None:
    row = _seven_family_bundle().families[family][0]
    assert row[column] != different
    persisted = _make_db_rows_from_bundle(family, [row], 10)
    counts = verify_family_rows(family, [row, dict(row)], persisted, 10)
    assert (counts.input_rows, counts.expected_distinct, counts.persisted_rows) == (2, 1, 1)
    with pytest.raises(ConflictingPayloadError):
        verify_family_rows(family, [row, {**row, column: different}], persisted, 10)
    with pytest.raises(ConflictingPayloadError):
        verify_family_rows(family, [row], [{**persisted[0], column: different}], 10)


def test_text_payload_is_not_normalized_as_json() -> None:
    row = dict(_seven_family_bundle().families["canonical_nodes"][0], display_name='[1, 2]')
    persisted = _make_db_rows_from_bundle("canonical_nodes", [row], 10)
    persisted[0]["display_name"] = '[1,2]'
    with pytest.raises(ConflictingPayloadError):
        verify_family_rows("canonical_nodes", [row], persisted, 10)


def test_verify_family_rows_rejects_stale_last_seen() -> None:
    bundle = _seven_family_bundle()
    run_id = 10

    # has_last_seen=True: DB row with stale last_seen_run_id raises StaleLastSeenError
    files = bundle.families["files"]
    db_files = _make_db_rows_from_bundle("files", files, run_id - 1)
    with pytest.raises(StaleLastSeenError) as exc_info:
        verify_family_rows("files", files, db_files, run_id)
    assert issubclass(StaleLastSeenError, DurableFamilyVerificationError)
    assert "stale last_seen" in str(exc_info.value)

    # has_last_seen=False: DB row with stale run_id raises StaleLastSeenError
    evs = bundle.families["canonical_evidence"]
    db_evs = _make_db_rows_from_bundle("canonical_evidence", evs, run_id - 1)
    with pytest.raises(StaleLastSeenError):
        verify_family_rows("canonical_evidence", evs, db_evs, run_id)


def test_assert_durable_families_mock_connection() -> None:
    bundle = _seven_family_bundle()
    run_id = 10
    repo_id = 101

    class MockCursor:
        def __init__(self, family: StageFamily, rows: list[dict[str, object]]) -> None:
            self._spec = _SPECS[family]
            self._rows = [tuple(r.get(c) for c in self._spec.query_columns) for r in rows]
            self.description = [MagicMock(name=c) for c in self._spec.query_columns]
            for i, c in enumerate(self._spec.query_columns):
                self.description[i].name = c

        def fetchall(self) -> list[tuple[object, ...]]:
            return self._rows

    class MockConnection:
        def execute(self, query: str, params: tuple[Any, ...]) -> MockCursor:
            for family, spec in _SPECS.items():
                if query.startswith(f"SELECT {', '.join(spec.query_columns[:2])}"):
                    db_rows = _make_db_rows_from_bundle(family, bundle.families[family], run_id)
                    return MockCursor(family, db_rows)
            for family in ("canonical_node_evidence", "canonical_edge_evidence"):
                if f"FROM {family}" in query:
                    db_rows = _make_db_rows_from_bundle(family, bundle.families[family], run_id)
                    return MockCursor(family, db_rows)
            raise AssertionError(f"Unhandled query: {query}")

    mock_conn = MockConnection()
    result = assert_durable_families(mock_conn, bundle, repo_id, run_id)
    assert set(result.keys()) == set(PUBLICATION_FAMILIES)
    for family, counts in result.items():
        assert counts.input_rows == len(bundle.families[family])
        assert counts.persisted_rows == len(bundle.families[family])


@pytest.mark.parametrize(("conflict_col", "conflict_val"), (
    ("path", "different/path.py"),
    ("payload_json", '{"divergent": true}'),
    ("payload_hash", "f" * 64),
))
def test_raw_observations_collapsible_duplicates_and_conflict(conflict_col: str, conflict_val: Any) -> None:
    raws = _seven_family_bundle().families["raw_observations"]
    base_row = raws[0]
    identical_dup = dict(base_row)
    db_rows = _make_db_rows_from_bundle("raw_observations", [base_row], 10)

    # Identical duplicates in raw_observations collapse cleanly
    counts = verify_family_rows("raw_observations", [base_row, identical_dup], db_rows, 10)
    assert counts.input_rows == 2
    assert counts.expected_distinct == 1
    assert counts.persisted_rows == 1

    # Conflicting duplicate at same source_ordinal fails closed
    conflicting_row = dict(base_row, **{conflict_col: conflict_val})
    with pytest.raises(ConflictingPayloadError) as exc_info:
        verify_family_rows("raw_observations", [base_row, conflicting_row], db_rows, 10)
    assert "input collapsible rows conflict" in str(exc_info.value)


def test_set_deduplicated_families_unaffected_by_duplicate_collapse() -> None:
    bundle = _seven_family_bundle()
    for fam in ("canonical_node_evidence", "canonical_edge_evidence"):
        rows = bundle.families[fam]
        dup_rows = [rows[0], dict(rows[0])]
        db_rows = _make_db_rows_from_bundle(fam, [rows[0]], 10)
        counts = verify_family_rows(fam, dup_rows, db_rows, 10)
        assert counts.input_rows == 2
        assert counts.expected_distinct == 1
        assert counts.persisted_rows == 1


def test_junction_queries_parameter_contract() -> None:
    for fam in ("canonical_node_evidence", "canonical_edge_evidence"):
        spec = _SPECS[fam]
        assert spec.query.count("%s") == 2
        assert "t.repository_id = e.repository_id" in spec.query
        assert "e.repository_id = %s" in spec.query
        assert "e.run_id = %s" in spec.query


def test_junction_queries_repository_scoping_sqlite() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE canonical_nodes (id INT, repository_id INT, graph_key_version INT, canonical_key TEXT);
        CREATE TABLE canonical_edges (id INT, repository_id INT, graph_key_version INT, source_canonical_key TEXT, edge_kind TEXT, target_canonical_key TEXT, identity_metadata_hash TEXT);
        CREATE TABLE canonical_evidence (id INT, repository_id INT, run_id INT, evidence_key TEXT);
        CREATE TABLE canonical_node_evidence (canonical_node_id INT, canonical_evidence_id INT, link_kind TEXT);
        CREATE TABLE canonical_edge_evidence (canonical_edge_id INT, canonical_evidence_id INT, link_kind TEXT);
        INSERT INTO canonical_nodes VALUES (1, 1, 1, 'n1'), (2, 2, 1, 'n2');
        INSERT INTO canonical_edges VALUES (1, 1, 1, 'n1', 'defines', 'n2', 'h1'), (2, 2, 1, 'n1', 'defines', 'n2', 'h2');
        INSERT INTO canonical_evidence VALUES (10, 1, 100, 'ev1');
        INSERT INTO canonical_node_evidence VALUES (1, 10, 'syntax'), (2, 10, 'cross');
        INSERT INTO canonical_edge_evidence VALUES (1, 10, 'syntax'), (2, 10, 'cross');
    """)
    q_node = _SPECS["canonical_node_evidence"].query.replace("%s", "?")
    rows_node = conn.execute(q_node, (1, 100)).fetchall()
    assert rows_node == [(1, "n1", "ev1", "syntax")]

    q_edge = _SPECS["canonical_edge_evidence"].query.replace("%s", "?")
    rows_edge = conn.execute(q_edge, (1, 100)).fetchall()
    assert rows_edge == [(1, "n1", "defines", "n2", "h1", "ev1", "syntax")]
