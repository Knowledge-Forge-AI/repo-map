"""Public capture callback boundary and unchanged source error precedence."""
import tempfile
from dataclasses import replace
from typing import TYPE_CHECKING, cast
import pytest
from common_lore_index import _temporary
from common_lore_index.graph import discovery, multi_source_pipeline as pipeline
from common_lore_index.graph._capture_control import CancelCheck
from common_lore_index.graph.multi_source_capture import _capture_inventory
from common_lore_index.graph.multi_source import graph_source_binding_id
from repomap_test_support.capture_cancellation_fixtures import capture_graph
if TYPE_CHECKING:
    from common_lore_index.artifacts._sealing_meter import SealingMeter


@pytest.mark.parametrize("error", [OSError("callback"), ValueError("callback"), RuntimeError("callback")])
@pytest.mark.parametrize("boundary", ["inventory", "extraction", "resolver", "final-inventory", "return"])
def test_actual_capture_callback_retains_identity_and_owned_root_cleanup(tmp_path, monkeypatch, error, boundary):
    graph = capture_graph(tmp_path / "source")
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(ambient))
    armed = boundary == "inventory"
    inventories = 0
    original_inventory, original_extract, original_resolve = pipeline._capture_inventory, pipeline.extract_observations_from_repository_files, pipeline.resolve_nix_relations

    def inventory(*args, **kwargs):
        nonlocal armed, inventories
        inventories += 1
        if inventories == 2 and boundary == "final-inventory":
            armed = True
        result = original_inventory(*args, **kwargs)
        if inventories == 2 and boundary == "return":
            armed = True
        return result

    def extract(*args, **kwargs):
        nonlocal armed
        armed = boundary == "extraction"
        return original_extract(*args, **kwargs)

    def resolve(*args, **kwargs):
        nonlocal armed
        result = original_resolve(*args, **kwargs)
        armed = boundary == "resolver"
        return result

    def check():
        if armed:
            raise error

    monkeypatch.setattr(pipeline, "_capture_inventory", inventory)
    monkeypatch.setattr(pipeline, "extract_observations_from_repository_files", extract)
    monkeypatch.setattr(pipeline, "resolve_nix_relations", resolve)
    with pytest.raises(type(error)) as caught:
        pipeline.capture_multi_source_candidate(graph, elide_discovery_hash=True, cancel_check=check)
    assert caught.value is error and error.__context__ is None
    assert not tuple(ambient.iterdir())


@pytest.mark.parametrize("invalid", [False, 1, "check", object()])
def test_invalid_callback_refuses_before_creating_owned_workspace(tmp_path, monkeypatch, invalid):
    graph = capture_graph(tmp_path / "source")
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(ambient))
    with pytest.raises(ValueError, match="must be callable"):
        pipeline.capture_multi_source_candidate(graph, cancel_check=cast(CancelCheck, invalid))
    assert not tuple(ambient.iterdir())


def test_shared_extraction_callback_is_plain_and_meter_composition_refuses_before_io(tmp_path):
    failure = OSError("plain shared-helper callback")

    def refuse():
        raise failure

    with pytest.raises(OSError) as caught:
        discovery.extract_observations_from_repository_files(tmp_path, (), cancel_check=refuse)
    assert caught.value is failure
    with pytest.raises(ValueError, match="cannot use a sealing meter"):
        _capture_inventory(capture_graph(tmp_path / "source"), io_meter=cast("SealingMeter", object()), cancel_check=lambda: None)


def test_outer_cleanup_receives_real_callback_and_keeps_legacy_precedence(tmp_path, monkeypatch):
    graph = capture_graph(tmp_path / "source")
    primary, cleanup = ValueError("callback"), RuntimeError("owned root cleanup")
    observed = []
    original = _temporary.OwnedTemporaryDirectory.cleanup

    def refuse():
        raise primary

    def cleanup_then_fail(self):
        original(self)
        observed.append(True)
        raise cleanup

    monkeypatch.setattr(_temporary.OwnedTemporaryDirectory, "cleanup", cleanup_then_fail)
    with pytest.raises(RuntimeError) as caught:
        pipeline.capture_multi_source_candidate(graph, cancel_check=refuse)
    assert caught.value is cleanup and cleanup.__context__ is primary and observed == [True]


@pytest.mark.parametrize("seam", ["resolve_nix_relations", "_capture_inventory", "discover_repository", "extract_observations_from_repository_files"])
def test_default_facade_seams_are_resolved_at_the_original_work_phase(tmp_path, monkeypatch, seam):
    graph = capture_graph(tmp_path / "source")
    if seam == "extract_observations_from_repository_files":
        binding = graph.effective_source_bindings[0]
        other = replace(binding, binding_id=graph_source_binding_id(graph.id, "other"), alias="other",
                        source_definition_id="src1:other", role="module", input_name="other")
        graph = replace(graph, source_bindings=(binding, other))
    original_extract = pipeline.extract_observations_from_repository_files
    original_seam = getattr(pipeline, seam)
    called = []

    def replacement(*args, **kwargs):
        called.append(seam)
        return original_seam(*args, **kwargs)

    def extract(*args, **kwargs):
        result = original_extract(*args, **kwargs)
        monkeypatch.setattr(pipeline, seam, replacement)
        return result

    monkeypatch.setattr(pipeline, "extract_observations_from_repository_files", extract)
    result = pipeline.capture_multi_source_candidate(graph)
    assert result.observations and called == [seam]
