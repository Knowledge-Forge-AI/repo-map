from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
import hashlib
import json

import pytest

from repomap_kg.storage import (
    external_row_sort,
    structural_digest as digest_module,
    structural_digest_encoding,
)
from repomap_kg.storage.staged_rows import PreparedStageRows
from repomap_kg.storage.structural_digest import (
    STRUCTURAL_DIGEST_FAMILY_CODES,
    STRUCTURAL_DIGEST_FIELDS,
    StructuralDigestError,
    StructuralDigestFamily,
    digest_prepared_stage_rows,
    structural_digest,
)

type _JsonScalar = str | int | float | bool | None
type _JsonValue = _JsonScalar | list[_JsonValue] | dict[str, _JsonValue]
type _DigestRow = tuple[_JsonValue, ...]
type _StructuralDigestRow = Sequence[object]


def _rows(**overrides):
    rows = {
        "files": [("a.py", "python", "source", "a" * 64, False, False, {"empty": "", "nested": [None, True, 7]})],
        "raw_observations": [(0, 1, "file", "a.py", "a.py", {"name": "café", "value": False}, "b" * 64)],
        "canonical_nodes": [(1, "file:a.py", "file", "a.py", {}, "extracted", False)],
        "canonical_edges": [], "canonical_evidence": [], "canonical_node_evidence": [], "canonical_edge_evidence": [],
    }
    rows.update(overrides)
    return rows


def _reference(rows) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _families(rows) -> tuple[StructuralDigestFamily, ...]:
    return tuple(
        StructuralDigestFamily(family, rows[family])
        for family in STRUCTURAL_DIGEST_FAMILY_CODES
    )


def test_streaming_digest_equals_the_current_whole_graph_reference() -> None:
    rows = _rows()
    assert structural_digest(_families(rows)) == _reference(rows)


def test_empty_graph_retains_the_exact_seven_family_digest() -> None:
    rows: dict[str, Sequence[_StructuralDigestRow]] = {
        family: [] for family in STRUCTURAL_DIGEST_FAMILY_CODES
    }
    assert structural_digest(_families(rows)) == _reference(rows)


@pytest.mark.parametrize(
    "left,right",
    (
        (["ab", "c"], ["a", "bc"]),
        ([None, ""], ["", None]),
        ([1, True], [True, 1]),
        ([{"a": 1}, {"b": 2}], [{"a": 1, "b": 2}]),
    ),
)
def test_row_framing_is_collision_safe(
    left: list[_JsonValue], right: list[_JsonValue]
) -> None:
    base = list(_rows()["files"][0])
    base[-1] = {"values": left}
    left_rows = _rows(files=[tuple(base)])
    base[-1] = {"values": right}
    right_rows = _rows(files=[tuple(base)])

    assert structural_digest(_families(left_rows)) != structural_digest(
        _families(right_rows)
    )


def test_family_framing_is_collision_safe() -> None:
    edge: _DigestRow = (1, "source", "kind", "target", {}, "a" * 64, {}, "extracted", False)
    evidence: _DigestRow = (1, "evidence", 0, 1, "file", "source", "path", None, None, "extractor", "1", "extracted", {})
    first = _rows(canonical_edges=[edge], canonical_evidence=[])
    second = _rows(canonical_edges=[], canonical_evidence=[evidence])

    assert structural_digest(_families(first)) != structural_digest(
        _families(second)
    )


def test_duplicate_rows_are_retained_in_order() -> None:
    row = _rows()["canonical_nodes"][0]
    once = _rows(canonical_nodes=[row])
    twice = _rows(canonical_nodes=[row, row])

    assert structural_digest(_families(once)) == _reference(once)
    assert structural_digest(_families(twice)) == _reference(twice)
    assert structural_digest(_families(once)) != structural_digest(
        _families(twice)
    )


def test_family_and_row_iterators_are_consumed_once_without_length_requests() -> None:
    events: list[str] = []
    rows = _rows()

    class OnePassFamilies:
        def __iter__(self):
            for family in STRUCTURAL_DIGEST_FAMILY_CODES:
                events.append(f"family:{family}")

                def one_family(family=family):
                    for row in rows[family]:
                        events.append(f"row:{family}")
                        yield row

                yield StructuralDigestFamily(family, one_family())

        def __len__(self):
            raise AssertionError("family collection length was requested")

    assert structural_digest(OnePassFamilies()) == _reference(rows)
    assert events[0] == f"family:{STRUCTURAL_DIGEST_FAMILY_CODES[0]}"
    assert events[-1].startswith("family:") or events[-1].startswith("row:")


def test_cancellation_propagates_without_returning_a_partial_digest() -> None:
    checks = 0

    def cancel() -> None:
        nonlocal checks
        checks += 1
        if checks == 5:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        structural_digest(_families(_rows()), cancellation_check=cancel)


def test_shared_encoder_propagates_value_error_cancellation() -> None:
    class _Cancelled(ValueError):
        pass

    def cancel() -> None:
        raise _Cancelled("stop")

    with pytest.raises(_Cancelled, match="stop"):
        list(
            structural_digest_encoding.iter_canonical_json_chunks(
                {"value": 1},
                cancel,
            )
        )


def test_cancellation_at_final_completion_returns_no_digest_and_retries() -> None:
    rows = _rows()
    successful_checks = 0

    def count_checks() -> None:
        nonlocal successful_checks
        successful_checks += 1

    expected = structural_digest(
        _families(rows),
        cancellation_check=count_checks,
    )
    failing_checks = 0

    def cancel_at_completion() -> None:
        nonlocal failing_checks
        failing_checks += 1
        if failing_checks == successful_checks:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        structural_digest(
            _families(rows),
            cancellation_check=cancel_at_completion,
        )

    assert structural_digest(_families(rows)) == expected


def test_encoder_updates_are_bounded_for_one_large_row_value() -> None:
    row = list(_rows()["files"][0])
    row[-1] = {"payload": "x" * 200_000}
    rows = _rows(files=[tuple(row)])
    chunks: list[int] = []

    assert structural_digest(
        _families(rows),
        chunk_observer=chunks.append,
    ) == _reference(rows)
    assert max(chunks) <= 16_384


@pytest.mark.parametrize(
    "families,message",
    (
        ((), "missing"),
        (
            (
                StructuralDigestFamily("legacy_graph", ()),
                *tuple(
                    StructuralDigestFamily(family, ())
                    for family in STRUCTURAL_DIGEST_FAMILY_CODES[1:]
                ),
            ),
            "family order",
        ),
        (
            tuple(
                StructuralDigestFamily(family, ())
                for family in STRUCTURAL_DIGEST_FAMILY_CODES
            )
            + (StructuralDigestFamily("files", ()),),
            "unexpected",
        ),
    ),
)
def test_invalid_family_streams_fail_closed(families, message) -> None:
    with pytest.raises(StructuralDigestError, match=message):
        structural_digest(families)


def test_invalid_row_shape_and_value_fail_with_bounded_errors() -> None:
    rows = _rows(files=[{"not": "a sequence"}])
    with pytest.raises(StructuralDigestError, match="row is invalid"):
        structural_digest(_families(rows))

    row = list(_rows()["files"][0])
    row[-1] = object()
    rows = _rows(files=[tuple(row)])
    with pytest.raises(StructuralDigestError, match="value is invalid") as error:
        structural_digest(_families(rows))
    assert "object at" not in str(error.value)


def test_prepared_stage_adapter_projects_exact_terminal_fields() -> None:
    prepared_rows: dict[str, tuple[dict[str, object], ...]] = {family: () for family in STRUCTURAL_DIGEST_FAMILY_CODES}
    prepared_rows["files"] = ({
        "stage_id": "private-stage", "family_ordinal": 0, "path": "a.py", "language": "python",
        "role": "source", "confidence": "extracted", "content_hash": "a" * 64,
        "executable": False, "generated": False, "metadata_json": {},
    },)
    prepared = PreparedStageRows(
        family_rows=prepared_rows, checksums={},
        row_counts={f: len(prepared_rows[f]) for f in prepared_rows},
        normalized_byte_counts={f: 0 for f in prepared_rows},
        privacy_classifications={}, files=1,
    )
    semantic: dict[str, list[_DigestRow]] = {family: [] for family in STRUCTURAL_DIGEST_FAMILY_CODES}
    semantic["files"] = [("a.py", "python", "source", "a" * 64, False, False, {})]

    assert STRUCTURAL_DIGEST_FIELDS["files"] == (
        "path", "language", "role", "content_hash", "executable", "generated", "metadata_json",
    )
    assert digest_prepared_stage_rows(prepared) == _reference(semantic)


def test_prepared_stage_adapter_orders_rows_by_terminal_query_keys() -> None:
    prepared_rows: dict[str, tuple[dict[str, object], ...]] = {family: () for family in STRUCTURAL_DIGEST_FAMILY_CODES}
    prepared_rows["canonical_nodes"] = (
        {"graph_key_version": 1, "canonical_key": "node:z", "kind": "file", "display_name": "z", "metadata_json": {}, "confidence": "extracted", "conflict": False},
        {"graph_key_version": 1, "canonical_key": "node:a", "kind": "file", "display_name": "a", "metadata_json": {}, "confidence": "extracted", "conflict": False},
    )
    prepared = PreparedStageRows(
        family_rows=prepared_rows, checksums={},
        row_counts={f: len(prepared_rows[f]) for f in prepared_rows},
        normalized_byte_counts={f: 0 for f in prepared_rows},
        privacy_classifications={}, files=0,
    )
    semantic: dict[str, list[_DigestRow]] = {family: [] for family in STRUCTURAL_DIGEST_FAMILY_CODES}
    semantic["canonical_nodes"] = [
        (1, "node:a", "file", "a", {}, "extracted", False),
        (1, "node:z", "file", "z", {}, "extracted", False),
    ]
    assert digest_prepared_stage_rows(prepared) == _reference(semantic)


def test_prepared_adapter_reuses_the_canonical_sorted_row_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared_rows: dict[str, tuple[dict[str, object], ...]] = {family: () for family in STRUCTURAL_DIGEST_FAMILY_CODES}
    prepared_rows["files"] = ({
        "path": "a.py", "language": "python", "role": "source", "content_hash": "a" * 64,
        "executable": False, "generated": False, "metadata_json": {"z": 1, "a": "café"},
    },)
    prepared = PreparedStageRows(
        family_rows=prepared_rows, checksums={},
        row_counts={f: len(prepared_rows[f]) for f in prepared_rows},
        normalized_byte_counts={f: 0 for f in prepared_rows},
        privacy_classifications={}, files=1,
    )
    semantic: dict[str, list[_DigestRow]] = {family: [] for family in STRUCTURAL_DIGEST_FAMILY_CODES}
    semantic["files"] = [("a.py", "python", "source", "a" * 64, False, False, {"z": 1, "a": "café"})]
    encoded_values: list[object] = []

    class _EncoderSpy:
        def __init__(self, delegate: json.JSONEncoder, values: list[object]) -> None:
            self._delegate = delegate
            self._values = values

        def iterencode(self, value: object) -> Iterator[str]:
            self._values.append(value)
            return self._delegate.iterencode(value)

    monkeypatch.setattr(
        structural_digest_encoding,
        "CANONICAL_JSON_ENCODER",
        _EncoderSpy(structural_digest_encoding.CANONICAL_JSON_ENCODER, encoded_values),
    )

    assert digest_prepared_stage_rows(prepared) == _reference(semantic)
    assert len([value for value in encoded_values if isinstance(value, tuple)]) == 1
    encoded_values.clear()
    assert structural_digest(_families(semantic)) == _reference(semantic)
    assert any(isinstance(value, (tuple, list)) for value in encoded_values)
    assert not hasattr(external_row_sort, "_ENCODER")
    assert not hasattr(digest_module, "_ENCODER")


def test_prepared_encoded_row_cancellation_returns_no_digest_and_retries() -> None:
    prepared_rows: dict[str, tuple[dict[str, object], ...]] = {family: () for family in STRUCTURAL_DIGEST_FAMILY_CODES}
    prepared_rows["files"] = ({
        "path": "a.py", "language": "python", "role": "source", "content_hash": "a" * 64,
        "executable": False, "generated": False, "metadata_json": {"payload": "x" * 200_000},
    },)
    prepared = PreparedStageRows(
        family_rows=prepared_rows, checksums={},
        row_counts={f: len(prepared_rows[f]) for f in prepared_rows},
        normalized_byte_counts={f: 0 for f in prepared_rows},
        privacy_classifications={}, files=1,
    )
    checks = 0

    def cancel() -> None:
        nonlocal checks
        checks += 1
        if checks == 12:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        digest_prepared_stage_rows(prepared, cancellation_check=cancel)

    assert digest_prepared_stage_rows(prepared) == digest_prepared_stage_rows(prepared)


def test_prepared_stage_adapter_closes_an_active_row_iterator_on_failure() -> None:
    closed = False

    def failing_rows() -> Iterator[dict[str, object]]:
        nonlocal closed
        try:
            yield {
                "path": "a.py", "language": "python", "role": "source", "content_hash": "a" * 64,
                "executable": False, "generated": False, "metadata_json": {},
            }
            raise RuntimeError("private diagnostic")
        finally:
            closed = True

    rows: dict[str, Iterable[dict[str, object]]] = {family: () for family in STRUCTURAL_DIGEST_FAMILY_CODES}
    rows["files"] = failing_rows()
    prepared = PreparedStageRows(
        family_rows=rows, checksums={},
        row_counts={family: 0 for family in rows},
        normalized_byte_counts={family: 0 for family in rows},
        privacy_classifications={}, files=0,
    )

    with pytest.raises(RuntimeError, match="private diagnostic"):
        digest_prepared_stage_rows(prepared)
    assert closed is True
