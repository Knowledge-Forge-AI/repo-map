from repomap_kg.ops.graph_file_records import graph_file_record_from_payload


def test_graph_file_readback_exposes_source_qualified_candidate_membership():
    payload = {
        "canonical_key": "file:entry/modules/default.nix",
        "graph_key_version": 1,
        "metadata": {
            "language": "Nix",
            "role": "source",
            "generated": False,
            "executable": False,
            "binding_id": "bind1:" + "1" * 64,
            "binding_alias": "entry",
            "binding_role": "entry",
            "snapshot_id": "snap1:" + "2" * 64,
            "candidate_id": "cand1:" + "3" * 64,
            "source_relative_path": "modules/default.nix",
        },
        "confidence": "extracted",
        "conflict": False,
        "evidence_count": 1,
        "file_observation_count": 1,
        "link_kinds": ["observed"],
    }

    record = graph_file_record_from_payload(payload)
    result = record.to_jsonable()

    assert result["path"] == "modules/default.nix"
    assert result["source_binding"] == {
        "binding_id": "bind1:" + "1" * 64,
        "alias": "entry",
        "role": "entry",
        "snapshot_id": "snap1:" + "2" * 64,
    }
    assert result["candidate_id"] == "cand1:" + "3" * 64


def test_legacy_graph_file_readback_shape_remains_compatible():
    payload = {
        "canonical_key": "file:modules/default.nix",
        "graph_key_version": 1,
        "metadata": {
            "language": "Nix",
            "role": "source",
            "generated": False,
            "executable": False,
        },
        "confidence": "extracted",
        "conflict": False,
        "evidence_count": 1,
        "file_observation_count": 1,
        "link_kinds": ["observed"],
    }

    result = graph_file_record_from_payload(payload).to_jsonable()

    assert result["path"] == "modules/default.nix"
    assert result["source_binding"] is None
    assert result["candidate_id"] is None


def test_database_independent_single_source_root_observation_and_projection():
    from pathlib import Path
    from types import SimpleNamespace
    from typing import TYPE_CHECKING, cast
    from repomap_kg.graph.multi_source_pipeline import _CapturedSource, _namespaced_observation
    from repomap_kg.observations.raw import RawObservation

    if TYPE_CHECKING:
        from repomap_kg.graph.multi_source_records import SourceSnapshot
        from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig

    raw = RawObservation(
        kind="file",
        source_id="repo-1:file:modules/default.nix",
        path="modules/default.nix",
        confidence="extracted",
        extractor="nix",
        extractor_version="1.0",
        target=None,
        name="modules/default.nix",
        metadata={"language": "Nix", "role": "source"},
    )
    source = _CapturedSource(
        config=cast(
            "OpsGraphSourceBindingConfig",
            SimpleNamespace(
                alias="root",
                binding_id="bind1:" + "4" * 64,
                role="root",
                revision=1,
            ),
        ),
        root=Path("/fake/root"),
        files=(),
        snapshot=cast(
            "SourceSnapshot",
            SimpleNamespace(
                binding=SimpleNamespace(graph_id="fixture-graph"),
                snapshot_id="snap1:" + "5" * 64,
                manifest_digest="dig1:" + "6" * 64,
            ),
        ),
        file_sizes=(),
    )
    namespaced = _namespaced_observation(raw, source)
    assert namespaced.path == "root/modules/default.nix"
    assert namespaced.metadata["source_relative_path"] == "modules/default.nix"
    assert namespaced.metadata["binding_alias"] == "root"

    payload = {
        "canonical_key": f"file:{namespaced.path}",
        "graph_key_version": 1,
        "metadata": namespaced.metadata,
        "confidence": "extracted",
        "conflict": False,
        "evidence_count": 1,
        "file_observation_count": 1,
        "link_kinds": ["observed"],
    }
    record = graph_file_record_from_payload(payload)
    assert record.path == "modules/default.nix"
    assert record.canonical_key == "file:root/modules/default.nix"
    assert record.binding_alias == "root"
    assert record.binding_id == "bind1:" + "4" * 64
    jsonable = record.to_jsonable()
    assert jsonable["path"] == "modules/default.nix"
    assert jsonable["canonical_key"] == "file:root/modules/default.nix"
    assert jsonable["source_binding"]["alias"] == "root"
