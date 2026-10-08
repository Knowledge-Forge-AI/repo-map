"""Pure identity and snapshot contracts exercised through maintained record constructors."""

from dataclasses import replace
from typing import cast

import pytest

from repomap_kg.graph.multi_source import (
    GraphSourceBinding, MultiSourceIdentityError, SnapshotManifestEntry,
    SourceDefinition, SourceKind, SourceSnapshot, graph_source_binding_id,
    multi_source_configuration_id, source_selection_policy_id,
)


def _binding():
    return GraphSourceBinding.create(
        graph_id="fixture-graph", alias="svc",
        source_definition=SourceDefinition.create("svc", SourceKind.FOLDER),
        revision=1, logical_root=".", privacy_policy="public-dev",
        evidence_retention_policy="inherit", extractor_profile="default",
        selection_policy_id=source_selection_policy_id((), ()), resolution_policy="isolated",
    )


def test_graph_source_binding_and_configuration_invariants() -> None:
    for bad_id in ("", None, 123, "graph\u2022id", "bad id", "bad/id"):
        with pytest.raises(MultiSourceIdentityError, match="graph identity"):
            graph_source_binding_id(cast(str, bad_id), "svc")

    for bad_root in ("/abs", "../escape", "foo//bar", "foo/"):
        with pytest.raises(MultiSourceIdentityError, match="logical root"):
            replace(_binding(), logical_root=bad_root)

    with pytest.raises(MultiSourceIdentityError, match="source kind"):
        SourceDefinition("src1:id", cast(SourceKind, "not-a-kind"))

    sdef = SourceDefinition.create("svc", SourceKind.FOLDER)
    select_id = source_selection_policy_id((), ())
    good_bid = graph_source_binding_id("fixture-graph", "svc")

    with pytest.raises(MultiSourceIdentityError, match="graph source binding identity"):
        GraphSourceBinding(
            "bind1:" + "0" * 64, "fixture-graph", "svc", sdef, 1, ".",
            "public-dev", "inherit", "default", select_id, "isolated",
        )
    with pytest.raises(MultiSourceIdentityError, match="source definition"):
        GraphSourceBinding(
            good_bid, "fixture-graph", "svc", cast(SourceDefinition, "not-def"), 1, ".",
            "public-dev", "inherit", "default", select_id, "isolated",
        )

    for bad_rev in (0, -1, True, "1"):
        with pytest.raises(MultiSourceIdentityError, match="binding revision"):
            GraphSourceBinding(
                good_bid, "fixture-graph", "svc", sdef, cast(int, bad_rev), ".",
                "public-dev", "inherit", "default", select_id, "isolated",
            )

    good_binding = GraphSourceBinding.create(
        graph_id="fixture-graph", alias="svc", source_definition=sdef, revision=1,
        logical_root=".", privacy_policy="public-dev", evidence_retention_policy="inherit",
        extractor_profile="default", selection_policy_id=select_id, resolution_policy="isolated",
    )
    with pytest.raises(MultiSourceIdentityError):
        replace(good_binding, privacy_policy="unsupported-privacy")
    with pytest.raises(MultiSourceIdentityError):
        replace(good_binding, evidence_retention_policy="unsupported-retention")
    with pytest.raises(MultiSourceIdentityError):
        replace(good_binding, resolution_policy="unsupported-resolution")
    with pytest.raises(MultiSourceIdentityError):
        replace(good_binding, enabled=cast(bool, "true"))

    with pytest.raises(MultiSourceIdentityError, match="binding inventory"):
        multi_source_configuration_id("fixture-graph", ())



def test_snapshot_manifest_and_identity_validation_invariants() -> None:
    for bad_path in ("/abs", "../escape", ".", ""):
        with pytest.raises(MultiSourceIdentityError, match="manifest path"):
            SnapshotManifestEntry(bad_path, "a" * 64, 10, False)

    for bad_hash in ("bad-hash", "g" * 64):
        with pytest.raises(MultiSourceIdentityError, match="manifest content digest"):
            SnapshotManifestEntry("a.txt", bad_hash, 10, False)

    for bad_size in (-1, True, 2**63):
        with pytest.raises(MultiSourceIdentityError, match="manifest size"):
            SnapshotManifestEntry("a.txt", "a" * 64, bad_size, False)

    with pytest.raises(MultiSourceIdentityError, match="manifest mode"):
        SnapshotManifestEntry("a.txt", "a" * 64, 10, cast(bool, "yes"))

    binding = GraphSourceBinding.create(
        graph_id="fixture-graph", alias="svc",
        source_definition=SourceDefinition.create("svc", SourceKind.FOLDER),
        revision=1, logical_root=".", privacy_policy="public-dev",
        evidence_retention_policy="inherit", extractor_profile="default",
        selection_policy_id=source_selection_policy_id((), ()), resolution_policy="isolated",
    )
    entry1 = SnapshotManifestEntry("a.txt", "a" * 64, 10, False)
    entry2 = SnapshotManifestEntry("b.txt", "b" * 64, 20, False)

    with pytest.raises(MultiSourceIdentityError, match="snapshot binding"):
        SourceSnapshot(
            "snap1:" + "0" * 64, cast(GraphSourceBinding, "bad-binding"), (entry1,), "manifest1:" + "0" * 64,
            None, None, "ignore1:dec", "meta1:fix",
        )

    for bad_git in ("not-hex", "1" * 39, "1" * 65):
        with pytest.raises(MultiSourceIdentityError, match="Git object identity"):
            SourceSnapshot.create(
                binding, manifest_entries=(entry1,), git_commit=bad_git, git_tree=None,
                ignore_policy_id="ignore1:dec", metadata_identity="meta1:fix",
            )

    with pytest.raises(MultiSourceIdentityError, match="manifest ordering"):
        SourceSnapshot(
            "snap1:" + "0" * 64, binding, (entry2, entry1), "manifest1:" + "0" * 64,
            None, None, "ignore1:dec", "meta1:fix",
        )

    with pytest.raises(MultiSourceIdentityError, match="snapshot content identity"):
        SourceSnapshot.create(
            binding, manifest_entries=(), git_commit=None, git_tree=None,
            ignore_policy_id="ignore1:dec", metadata_identity="meta1:fix",
        )
