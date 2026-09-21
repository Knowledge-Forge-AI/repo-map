import hashlib

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.observations.raw import RawObservation


def _file(alias: str) -> RawObservation:
    path = f"{alias}/modules/default.nix"
    return RawObservation(
        kind="file",
        source_id=f"bind:{alias}:{path}",
        path=path,
        name=path,
        confidence="extracted",
        extractor="repo-discovery",
        extractor_version="fixture",
        metadata={
            "language": "Nix",
            "role": "source",
            "content_hash": alias * 8,
            "executable": False,
            "generated": False,
            "binding_id": f"bind1:{alias}",
            "binding_alias": alias,
            "binding_role": "module",
            "snapshot_id": f"snap1:{alias}",
            "candidate_id": "cand1:fixture",
            "source_relative_path": "modules/default.nix",
        },
    )


def test_binding_qualified_files_and_cross_source_edge_remain_distinct():
    relation = RawObservation(
        kind="nix.import",
        source_id="bind:entry:flake.nix#input",
        path="entry/flake.nix",
        target="file:composition/modules/default.nix",
        confidence="extracted",
        extractor="nix",
        extractor_version="fixture",
        metadata={
            "resolved_path": "composition/modules/default.nix",
            "resolution_outcome": "exact",
            "resolution_evidence_class": "static-literal",
            "cross_binding": True,
            "source_binding": "entry",
            "target_binding": "composition",
            "binding_id": "bind1:entry",
            "snapshot_id": "snap1:entry",
            "candidate_id": "cand1:fixture",
        },
    )

    result = canonicalize_observations((_file("entry"), _file("composition"), relation))

    keys = {item.canonical_key for item in result.graph.nodes}
    assert "file:entry/modules/default.nix" in keys
    assert "file:composition/modules/default.nix" in keys
    edge = next(item for item in result.graph.edges if item.kind == "sources")
    assert edge.source_key == "file:entry/flake.nix"
    assert edge.target_key == "file:composition/modules/default.nix"
    assert edge.metadata["resolution_outcome"] == "exact"
    assert edge.metadata["cross_binding"] is True
    assert edge.metadata["candidate_id"] == "cand1:fixture"


def test_non_exact_resolution_uses_per_observation_identity():
    first = RawObservation(
        kind="nix.import",
        source_id="bind:entry:flake.nix#dynamic-one",
        path="entry/flake.nix",
        target="dynamic:file:nix-cross-source-evaluation-dependent",
        confidence="heuristic",
        extractor="nix",
        extractor_version="fixture",
        metadata={
            "dynamic_reason": "nix-cross-source-evaluation-dependent",
            "resolution_outcome": "evaluation-dependent",
            "resolution_evidence_class": "bounded-unknown",
            "cross_binding": True,
            "source_binding": "entry",
            "target_binding": "one",
            "binding_id": "bind1:entry",
            "snapshot_id": "snap1:entry",
            "candidate_id": "cand1:fixture",
        },
    )
    second = RawObservation(
        kind="nix.import",
        source_id="bind:entry:flake.nix#dynamic-two",
        path="entry/flake.nix",
        target="dynamic:file:nix-cross-source-evaluation-dependent",
        confidence="heuristic",
        extractor="nix",
        extractor_version="fixture",
        metadata={
            "dynamic_reason": "nix-cross-source-evaluation-dependent",
            "resolution_outcome": "evaluation-dependent",
            "resolution_evidence_class": "bounded-unknown",
            "cross_binding": True,
            "source_binding": "entry",
            "target_binding": "two",
            "binding_id": "bind1:entry",
            "snapshot_id": "snap1:entry",
            "candidate_id": "cand1:fixture",
        },
    )

    result = canonicalize_observations((first, second))
    repeated = canonicalize_observations((second, first))

    edges = [item for item in result.graph.edges if item.kind == "sources"]
    repeated_edges = [
        item for item in repeated.graph.edges if item.kind == "sources"
    ]

    assert len(edges) == 2
    assert len({item.target_key for item in edges}) == 2
    assert {item.metadata["target_binding"] for item in edges} == {"one", "two"}
    assert all(
        isinstance(item.metadata["target_binding"], str) for item in edges
    )
    assert all(
        isinstance(item.metadata["source_binding"], str) for item in edges
    )
    assert {item.target_key for item in edges} == {
        item.target_key for item in repeated_edges
    }
    assert all(
        item.target_key.startswith("dynamic:file:") for item in edges
    )


def test_unsupported_resolution_produces_opaque_unknown_target_with_deterministic_digest():
    raw_source_id = "bind:entry:flake.nix#escape"
    expected_digest = hashlib.sha256(raw_source_id.encode("utf-8")).hexdigest()[:24]
    expected_placeholder = f"unknown:file:nix-cross-source-unsupported#{expected_digest}"

    obs = RawObservation(
        kind="nix.import",
        source_id=raw_source_id,
        path="entry/flake.nix",
        target="unknown:file:nix-cross-source-unsupported",
        confidence="heuristic",
        extractor="nix",
        extractor_version="fixture",
        metadata={
            "resolution_outcome": "unsupported",
            "resolution_evidence_class": "bounded-unknown",
            "cross_binding": False,
            "source_binding": "entry",
            "target_binding": "entry",
            "binding_id": "bind1:entry",
            "snapshot_id": "snap1:entry",
            "candidate_id": "cand1:fixture",
        },
    )

    result = canonicalize_observations((obs,))
    diag_categories = {d.category for d in result.diagnostics}
    assert "opaque_unknown_target" in diag_categories
    assert "unsupported_raw_observation_kind" not in diag_categories

    edge = next(item for item in result.graph.edges if item.kind == "sources")
    assert edge.target_key == expected_placeholder
    assert edge.metadata["resolution_outcome"] == "unsupported"
