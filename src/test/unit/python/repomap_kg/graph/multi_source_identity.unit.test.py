from dataclasses import replace

import pytest

from repomap_kg.graph.multi_source import (
    GraphCandidate,
    GraphSourceBinding,
    MultiSourceIdentityError,
    SnapshotManifestEntry,
    SourceDefinition,
    SourceKind,
    SourceSnapshot,
    compatibility_extractor_profile,
    compatibility_source_selection_policy_id,
    compatibility_source_definition_id,
    graph_source_binding_id,
    multi_source_configuration_id,
    source_definition_id,
    source_selection_policy_id,
)
from repomap_kg.graph.multi_source_capture import MultiSourceCaptureError
from repomap_kg.graph.multi_source_pipeline import (
    _multi_source_source_generation,
    multi_source_config_generation,
    multi_source_semantic_identities,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig


def _binding(
    alias: str,
    *,
    source: str | None = None,
    role: str = "source",
    input_name: str | None = None,
) -> GraphSourceBinding:
    definition = SourceDefinition.create(source or alias, SourceKind.GIT_WORKING_TREE)
    return GraphSourceBinding.create(
        graph_id="fixture-graph",
        alias=alias,
        source_definition=definition,
        revision=1,
        logical_root=".",
        privacy_policy="public-dev",
        evidence_retention_policy="inherit",
        extractor_profile="default",
        selection_policy_id=source_selection_policy_id((), ("result-*",)),
        resolution_policy="isolated",
        role=role,
        input_name=input_name,
    )


def _snapshot(binding: GraphSourceBinding, digest: str) -> SourceSnapshot:
    return SourceSnapshot.create(
        binding,
        manifest_entries=(
            SnapshotManifestEntry("shared/default.nix", digest, 17, False),
        ),
        git_commit="1" * 40,
        git_tree="2" * 40,
        ignore_policy_id="ignore1:declared",
        metadata_identity="meta1:fixture",
    )


def _candidate(snapshots: tuple[SourceSnapshot, ...], **overrides: str) -> GraphCandidate:
    bindings = tuple(
        {snapshot.binding.binding_id: snapshot.binding for snapshot in snapshots}.values()
    )
    values = {
        "configuration_identity": multi_source_configuration_id(
            "fixture-graph", bindings
        ),
        "extractor_capability_identity": "cap1:repomap-default",
        "resolver_identity": "resolver1:isolated",
        "canonicalizer_identity": "canon1:repomap",
        "semantic_contract_identity": "semantic1:graph-key-v1",
        "quality_rule_identity": "quality1:default",
    }
    values.update(overrides)
    return GraphCandidate.create("fixture-graph", snapshots, **values)


def test_source_and_binding_grammars_are_bounded_and_versioned():
    assert source_definition_id("root") == "src1:root"
    assert graph_source_binding_id("fixture-graph", "root").startswith("bind1:")

    with pytest.raises(MultiSourceIdentityError, match="source definition identity"):
        SourceDefinition("src2:root", SourceKind.FOLDER)
    with pytest.raises(MultiSourceIdentityError, match="source definition identifier"):
        source_definition_id("A" * 125)
    with pytest.raises(MultiSourceIdentityError, match="binding alias"):
        graph_source_binding_id("fixture-graph", "Private Root")
    assert compatibility_source_definition_id("g" * 5000).startswith(
        "src1:legacy-"
    )


def test_binding_identity_is_relocation_independent_and_inventory_local():
    root = _binding("root")
    security = _binding("security")
    assert root.binding_id == _binding("root").binding_id
    assert root.binding_id != security.binding_id


def test_configuration_and_candidate_identity_bind_role_and_input_name():
    baseline = _snapshot(_binding("root"), "a" * 64)
    role_variant = _snapshot(
        _binding("root", role="composition"), "a" * 64
    )
    input_variant = _snapshot(
        _binding("root", input_name="composition"), "a" * 64
    )

    assert baseline.binding.binding_id == role_variant.binding.binding_id
    assert baseline.binding.binding_id == input_variant.binding.binding_id
    assert multi_source_configuration_id(
        "fixture-graph", (baseline.binding,)
    ) != multi_source_configuration_id("fixture-graph", (role_variant.binding,))
    assert multi_source_configuration_id(
        "fixture-graph", (baseline.binding,)
    ) != multi_source_configuration_id("fixture-graph", (input_variant.binding,))
    assert _candidate((baseline,)).candidate_id != _candidate((role_variant,)).candidate_id
    assert _candidate((baseline,)).candidate_id != _candidate((input_variant,)).candidate_id


@pytest.mark.parametrize(
    "field,value",
    (
        ("role", ""),
        ("role", "r" * 65),
        ("role", "bad role"),
        ("role", "bad/name"),
        ("role", "bad\nrole"),
        ("role", "BadRole"),
        ("role", "naïve"),
        ("input_name", ""),
        ("input_name", "i" * 65),
        ("input_name", "bad name"),
        ("input_name", "bad.name"),
        ("input_name", "bad/name"),
        ("input_name", "bad\nname"),
        ("input_name", "naïve"),
    ),
)
def test_role_and_input_name_grammars_reject_unbounded_or_unsafe_values(
    field: str, value: str
):
    with pytest.raises(MultiSourceIdentityError, match=f"{field.replace('_', ' ')}"):
        _binding("root", **{field: value})


def test_legacy_compatibility_identities_bind_exact_values_without_token_validation():
    excludes = ("result-*", "result-*", "naive-路径", ".", "x" * 300)
    assert compatibility_source_selection_policy_id(excludes) == (
        compatibility_source_selection_policy_id(excludes)
    )
    assert compatibility_source_selection_policy_id(excludes) != (
        compatibility_source_selection_policy_id(tuple(reversed(excludes)))
    )
    assert compatibility_extractor_profile("default") == "default"
    assert compatibility_extractor_profile("Legacy_Profile With Spaces").startswith(
        "legacy-"
    )
    assert compatibility_extractor_profile("Legacy_Profile With Spaces") == (
        compatibility_extractor_profile("Legacy_Profile With Spaces")
    )


def test_strict_and_compatibility_extractor_profiles_use_disjoint_domains():
    derived = compatibility_extractor_profile("Legacy Profile With Spaces")
    escaped_reserved_input = compatibility_extractor_profile(derived)

    assert derived.startswith("legacy-")
    assert escaped_reserved_input.startswith("legacy-strict-v1-")
    assert escaped_reserved_input != derived
    assert compatibility_extractor_profile("legacy-user-profile") == (
        "legacy-user-profile"
    )


def test_strict_selection_canonicalizes_while_legacy_preserves_sequence():
    ordered = ("z-output", "a-output")
    reversed_order = tuple(reversed(ordered))
    duplicated = ("z-output", "z-output", "a-output")

    assert source_selection_policy_id((), ordered) == source_selection_policy_id(
        (), reversed_order
    )
    assert compatibility_source_selection_policy_id(ordered) != (
        compatibility_source_selection_policy_id(reversed_order)
    )
    assert compatibility_source_selection_policy_id(duplicated) != (
        compatibility_source_selection_policy_id(("z-output", "a-output"))
    )


def test_manifest_order_is_canonical_and_duplicate_entries_fail_closed():
    binding = _binding("root")
    first = SnapshotManifestEntry("a.nix", "a" * 64, 1, False)
    second = SnapshotManifestEntry("b.nix", "b" * 64, 2, True)
    left = SourceSnapshot.create(
        binding,
        manifest_entries=(second, first),
        git_commit=None,
        git_tree=None,
        ignore_policy_id="ignore1:declared",
        metadata_identity="meta1:fixture",
    )
    right = SourceSnapshot.create(
        binding,
        manifest_entries=(first, second),
        git_commit=None,
        git_tree=None,
        ignore_policy_id="ignore1:declared",
        metadata_identity="meta1:fixture",
    )
    assert left == right

    with pytest.raises(MultiSourceIdentityError, match="duplicate manifest path"):
        SourceSnapshot.create(
            binding,
            manifest_entries=(first, first),
            git_commit=None,
            git_tree=None,
            ignore_policy_id="ignore1:declared",
            metadata_identity="meta1:fixture",
        )


def test_identical_relative_paths_remain_distinct_across_bindings():
    root = _snapshot(_binding("root"), "a" * 64)
    private = _snapshot(_binding("private"), "a" * 64)
    assert root.manifest_entries == private.manifest_entries
    assert root.snapshot_id != private.snapshot_id


def test_candidate_vector_order_is_canonical_and_duplicates_fail_closed():
    root = _snapshot(_binding("root"), "a" * 64)
    security = _snapshot(_binding("security"), "b" * 64)
    assert _candidate((root, security)) == _candidate((security, root))

    with pytest.raises(MultiSourceIdentityError, match="duplicate candidate binding"):
        _candidate((root, root))


@pytest.mark.parametrize(
    "field,value",
    (
        ("extractor_capability_identity", "cap1:changed"),
        ("resolver_identity", "resolver1:cross-source"),
        ("canonicalizer_identity", "canon1:changed"),
        ("semantic_contract_identity", "semantic1:graph-key-v1-plus-binding"),
        ("quality_rule_identity", "quality1:strict"),
    ),
)
def test_candidate_changes_for_each_semantic_input(field: str, value: str):
    snapshot = _snapshot(_binding("root"), "a" * 64)
    assert _candidate((snapshot,)).candidate_id != _candidate(
        (snapshot,), **{field: value}
    ).candidate_id


def test_candidate_changes_for_one_snapshot_but_not_physical_placement():
    root = _binding("root")
    security = _binding("security")
    first = _snapshot(root, "a" * 64)
    second = _snapshot(root, "b" * 64)
    sec_snap = _snapshot(security, "c" * 64)
    assert _candidate((first,)).candidate_id != _candidate((second,)).candidate_id
    assert (
        _candidate((first, sec_snap)).candidate_id
        == _candidate((sec_snap, first)).candidate_id
    )


def test_snapshot_and_candidate_unknown_versions_fail_closed():
    snapshot = _snapshot(_binding("root"), "a" * 64)
    candidate = _candidate((snapshot,))
    with pytest.raises(MultiSourceIdentityError, match="resolver identity"):
        _candidate((snapshot,), resolver_identity="resolver2:unknown")
    with pytest.raises(MultiSourceIdentityError, match="snapshot identity"):
        SourceSnapshot(
            snapshot_id="snap2:" + "0" * 64,
            binding=snapshot.binding,
            manifest_entries=snapshot.manifest_entries,
            manifest_digest=snapshot.manifest_digest,
            git_commit=snapshot.git_commit,
            git_tree=snapshot.git_tree,
            ignore_policy_id=snapshot.ignore_policy_id,
            metadata_identity=snapshot.metadata_identity,
        )
    with pytest.raises(MultiSourceIdentityError, match="snapshot identity"):
        replace(snapshot, snapshot_id="snap1:" + "0" * 64)
    with pytest.raises(MultiSourceIdentityError, match="candidate identity"):
        replace(candidate, candidate_id="cand1:" + "0" * 64)


def test_multi_source_generations_and_semantic_identities_independently_asserted():
    b1 = _binding("root")
    snap1 = _snapshot(b1, "a" * 64)
    b2 = _binding("security", role="security", input_name="sec")
    snap2 = _snapshot(b2, "b" * 64)

    # Independent source generation assertion
    source_gen = _multi_source_source_generation((snap2, snap1))
    assert source_gen.startswith("sg1:") and len(source_gen) == 68
    assert source_gen == _multi_source_source_generation((snap1, snap2))

    with pytest.raises(MultiSourceCaptureError, match="unsupported"):
        _multi_source_source_generation(())
    other_binding = replace(
        b1, graph_id="other-graph", binding_id=graph_source_binding_id("other-graph", b1.alias)
    )
    other_snap = _snapshot(other_binding, "a" * 64)
    with pytest.raises(MultiSourceCaptureError, match="invalid"):
        _multi_source_source_generation((snap1, other_snap))

    # Independent config generation and semantic identities
    ops_b1 = OpsGraphSourceBindingConfig(
        schema_version=1, binding_id=b1.binding_id,
        source_definition_id=b1.source_definition.source_definition_id,
        alias=b1.alias, revision=b1.revision, source_kind=b1.source_definition.kind,
        root_path="/repo/root", root_path_expanded="/repo/root", repository_name="fixture",
        logical_root=".", privacy=b1.privacy_policy, evidence_retention="inherit",
        extractor_profile="default", include_paths=(), exclude_paths=(),
        selection_policy_id=b1.selection_policy_id, resolution_policy=b1.resolution_policy,
        enabled=True, role=b1.role, input_name=b1.input_name,
    )
    ops_b2 = replace(
        ops_b1, binding_id=b2.binding_id, alias=b2.alias, role=b2.role, input_name=b2.input_name
    )
    graph = OpsGraphConfig(
        id="fixture-graph", name="Fixture", root_path="", root_path_expanded="",
        repository_name="fixture", privacy="public-dev", enabled=True, mcp_visible=False,
        extractor_profile="", refresh_policy="manual", source_bindings=(ops_b1, ops_b2),
        explicit_source_bindings=True,
    )
    cfg_gen = multi_source_config_generation(graph)
    assert cfg_gen.startswith("cg1:") and len(cfg_gen) == 68

    # Path independence
    relocated = replace(
        graph,
        source_bindings=(replace(ops_b1, root_path="/other", root_path_expanded="/other"), ops_b2),
    )
    assert multi_source_config_generation(relocated) == cfg_gen

    # Sensitivity to role and input_name
    assert multi_source_config_generation(
        replace(graph, source_bindings=(replace(ops_b1, role="other_role"), ops_b2))
    ) != cfg_gen
    assert multi_source_config_generation(
        replace(graph, source_bindings=(replace(ops_b1, input_name="other_input"), ops_b2))
    ) != cfg_gen

    # Semantic identities tuple
    identities = multi_source_semantic_identities(graph)
    assert identities == (
        "cap1:python-static-v1",
        identities[1],
        "canon1:graph-key-v1-binding-path",
        "semantic1:multi-source-v1",
        "quality1:default",
    )
    assert identities[1].startswith("resolver1:nix-static-v2-")
