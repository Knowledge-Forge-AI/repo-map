"""Real sealed worker spools stay inside their attempt across success and failure."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
import tempfile
import threading

import pytest

from common_lore_index.artifacts._bundle_stream_encode import StreamingBundleEncoder
from common_lore_index.artifacts import _bundle_stream_encode as encoder_module
from common_lore_index.artifacts import _bundle_stream_sort as sorter_module
from common_lore_index.artifacts import _bundle_sort_runs as runs_module
from common_lore_index.artifacts.validator import PublisherBundleValidator
from common_lore_index.coordinator import _portable_semantic_adapter as adapter
from common_lore_index.graph.multi_source_pipeline import capture_multi_source_candidate
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage import staged_rows as preparation_module
from common_lore_index.storage.row_spool import RowSpool
from repomap_test_support.portable_spool_case import spool_case as _setup
from repomap_test_support.portable_worker_equivalence import reference_bytes, publication_expectation
from repomap_test_support.bundle_sort_fixtures import SortIOWitness, observe_sort_directory_cleanup


@pytest.mark.parametrize("limit", ["bytes", "records"])
def test_preparation_admits_before_writing_beyond_existing_bundle_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str,
) -> None:
    _, store, _, _, capability, sentinel = _setup(tmp_path, functions=4201)
    byte_limit = 8192 if limit == "bytes" else capability.max_bundle_bytes
    capability = replace(capability, max_bundle_bytes=byte_limit)
    if limit == "records":
        monkeypatch.setattr(encoder_module, "MAX_BUNDLE_RECORDS", 2)
    before = {path.name: path.read_bytes() for path in store._objects.iterdir()}
    admitted: list[int] = []
    written: list[int] = []
    original = RowSpool.from_rows

    def spool(cls, rows, **kwargs):
        observer = kwargs.get("artifact_observer")

        def observe(projected_bytes):
            if observer is not None:
                observer(projected_bytes)
            admitted.append(projected_bytes)
            written.extend(
                path.stat().st_size
                for path in capability.workspace_root.rglob("repomap-stage-rows-*.jsonl")
            )

        return original(rows, **dict(kwargs, artifact_observer=observe))

    monkeypatch.setattr(RowSpool, "from_rows", classmethod(spool))
    with pytest.raises(adapter.PortableExecutionError) as caught:
        adapter.execute_portable_extraction(
            capability, emit_progress=lambda *_: None, cancel_event=threading.Event(),
        )
    assert caught.value.category == "contract_validation"
    assert admitted and written
    if limit == "bytes":
        assert max(written) <= byte_limit
        assert max(admitted) <= byte_limit
    else:
        assert len(admitted) == 2
    assert {path.name: path.read_bytes() for path in store._objects.iterdir()} == before
    assert not tuple(store._temporary.iterdir())
    assert tuple(capability.workspace_root.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"


def _observe_preparation(
    monkeypatch: pytest.MonkeyPatch, event: threading.Event, boundary: str,
) -> tuple[list[str], list[int]]:
    consumed: list[str] = []
    growth: list[int] = []
    original_indexed = preparation_module._indexed
    original_spool = RowSpool.from_rows

    def indexed(descriptor, stage_id, rows, row_adapter):
        for row in original_indexed(descriptor, stage_id, rows, row_adapter):
            if descriptor.family == "raw_observations":
                consumed.append(descriptor.family)
                if boundary != "buffered-replay" and len(consumed) == 2:
                    event.set()
                    if boundary == "data-error-with-cancel":
                        raise ValueError("cancelled")
            yield row

    def spool(cls, rows, **kwargs):
        observer = kwargs.get("artifact_observer")

        def observe(size):
            if observer is not None:
                observer(size)
            growth.append(size)
            if boundary == "buffered-replay":
                event.set()

        return original_spool(rows, **dict(kwargs, artifact_observer=observe))

    monkeypatch.setattr(preparation_module, "_indexed", indexed)
    monkeypatch.setattr(RowSpool, "from_rows", classmethod(spool))
    return consumed, growth


@pytest.mark.parametrize("boundary", ["acquisition", "buffered-replay", "data-error-with-cancel"])
def test_preparation_cancellation_and_data_faults_stop_real_owned_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str,
) -> None:
    _, store, _, _, capability, sentinel = _setup(tmp_path, functions=4201)
    before = {path.name: path.read_bytes() for path in store._objects.iterdir()}
    event = threading.Event()
    consumed, growth = _observe_preparation(monkeypatch, event, boundary)
    with pytest.raises(adapter.PortableExecutionError) as caught:
        adapter.execute_portable_extraction(capability, emit_progress=lambda *_: None, cancel_event=event)
    assert caught.value.category == ("contract_validation" if boundary == "data-error-with-cancel" else "cancelled")
    assert len(consumed) == (4097 if boundary == "buffered-replay" else 2)
    assert len(growth) == (1 if boundary == "buffered-replay" else 0)
    assert {path.name: path.read_bytes() for path in store._objects.iterdir()} == before
    assert not tuple(store._temporary.iterdir())
    assert tuple(capability.workspace_root.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"




def test_actual_large_worker_spools_are_attempt_owned_and_byte_equivalent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, store, manifest, candidate_id, capability, sentinel = _setup(tmp_path, functions=4201)
    reference = capture_multi_source_candidate(config)
    expected = reference_bytes(reference, manifest, capability, tmp_path / "reference-sort")
    ambient = tmp_path / "ambient"
    ambient.mkdir(mode=0o700)
    allocations: list[tuple[Path, int]] = []
    original_spool = RowSpool.from_rows
    storage_prepared = False

    def spool(cls, rows, **kwargs):
        result = original_spool(rows, **kwargs)
        allocations.append((result.path, result.count))
        return result

    def progress(phase: str, _done: int, _total: int) -> None:
        nonlocal storage_prepared
        if phase == "storage_prepare":
            storage_prepared = True
            assert allocations and max(count for _, count in allocations) > 4096
            for path, _count in allocations:
                assert path.is_file()
                assert path.parent.parent == capability.workspace_root
                assert path.parent.name.startswith("attempt-1-")
            assert not tuple(ambient.iterdir())

    monkeypatch.setattr(tempfile, "tempdir", str(ambient))
    monkeypatch.setattr(RowSpool, "from_rows", classmethod(spool))
    result = adapter.execute_portable_extraction(capability, emit_progress=progress, cancel_event=threading.Event())
    assert storage_prepared
    assert store.read(result.bundle_reference) == expected
    assert result.candidate_id == candidate_id
    validation = PublisherBundleValidator().validate_bundle(
        store=store, bundle_reference=result.bundle_reference, receipt_reference=result.receipt_reference,
        expectation=publication_expectation(manifest, capability, candidate_id),
    )
    assert validation.byte_integrity_valid and validation.semantic_authority_valid
    assert all(not path.exists() for path, _count in allocations)
    assert not tuple(ambient.iterdir())
    assert tuple(capability.workspace_root.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"


@pytest.mark.parametrize("invalid_input", [False, True], ids=["actual-event-checkpoint", "data-error-with-cancel-set"])
def test_real_encoder_cancellation_and_data_failure_keep_distinct_categories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_input: bool,
) -> None:
    _config, _store, _manifest, _candidate_id, capability, sentinel = _setup(tmp_path)
    event = threading.Event()
    consumed = 0

    class Encoder(StreamingBundleEncoder):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            original_rows = self.family_rows["files"]

            def rows():
                nonlocal consumed
                for row in original_rows:
                    consumed += 1
                    event.set()
                    if invalid_input:
                        raise ValueError("cancelled")
                    yield row

            families: dict[str, Iterable[dict[str, object]]] = {}
            for family, values in self.family_rows.items():
                families[family] = values
            families["files"] = rows()
            self.family_rows = families

    monkeypatch.setattr(adapter, "StreamingBundleEncoder", Encoder)
    with pytest.raises(adapter.PortableExecutionError) as caught:
        adapter.execute_portable_extraction(capability, emit_progress=lambda *_: None, cancel_event=event)
    assert caught.value.category == ("contract_validation" if invalid_input else "cancelled")
    assert consumed == 1
    assert tuple(capability.workspace_root.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"


@pytest.mark.parametrize("failure", [StorageSchemaError("synthetic preparation refusal"), OSError("synthetic I/O refusal"), RuntimeError("synthetic operation refusal")])
def test_preparation_boundary_maps_only_contract_data_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception,
) -> None:
    _config, _store, _manifest, _candidate_id, capability, sentinel = _setup(tmp_path)

    def refuse(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(adapter, "build_staged_rows", refuse)
    expected = adapter.PortableExecutionError if isinstance(failure, ValueError) else type(failure)
    with pytest.raises(expected) as caught:
        adapter.execute_portable_extraction(capability, emit_progress=lambda *_: None, cancel_event=threading.Event())
    if isinstance(failure, ValueError):
        assert isinstance(caught.value, adapter.PortableExecutionError)
        assert caught.value.category == "contract_validation"
        assert caught.value.__cause__ is failure
    else:
        assert caught.value is failure
    assert tuple(capability.workspace_root.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"


def test_real_worker_multilevel_merge_is_attempt_owned_and_byte_equivalent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, store, manifest, candidate_id, capability, sentinel = _setup(tmp_path, functions=12)
    reference = capture_multi_source_candidate(config)
    expected = reference_bytes(reference, manifest, capability, tmp_path / "reference-sort")
    witness = SortIOWitness()
    remaining = observe_sort_directory_cleanup(monkeypatch)

    class Encoder(StreamingBundleEncoder):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, max_sorter_buffer_bytes=1)

    monkeypatch.setattr(adapter, "StreamingBundleEncoder", Encoder)
    monkeypatch.setattr(sorter_module, "_MAX_MERGE_FAN_IN", 3)
    monkeypatch.setattr(sorter_module, "open", witness.open_run, raising=False)
    monkeypatch.setattr(runs_module.tempfile, "NamedTemporaryFile", witness.temporary)
    result = adapter.execute_portable_extraction(
        capability, emit_progress=lambda *_: None, cancel_event=threading.Event(),
    )
    assert result.candidate_id == candidate_id
    assert store.read(result.bundle_reference) == expected
    assert len(witness.merge_paths) > 3 and witness.inputs
    assert witness.peak_handles <= 4 and witness.all_closed
    assert remaining and not any(remaining)
    assert all(not path.exists() for path in witness.merge_paths)
    assert all(path.parent.parent.parent == capability.workspace_root for path in witness.merge_paths)
    assert all(path.parent.parent.name.startswith("attempt-1-") for path in witness.merge_paths)
    validated = PublisherBundleValidator().validate_bundle(
        store=store, bundle_reference=result.bundle_reference, receipt_reference=result.receipt_reference,
        expectation=publication_expectation(manifest, capability, candidate_id),
    )
    assert validated.byte_integrity_valid and validated.semantic_authority_valid
    assert tuple(capability.workspace_root.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"


def test_real_worker_overflow_stops_sorter_consumption_without_publishing_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, store, _, _, capability, sentinel = _setup(tmp_path, functions=12)
    before = {path.name: path.read_bytes() for path in store._objects.iterdir()}
    consumed: list[str] = []
    closed: list[str] = []
    remaining = observe_sort_directory_cleanup(monkeypatch)

    def witnessed(family, values):
        try:
            for row in values:
                consumed.append(family)
                yield row
        finally:
            closed.append(family)

    class Encoder(StreamingBundleEncoder):
        def __init__(self, **kwargs):
            super().__init__(**kwargs, max_sorter_buffer_bytes=1)
            self.family_rows = {family: witnessed(family, values) for family, values in self.family_rows.items()}

    monkeypatch.setattr(adapter, "StreamingBundleEncoder", Encoder)
    monkeypatch.setattr(encoder_module, "MAX_BUNDLE_RECORDS", 2)
    with pytest.raises(adapter.PortableExecutionError) as caught:
        adapter.execute_portable_extraction(
            capability, emit_progress=lambda *_: None, cancel_event=threading.Event(),
        )
    assert caught.value.category == "contract_validation"
    assert consumed == ["files", "raw_observations", "raw_observations"]
    assert closed == ["files", "raw_observations"]
    assert remaining and not any(remaining)
    assert {path.name: path.read_bytes() for path in store._objects.iterdir()} == before
    assert not tuple(store._temporary.iterdir())
    assert tuple(capability.workspace_root.iterdir()) == (sentinel,)
    assert sentinel.read_bytes() == b"preserved"
