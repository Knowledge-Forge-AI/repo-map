"""Cooperative cancellation stops ingestion and retains exact bundle semantics."""
from __future__ import annotations

import builtins
from collections.abc import Iterator
from pathlib import Path
import threading
from typing import IO

import pytest

from common_lore_index.artifacts import _bundle_stream_sort as sorter_module
from common_lore_index.artifacts._bundle_stream_encode import StreamingBundleEncoder
from common_lore_index.artifacts._bundle_stream_sort import BoundedExternalRowSorter
from common_lore_index.artifacts._bundle_cancellation import BundleEncodingCancelled, closing_bundle_resource
from common_lore_index.artifacts._canonical import canonical_json
from repomap_test_support.portable_publication_fixtures import _bundle


@pytest.mark.parametrize("buffer_bytes", [1, 4096])
@pytest.mark.parametrize("cancel_at", [0, 1, 7])
def test_sorter_stops_before_requesting_more_rows_and_reclaims_spills(
    tmp_path: Path, buffer_bytes: int, cancel_at: int,
) -> None:
    event = threading.Event()
    seen: list[int] = []
    sentinel = tmp_path / "unrelated"
    sentinel.write_bytes(b"preserved")

    def rows() -> Iterator[dict[str, object]]:
        for number in range(100):
            seen.append(number)
            if number == cancel_at:
                event.set()
            yield {"value": number}

    with BoundedExternalRowSorter(
        spool_dir=tmp_path, max_buffer_bytes=buffer_bytes, cancel_event=event,
    ) as sorter:
        with pytest.raises(BundleEncodingCancelled, match="^cancelled$"):
            tuple(sorter.sort_family_records("files", rows()))
        assert seen == list(range(cancel_at + 1))
    assert tuple(tmp_path.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"


def test_pre_cancel_does_not_start_input_iteration(tmp_path: Path) -> None:
    event = threading.Event()
    event.set()

    class Rows:
        def __iter__(self) -> Iterator[dict[str, object]]:
            raise AssertionError("input must remain untouched")

    with BoundedExternalRowSorter(spool_dir=tmp_path, cancel_event=event) as sorter:
        with pytest.raises(BundleEncodingCancelled):
            tuple(sorter.sort_family_records("files", Rows()))
    assert not tuple(tmp_path.iterdir())


def test_bad_input_keeps_its_original_error_even_when_cancellation_is_set(tmp_path: Path) -> None:
    event = threading.Event()
    marker = ValueError("cancelled")

    def rows() -> Iterator[dict[str, object]]:
        yield {"value": "valid"}
        event.set()
        raise marker

    with BoundedExternalRowSorter(spool_dir=tmp_path, cancel_event=event) as sorter:
        with pytest.raises(ValueError) as caught:
            tuple(sorter.sort_family_records("files", rows()))
    assert caught.value is marker
    assert not isinstance(caught.value, BundleEncodingCancelled)
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("buffer_bytes", [1, 4096])
def test_cancellation_during_output_reclaims_all_runs(tmp_path: Path, buffer_bytes: int) -> None:
    event = threading.Event()
    rows = ({"value": "é"}, {"value": ""}, {"value": "🐦"}, {"value": "é"})
    with BoundedExternalRowSorter(spool_dir=tmp_path, max_buffer_bytes=buffer_bytes, cancel_event=event) as sorter:
        stream = sorter.sort_family_records("files", rows)
        assert next(stream) == sorted(canonical_json({"family": "files", "frame": "record", "record": r}) for r in rows)[0]
        event.set()
        with pytest.raises(BundleEncodingCancelled):
            next(stream)
    assert not tuple(tmp_path.iterdir())


def test_partial_run_open_failure_closes_every_acquired_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[IO[bytes]] = []
    marker = OSError("synthetic second run-open refusal")

    def open_run(path: Path, mode: str) -> IO[bytes]:
        if len(opened) == 1:
            raise marker
        handle = builtins.open(path, mode)
        opened.append(handle)
        return handle

    monkeypatch.setattr(sorter_module, "open", open_run, raising=False)
    with BoundedExternalRowSorter(spool_dir=tmp_path, max_buffer_bytes=1) as sorter:
        with pytest.raises(OSError) as caught:
            tuple(sorter.sort_family_records("files", ({"value": n} for n in range(3))))
        assert caught.value is marker
        assert len(opened) == 1 and opened[0].closed
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("buffer_bytes", [None, 1, 4096])
def test_encoder_bytes_do_not_change_with_live_uncancelled_event(tmp_path: Path, buffer_bytes: int | None) -> None:
    bundle = _bundle()
    encoder = StreamingBundleEncoder(
        request_id=bundle.request_id, job_id=bundle.job_id, attempt=bundle.attempt,
        graph_id=bundle.graph_id, candidate_id=bundle.candidate_id,
        snapshot_manifest_id=bundle.snapshot_manifest_id, snapshot_vector=bundle.snapshot_vector,
        source_generation=bundle.source_generation, config_generation=bundle.config_generation,
        extractor_generation=bundle.extractor_generation, canonicalizer_generation=bundle.canonicalizer_generation,
        extractor_capability_identity=bundle.extractor_capability_identity, resolver_identity=bundle.resolver_identity,
        canonicalizer_identity=bundle.canonicalizer_identity, semantic_contract_identity=bundle.semantic_contract_identity,
        quality_rule_identity=bundle.quality_rule_identity, privacy=bundle.privacy,
        family_rows=bundle.families, row_stage_contract=bundle.row_stage_contract,
        spool_dir=tmp_path, cancel_event=threading.Event(), max_sorter_buffer_bytes=buffer_bytes,
    )
    assert b"".join(encoder.stream_chunks(chunk_size=1)) == bundle.canonical_bytes()
    assert encoder.descriptor().bundle_id == bundle.bundle_id
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("primary_failure", [False, True])
def test_bundle_resource_context_preserves_only_its_own_primary(primary_failure: bool) -> None:
    primary = BundleEncodingCancelled()
    secondary = OSError("synthetic iterator close refusal")
    closes = 0

    class Resource:
        def close(self) -> None:
            nonlocal closes
            closes += 1
            raise secondary

    try:
        raise ValueError("previously handled caller error")
    except ValueError:
        expected = BundleEncodingCancelled if primary_failure else OSError
        with pytest.raises(expected) as caught:
            with closing_bundle_resource(Resource()):
                if primary_failure:
                    raise primary
        assert caught.value is (primary if primary_failure else secondary)
    assert closes == 1
