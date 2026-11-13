"""Actual portable adapter capture faults with real source, store and temp custody."""
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import pytest
from common_lore_index.artifacts.source_sealer import seal_configured_sources
from common_lore_index.coordinator import _portable_semantic_adapter as adapter
from common_lore_index.graph import multi_source_pipeline as pipeline
from common_lore_index.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_test_support.capture_cancellation_fixtures import CAPTURE_CHUNK, observe_capture_io
from repomap_test_support.portable_spool_case import spool_case
from repomap_test_support.portable_worker_equivalence import reference_bytes


def _large_case(tmp_path):
    config, store, manifest, candidate, capability, sentinel = spool_case(tmp_path)
    source = Path(config.effective_source_bindings[0].root_path_expanded)
    (source / "public.payload").write_bytes(b"# public fixture\n" + b"#" * (3 * CAPTURE_CHUNK) + b"\n")
    manifest, reference, candidate = seal_configured_sources(
        config, store, extractor_generation="eg1:spool", canonicalizer_generation="kg1:spool",
    )
    from dataclasses import replace
    capability = replace(capability, manifest_reference=reference,
                         source_generation=manifest.source_generation, config_generation=manifest.config_generation)
    return config, store, manifest, candidate, capability, sentinel


class ExtractionIterator:
    """Actual extracted observations with injected iterator/release faults."""
    def __init__(self, values, event, mode, observed):
        self.values, self.event, self.mode, self.observed = iter(values), event, mode, observed

    def __iter__(self):
        return self

    def __next__(self):
        if self.mode == "lazy-body-error":
            self.event.set()
            raise ValueError("cancelled")
        value = next(self.values)
        self.observed["consumed"] += 1
        if self.mode not in {"lazy-close-error", "lazy-close-handled-caller"}:
            self.event.set()
        return value

    def close(self):
        self.observed["closes"] += 1
        if "close" in self.mode:
            raise OSError("iterator release fixture")


def _fault(monkeypatch, event, mode, observed):
    if mode.startswith("stable"):
        def after_chunk():
            event.set()
            if mode == "stable-source-error":
                raise OSError("actual capture source error")
        result = observe_capture_io(monkeypatch, after_chunk)
        if mode == "stable-cancel-close-error":
            original_open = Path.open

            def opened(path, mode="r", *args, **kwargs):
                writer = original_open(path, mode, *args, **kwargs)
                if mode != "wb":
                    return writer

                def close():
                    writer.close()
                    observed["closes"] += 1
                    raise OSError("legacy staged writer close fixture")

                return SimpleNamespace(write=writer.write, close=close)

            monkeypatch.setattr(Path, "open", opened)
        return result
    original = pipeline.extract_observations_from_repository_files

    def extract(*args, **kwargs):
        if mode.startswith("lazy-"):
            iterator = ExtractionIterator(original(*args, **dict(kwargs, cancel_check=None)), event, mode, observed)
            if mode == "lazy-pre-consumption-cancel":
                event.set()
            return iterator
        event.set()
        if mode == "extractor-error":
            raise ValueError("cancelled")
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "extract_observations_from_repository_files", extract)
    return [], [], []


def _assert_legacy_close_chain(error, observed):
    assert observed["closes"] == 1
    current = error
    chain = []
    while current is not None:
        chain.append(current)
        current = current.__cause__
    assert not any(type(item).__name__ == "_CaptureAbort" for item in chain)
    source_error = next(item for item in chain if isinstance(item, OSError))
    callback_error = source_error.__context__
    assert isinstance(callback_error, adapter.PortableExecutionError) and callback_error.category == "cancelled"


def _execute_with_caller_state(capability, event, mode):
    if mode == "lazy-close-handled-caller":
        try:
            raise ValueError("handled caller exception")
        except ValueError:
            return adapter.execute_portable_extraction(capability, emit_progress=lambda *_: None, cancel_event=event)
    return adapter.execute_portable_extraction(capability, emit_progress=lambda *_: None, cancel_event=event)


@pytest.mark.parametrize("mode", ["stable-cancel", "stable-source-error", "stable-cancel-close-error", "extraction-cancel", "extractor-error", "lazy-extraction", "lazy-close-error", "lazy-close-handled-caller", "lazy-pre-consumption-cancel", "lazy-cancel-close-error", "lazy-body-error"])
def test_capture_fault_precedence_and_exact_resource_cleanup(tmp_path, monkeypatch, mode):
    _, store, _, _, capability, sentinel = _large_case(tmp_path)
    before = {p.name: p.read_bytes() for p in store._objects.iterdir()}
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(ambient))
    event = threading.Event()
    observed = {"consumed": 0, "closes": 0}
    consumed, written, sources = _fault(monkeypatch, event, mode, observed)
    with pytest.raises(adapter.PortableExecutionError) as caught:
        _execute_with_caller_state(capability, event, mode)
    expected = {"stable-source-error": "source_capture", "stable-cancel-close-error": "source_capture", "extractor-error": "source_capture", "lazy-close-error": "source_capture", "lazy-close-handled-caller": "source_capture", "lazy-body-error": "source_capture"}.get(mode, "cancelled")
    assert caught.value.category == expected
    if mode.startswith("stable"):
        assert 0 < sum(consumed) <= CAPTURE_CHUNK and sum(written) == 0
        assert sources and all(probe.reader.closed for probe in sources)
    if mode.startswith("lazy-"):
        assert observed["closes"] == 1
        if mode in {"lazy-extraction", "lazy-cancel-close-error"}:
            assert observed["consumed"] == 1
        if mode == "lazy-pre-consumption-cancel":
            assert observed["consumed"] == 0
    if mode == "stable-cancel-close-error":
        _assert_legacy_close_chain(caught.value, observed)
    assert {p.name: p.read_bytes() for p in store._objects.iterdir()} == before
    assert not tuple(store._temporary.iterdir()) and not tuple(ambient.iterdir())
    assert tuple(capability.workspace_root.iterdir()) == (sentinel,) and sentinel.read_bytes() == b"preserved"


def test_controlled_large_capture_keeps_reference_bundle_and_default_checkpoints(tmp_path):
    config, store, manifest, _, capability, sentinel = _large_case(tmp_path)
    expected = reference_bytes(capture_multi_source_candidate(config), manifest, capability, tmp_path / "reference-sort")
    phases = []
    result = adapter.execute_portable_extraction(capability, emit_progress=lambda *phase: phases.append(phase), cancel_event=threading.Event())
    assert store.read(result.bundle_reference) == expected and phases
    assert tuple(capability.workspace_root.iterdir()) == (sentinel,)
