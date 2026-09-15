from dataclasses import replace
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

from repomap_kg.extractors.config.nix_resolver import NixResolution, ResolutionOutcome
from repomap_kg.graph.discovery_records import FileInfo
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.graph.multi_source_capture import _capture_inventory
from repomap_kg.graph.multi_source_pipeline import (
    MultiSourceCaptureError,
    capture_multi_source_candidate,
    capture_sealed_multi_source_candidate,
    scan_multi_source_generations,
)
from repomap_kg.graph.multi_source_routing import (
    SealedSourceBinding,
    _resolved_observation,
    _validate_provenance,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig


def _binding(
    root: Path, alias: str, *, privacy: str = "public-dev",
    role: str | None = None, input_name: str | None = None,
) -> OpsGraphSourceBindingConfig:
    return OpsGraphSourceBindingConfig(
        schema_version=1, binding_id=graph_source_binding_id("fixture-graph", alias),
        source_definition_id=f"src1:{alias}", alias=alias, revision=1,
        source_kind=SourceKind.FOLDER, root_path=str(root), root_path_expanded=str(root),
        repository_name=f"fixture-{alias}", logical_root=".", privacy=privacy,
        evidence_retention="metadata-only", extractor_profile="default",
        include_paths=(), exclude_paths=(), selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared", enabled=True,
        role=role or ("entry" if alias == "entry" else "module"),
        input_name=input_name if input_name is not None else (None if alias == "entry" else alias),
    )


def _graph(*bindings: OpsGraphSourceBindingConfig, explicit: bool = True) -> OpsGraphConfig:
    return OpsGraphConfig(
        id="fixture-graph", name="Fixture", root_path="", root_path_expanded="",
        repository_name="[multi-source]",
        privacy="public-dev" if all(item.privacy == "public-dev" for item in bindings) else "private-ops",
        enabled=True, mcp_visible=True, extractor_profile="", refresh_policy="manual",
        source_bindings=tuple(bindings), explicit_source_bindings=explicit,
    )


def _write_constellation(root: Path, alias: str) -> None:
    (root / "modules").mkdir(parents=True)
    (root / "modules/default.nix").write_text("{ ... }: {}\n", encoding="utf-8")
    if alias == "entry":
        (root / "flake.nix").write_text(
            "{ inputs, ... }: { imports = [ ./modules/default.nix inputs.composition.nixosModules.default ]; }\n",
            encoding="utf-8",
        )
    else:
        (root / "flake.nix").write_text(
            "{ ... }: { nixosModules.default = import ./modules/default.nix; }\n",
            encoding="utf-8",
        )


def test_capture_is_order_independent_relocation_stable_and_binding_distinct(tmp_path):
    entry = tmp_path / "entry"
    composition = tmp_path / "composition"
    _write_constellation(entry, "entry")
    _write_constellation(composition, "composition")
    first = capture_multi_source_candidate(
        _graph(_binding(entry, "entry"), _binding(composition, "composition"))
    )
    second = capture_multi_source_candidate(
        _graph(_binding(composition, "composition"), _binding(entry, "entry"))
    )

    assert first.candidate == second.candidate
    paths = {item.path for item in first.observations if item.kind == "file"}
    assert "entry/modules/default.nix" in paths
    assert "composition/modules/default.nix" in paths
    assert any(
        item.cross_binding and item.outcome.value == "exact"
        for item in first.resolutions
    )
    rendered = str(first)
    assert str(tmp_path) not in rendered

    relocated_entry = tmp_path / "relocated-entry"
    relocated_composition = tmp_path / "relocated-composition"
    _write_constellation(relocated_entry, "entry")
    _write_constellation(relocated_composition, "composition")
    relocated = capture_multi_source_candidate(
        _graph(
            _binding(relocated_entry, "entry"),
            _binding(relocated_composition, "composition"),
        )
    )
    assert relocated.candidate == first.candidate


def test_adding_binding_does_not_rekey_existing_source_local_observations(tmp_path):
    entry = tmp_path / "entry"
    composition = tmp_path / "composition"
    unrelated = tmp_path / "unrelated"
    for root, alias in (
        (entry, "entry"),
        (composition, "composition"),
        (unrelated, "unrelated"),
    ):
        _write_constellation(root, alias)
    base = capture_multi_source_candidate(
        _graph(_binding(entry, "entry"), _binding(composition, "composition"))
    )
    expanded = capture_multi_source_candidate(
        _graph(
            _binding(entry, "entry"),
            _binding(composition, "composition"),
            _binding(unrelated, "unrelated"),
        )
    )

    base_keys = {item.source_id for item in base.observations if item.path.startswith("entry/")}
    expanded_keys = {
        item.source_id for item in expanded.observations if item.path.startswith("entry/")
    }
    assert base_keys == expanded_keys
    assert base.candidate.candidate_id != expanded.candidate.candidate_id


def test_role_and_input_mapping_are_candidate_inputs(tmp_path):
    entry = tmp_path / "entry"
    composition = tmp_path / "composition"
    _write_constellation(entry, "entry")
    _write_constellation(composition, "composition")
    entry_binding = _binding(entry, "entry")
    composition_binding = _binding(composition, "composition")
    baseline = capture_multi_source_candidate(
        _graph(entry_binding, composition_binding)
    )

    assert baseline.candidate.candidate_id != capture_multi_source_candidate(
        _graph(entry_binding, replace(composition_binding, role="security"))
    ).candidate.candidate_id
    assert baseline.candidate.candidate_id != capture_multi_source_candidate(
        _graph(entry_binding, replace(composition_binding, input_name="modules"))
    ).candidate.candidate_id


def test_disabled_or_missing_binding_fails_before_partial_candidate(tmp_path):
    entry = tmp_path / "entry"
    _write_constellation(entry, "entry")
    disabled = replace(_binding(tmp_path / "missing", "missing"), enabled=False)
    with pytest.raises(MultiSourceCaptureError, match="binding inventory"):
        capture_multi_source_candidate(_graph(_binding(entry, "entry"), disabled))


def test_unsupported_source_kind_fails_before_partial_candidate(tmp_path):
    entry = tmp_path / "entry"
    _write_constellation(entry, "entry")
    unsupported = replace(_binding(entry, "entry"), source_kind=SourceKind.ARCHIVE)
    with pytest.raises(MultiSourceCaptureError, match="binding inventory"):
        capture_multi_source_candidate(_graph(unsupported))


def test_changed_during_capture_fails_without_candidate(tmp_path):
    entry = tmp_path / "entry"
    _write_constellation(entry, "entry")
    from repomap_kg.graph import multi_source_pipeline as pipeline

    real_extract = pipeline.extract_observations_from_repository_files

    def mutate_after_extract(root, files, **kwargs):
        observations = real_extract(root, files, **kwargs)
        entry.joinpath("flake.nix").write_text(
            "{ changed = true; }\n", encoding="utf-8"
        )
        return observations

    with (
        patch.object(
            pipeline,
            "extract_observations_from_repository_files",
            side_effect=mutate_after_extract,
        ),
        pytest.raises(MultiSourceCaptureError, match="changed during capture"),
    ):
        capture_multi_source_candidate(_graph(_binding(entry, "entry")))


def test_later_binding_extraction_rechecks_the_complete_inventory(tmp_path):
    """A mutation to an earlier binding invalidates a later-bound candidate."""

    first = tmp_path / "first"
    later = tmp_path / "later"
    _write_constellation(first, "first")
    _write_constellation(later, "later")
    from repomap_kg.graph import multi_source_pipeline as pipeline

    real_extract = pipeline.extract_observations_from_repository_files

    def mutate_first_after_later_extract(root, files, **kwargs):
        observations = real_extract(root, files, **kwargs)
        if Path(root).name == "later":
            (first / "flake.nix").write_text(
                "{ changed_during_later_extraction = true; }: {}\n",
                encoding="utf-8",
            )
        return observations

    with (
        patch.object(
            pipeline,
            "extract_observations_from_repository_files",
            side_effect=mutate_first_after_later_extract,
        ),
        pytest.raises(MultiSourceCaptureError, match="changed during capture") as raised,
    ):
        capture_multi_source_candidate(
            _graph(_binding(first, "first"), _binding(later, "later"))
        )

    assert getattr(raised.value, "category", None) == "source_changed"


def test_resolver_failure_produces_no_partial_candidate(tmp_path):
    entry = tmp_path / "entry"
    _write_constellation(entry, "entry")
    from repomap_kg.graph import multi_source_pipeline as pipeline

    with (
        patch.object(
            pipeline,
            "resolve_nix_relations",
            side_effect=ValueError("synthetic resolver failure"),
        ),
        pytest.raises(MultiSourceCaptureError, match="relation resolution failed"),
    ):
        capture_multi_source_candidate(_graph(_binding(entry, "entry")))


def test_mixed_privacy_is_conservative_and_diagnostics_are_path_free(tmp_path):
    entry = tmp_path / "entry"
    private = tmp_path / "private"
    _write_constellation(entry, "entry")
    _write_constellation(private, "private")
    bundle = capture_multi_source_candidate(
        _graph(
            _binding(entry, "entry"),
            _binding(private, "private", privacy="private-config"),
        )
    )

    assert bundle.privacy == "private-ops"
    assert all(str(tmp_path) not in str(item.metadata) for item in bundle.observations)


def test_public_safe_four_binding_fixture_covers_resolution_outcomes(tmp_path):
    fixture = Path("src/test/fixtures/multi_source_nix_constellation")
    roots = {}
    for alias in ("entry", "composition", "security", "developer"):
        roots[alias] = tmp_path / alias
        shutil.copytree(fixture / alias, roots[alias])
    bindings = [
        _binding(roots["entry"], "entry"),
        _binding(roots["composition"], "composition"),
        replace(
            _binding(roots["security"], "security", privacy="private-config"),
            input_name="shared",
            role="security",
        ),
        replace(
            _binding(roots["developer"], "developer"),
            input_name="shared",
            role="developer",
        ),
    ]

    bundle = capture_multi_source_candidate(_graph(*bindings))

    outcomes = {item.outcome.value for item in bundle.resolutions}
    assert {"exact", "ambiguous", "evaluation-dependent"} <= outcomes
    assert bundle.privacy == "private-ops"
    observed_vector = {
        (
            observation.metadata["binding_id"],
            next(
                snapshot.binding.revision
                for snapshot in bundle.candidate.snapshots
                if snapshot.binding.binding_id == observation.metadata["binding_id"]
            ),
            observation.metadata["snapshot_id"],
        )
        for observation in bundle.observations
    }
    assert observed_vector == set(bundle.candidate.snapshot_vector)
    from repomap_kg.canonicalization.main import canonicalize_observations
    canon_result = canonicalize_observations(bundle.observations)
    assert not any(
        diag.category == "unsupported_raw_observation_kind"
        for diag in canon_result.diagnostics
    )


def test_sealed_multi_source_candidate_and_scan_generations(tmp_path):
    entry = tmp_path / "entry"
    _write_constellation(entry, "entry")
    b = _binding(entry, "entry")
    graph = _graph(b)

    scan = scan_multi_source_generations(graph)
    assert scan.source_generation.startswith("sg1:") and scan.config_generation.startswith("cg1:")
    assert len(scan.snapshots) == 1 and len(scan.files) == 2
    assert scan_multi_source_generations(_graph(b, explicit=False)).source_generation == scan.source_generation

    sealed = SealedSourceBinding(
        binding_id=b.binding_id, source_definition_id=b.source_definition_id,
        alias=b.alias, revision=b.revision, source_kind=b.source_kind,
        root=entry, repository_scope=b.repository_name, logical_root=b.logical_root,
        privacy=b.privacy, evidence_retention=b.evidence_retention,
        extractor_profile=b.extractor_profile, selection_policy_id=b.selection_policy_id,
        resolution_policy=b.resolution_policy, role=b.role, input_name=b.input_name,
    )
    expected_vec = [(b.binding_id, 1, scan.snapshots[0].snapshot_id)]
    bundle = capture_sealed_multi_source_candidate(
        "fixture-graph", (sealed,), expected_snapshot_vector=expected_vec
    )
    assert bundle.candidate.snapshot_vector == tuple(expected_vec)

    with pytest.raises(MultiSourceCaptureError, match="sealed source inventory is invalid") as exc_info:
        capture_sealed_multi_source_candidate("fixture-graph", (), expected_snapshot_vector=())
    assert exc_info.value.category == "contract_validation"

    other_sealed = replace(sealed, binding_id="bind1:other", alias="other", repository_scope="repo2")
    with pytest.raises(MultiSourceCaptureError, match="sealed source inventory is invalid"):
        capture_sealed_multi_source_candidate("fixture-graph", (sealed, other_sealed), expected_snapshot_vector=())

    with pytest.raises(MultiSourceCaptureError, match="sealed source inventory disagrees with manifest") as exc_info:
        capture_sealed_multi_source_candidate(
            "fixture-graph", (sealed,), expected_snapshot_vector=[("bind1:wrong", 1, "snap1:fake")]
        )
    assert exc_info.value.category == "source_changed"


def test_routing_provenance_and_dynamic_resolution(tmp_path):
    entry = tmp_path / "entry"
    _write_constellation(entry, "entry")
    captured = _capture_inventory(_graph(_binding(entry, "entry")))
    base_obs = FileInfo("modules/default.nix", "nix", "source", "h1", False, False).to_observation()
    obs = replace(
        base_obs,
        source_id=f"{captured[0].config.binding_id}:file:modules/default.nix",
        path="entry/modules/default.nix", name="entry/modules/default.nix",
        metadata={
            "graph_id": "fixture-graph", "binding_id": captured[0].config.binding_id,
            "binding_alias": "entry", "binding_role": "entry", "binding_revision": 1,
            "snapshot_id": captured[0].snapshot.snapshot_id,
            "snapshot_manifest_digest": captured[0].snapshot.manifest_digest,
            "source_relative_path": "modules/default.nix", "candidate_id": "cand1:test",
        },
    )
    _validate_provenance([obs], captured, candidate_id="cand1:test")

    with pytest.raises(MultiSourceCaptureError, match="provenance is invalid"):
        _validate_provenance([obs], captured, candidate_id="cand1:wrong")

    for outcome, expected_kind, expected_target in (
        (ResolutionOutcome.EVALUATION_DEPENDENT, "nix.import", "dynamic:file:nix-cross-source-evaluation-dependent"),
        (ResolutionOutcome.UNSUPPORTED, "nix.import", "unknown:file:nix-cross-source-unsupported"),
    ):
        res = NixResolution(
            observation=obs, outcome=outcome,
            cross_binding=True, source_binding="entry", target_binding="composition",
            target_path=None,
        )
        resolved = _resolved_observation(res, candidate_id="cand1:test")
        assert resolved.kind == expected_kind and resolved.target == expected_target
