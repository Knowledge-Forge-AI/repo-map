"""Real sealed worker spools stay inside their attempt across success and failure."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import tempfile
import threading

import pytest

from common_lore_index.artifacts.source_sealer import seal_configured_sources
from common_lore_index.artifacts._bundle_stream_encode import StreamingBundleEncoder
from common_lore_index.artifacts.store import FileSystemArtifactStore
from common_lore_index.artifacts.validator import PublisherBundleValidator
from common_lore_index.coordinator import _portable_semantic_adapter as adapter
from common_lore_index.coordinator._portable_capability import PortableExecutionCapability
from common_lore_index.graph.multi_source_pipeline import capture_multi_source_candidate
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.row_spool import RowSpool
from repomap_test_support.portable_publication_fixtures import create_single_source_graph_config
from repomap_test_support.portable_worker_equivalence import reference_bytes, publication_expectation


def _setup(tmp_path: Path, *, functions: int = 1):
    tmp_path.chmod(0o700)
    source = tmp_path / "source"
    source.mkdir()
    (source / "public.py").write_text(
        "".join(f"def function_{index}():\n    return {index}\n\n" for index in range(functions)),
        encoding="utf-8",
    )
    config = create_single_source_graph_config(source, graph_id="spool-custody", repository_name="public-spool")
    store_root = tmp_path / "store"
    store_root.mkdir(mode=0o700)
    store = FileSystemArtifactStore(store_root)
    manifest, reference, candidate_id = seal_configured_sources(
        config, store, extractor_generation="eg1:spool", canonicalizer_generation="kg1:spool",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    sentinel = workspace / "unrelated-sentinel"
    sentinel.write_bytes(b"preserved")
    capability = PortableExecutionCapability(
        schema_version=1, job_id="job-spool-custody", attempt=1, graph_id=manifest.graph_id,
        store_root=store_root, workspace_root=workspace, manifest_reference=reference,
        source_generation=manifest.source_generation, config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation, canonicalizer_generation=manifest.canonicalizer_generation,
        max_artifact_bytes=64 * 1024 * 1024, max_bundle_bytes=64 * 1024 * 1024,
    )
    return config, store, manifest, candidate_id, capability, sentinel


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
