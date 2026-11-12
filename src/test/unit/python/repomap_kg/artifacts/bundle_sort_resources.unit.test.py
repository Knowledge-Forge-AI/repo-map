"""Admission and actual handle witnesses for canonical external sorting."""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
import threading

import pytest

from common_lore_index.artifacts import _bundle_stream_encode as encoder_module
from common_lore_index.artifacts import _bundle_stream_sort as sorter_module
from common_lore_index.artifacts import _bundle_sort_runs as runs_module
from common_lore_index.artifacts._bundle_cancellation import BundleEncodingCancelled
from common_lore_index.artifacts._bundle_stream_sort import BoundedExternalRowSorter
from common_lore_index.artifacts._canonical import CanonicalEncodingError, canonical_json
from common_lore_index.storage.staging_family_rows import StageFamily
from repomap_test_support.bundle_sort_fixtures import (
    SortIOWitness, encoder_for_bundle, encoder_for_rows, observe_sort_directory_cleanup,
)
from repomap_test_support.portable_publication_fixtures import _seven_family_bundle


@pytest.mark.parametrize("limit", ["records", "bytes"])
def test_encoder_stops_at_one_proving_overflow_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str,
) -> None:
    consumed: list[int] = []
    closed: list[bool] = []
    remaining = observe_sort_directory_cleanup(monkeypatch)

    def rows() -> Iterator[dict[str, object]]:
        try:
            for number in range(100):
                consumed.append(number)
                yield {"value": f"{number:03d}"}
        finally:
            closed.append(True)

    encoder = encoder_for_rows(tmp_path, rows(), max_sorter_buffer_bytes=1)
    if limit == "records":
        monkeypatch.setattr(encoder_module, "MAX_BUNDLE_RECORDS", 2)
    else:
        line = canonical_json({"family": "files", "frame": "record", "record": {"value": "000"}})
        encoder.max_bundle_bytes = len(canonical_json(encoder._header_mapping())) + 2 * len(line)
    message = f"publication bundle {'record' if limit == 'records' else 'byte'} bounds exceeded"
    with pytest.raises(ValueError, match=message):
        b"".join(encoder.stream_chunks())
    assert consumed == [0, 1, 2]
    assert closed == [True]
    assert remaining and not any(remaining)
    assert not tuple(tmp_path.iterdir())


def test_merge_fan_in_bounds_actual_simultaneous_input_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    witness = SortIOWitness()
    monkeypatch.setattr(sorter_module, "_MAX_MERGE_FAN_IN", 4, raising=False)
    monkeypatch.setattr(sorter_module, "open", witness.open_run, raising=False)
    monkeypatch.setattr(runs_module.tempfile, "NamedTemporaryFile", witness.temporary)
    rows = [{"value": f"{number:03d}"} for number in reversed(range(67))]
    with BoundedExternalRowSorter(max_buffer_bytes=1, spool_dir=tmp_path) as sorter:
        actual = tuple(sorter.sort_family_records("files", rows))
        assert sorter.spill_run_count == len(rows)
        assert sorter.spill_bytes == sum(map(len, actual))
    assert actual == tuple(sorted(canonical_json({"family": "files", "frame": "record", "record": row}) for row in rows))
    assert witness.inputs and witness.outputs and witness.all_closed
    assert witness.peak_inputs <= 4
    assert witness.peak_handles <= 5
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("buffer_bytes", [1, 192, 65536])
def test_multilevel_sort_preserves_duplicate_unicode_and_integer_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, buffer_bytes: int,
) -> None:
    monkeypatch.setattr(sorter_module, "_MAX_MERGE_FAN_IN", 3, raising=False)
    rows = [{"value": value} for value in ["é", "🐦", -1, 0, "a", "é"] * 9]
    rows.reverse()
    sentinel = tmp_path / "unrelated"
    sentinel.write_bytes(b"preserved")
    with BoundedExternalRowSorter(max_buffer_bytes=buffer_bytes, spool_dir=tmp_path) as sorter:
        actual = tuple(sorter.sort_family_records("files", rows))
    assert actual == tuple(sorted(canonical_json({"family": "files", "frame": "record", "record": row}) for row in rows))
    assert tuple(tmp_path.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"


@pytest.mark.parametrize("value", [-0.0, float("nan"), float("inf")])
def test_float_refusal_keeps_canonical_domain_and_reclaims_prior_spills(tmp_path: Path, value: float) -> None:
    with BoundedExternalRowSorter(max_buffer_bytes=1, spool_dir=tmp_path) as sorter:
        with pytest.raises(CanonicalEncodingError, match="floats are outside the canonical domain"):
            tuple(sorter.sort_family_records("files", [{"value": "valid"}, {"value": value}]))
        assert sorter._temp_dir is not None
        assert not tuple(Path(sorter._temp_dir.name).iterdir())
    assert not tuple(tmp_path.iterdir())


def test_all_family_descriptor_bytes_match_nonstreaming_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sorter_module, "_MAX_MERGE_FAN_IN", 2, raising=False)
    bundle = _seven_family_bundle()
    encoder = encoder_for_bundle(tmp_path, bundle, max_sorter_buffer_bytes=1)
    raw = b"".join(encoder.stream_chunks(chunk_size=7))
    descriptor = encoder.descriptor()
    assert raw == bundle.canonical_bytes()
    assert descriptor.bundle_id == bundle.bundle_id
    assert descriptor.family_summaries == bundle.family_summaries
    assert descriptor.total_bytes == len(raw)
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("offset", [-1, 0])
def test_admission_equality_is_distinct_from_trailer_overflow(tmp_path: Path, offset: int) -> None:
    values: list[dict[str, object]] = [{"value": f"{n:03d}"} for n in range(3)]
    consumed: list[int] = []
    exhausted = False

    def rows() -> Iterator[dict[str, object]]:
        nonlocal exhausted
        for index, row in enumerate(values):
            consumed.append(index)
            yield row
        exhausted = True

    encoder = encoder_for_rows(tmp_path, rows(), max_sorter_buffer_bytes=1)
    header = len(canonical_json(encoder._header_mapping()))
    family = sum(len(canonical_json({"family": "files", "frame": "record", "record": row})) for row in values)
    encoder.max_bundle_bytes = header + family + offset
    with pytest.raises(ValueError, match="publication bundle byte bounds exceeded"):
        b"".join(encoder.stream_chunks())
    assert consumed == [0, 1, 2]
    assert exhausted is (offset == 0)
    with pytest.raises(ValueError, match="streaming encoding has not completed"):
        encoder.descriptor()
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("offset", [-1, 0])
def test_later_family_byte_admission_includes_header_and_prior_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offset: int,
) -> None:
    bundle = _seven_family_bundle()
    families: dict[StageFamily, tuple[dict[str, object], ...]] = {family: () for family in bundle.families}
    families["files"] = bundle.families["files"][:1]
    later = bundle.families["raw_observations"][:2]
    exhausted = False
    remaining = observe_sort_directory_cleanup(monkeypatch)

    def rows() -> Iterator[dict[str, object]]:
        nonlocal exhausted
        yield from later
        exhausted = True

    selected: dict[StageFamily, Iterable[dict[str, object]]] = {family: values for family, values in families.items()}
    selected["raw_observations"] = rows()
    encoder = encoder_for_bundle(tmp_path, bundle, family_rows=selected, max_sorter_buffer_bytes=1)
    header = len(canonical_json(encoder._header_mapping()))
    prior_bytes = sum(len(canonical_json({"family": "files", "frame": "record", "record": row})) for row in families["files"])
    later_bytes = sum(len(canonical_json({"family": "raw_observations", "frame": "record", "record": row})) for row in later)
    assert families["files"] and len(later) == 2 and prior_bytes > 0
    encoder.max_bundle_bytes = header + prior_bytes + later_bytes + offset
    with pytest.raises(ValueError, match="publication bundle byte bounds exceeded"):
        b"".join(encoder.stream_chunks())
    assert exhausted is (offset == 0)
    assert remaining and not any(remaining)
    assert not tuple(tmp_path.iterdir())


def test_cancellation_on_overflow_row_precedes_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = threading.Event()

    def rows() -> Iterator[dict[str, object]]:
        yield {"value": "first"}
        event.set()
        yield {"value": "overflow"}

    monkeypatch.setattr(encoder_module, "MAX_BUNDLE_RECORDS", 1)
    encoder = encoder_for_rows(tmp_path, rows(), max_sorter_buffer_bytes=1, cancel_event=event)
    with pytest.raises(BundleEncodingCancelled):
        b"".join(encoder.stream_chunks())
    assert not tuple(tmp_path.iterdir())
