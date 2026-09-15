"""Hosted pipeline owners for the inactive portable-worker seam.

These executable tests cross the real managed-process and filesystem-store
boundaries. TEST-ISO2 keeps them unselected locally; STR-PUB5 must add separate
PostgreSQL ingestion and assembled-product route owners when that route exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repomap_kg.artifacts.parity_harness import compare_incumbent_and_subprocess_parity
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_test_support.portable_worker_conformance import (
    run_portable_worker_conformance,
)


def _binding(root: Path, alias: str) -> OpsGraphSourceBindingConfig:
    return OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id("pipeline-fixture", alias),
        source_definition_id=f"src1:{alias}",
        alias=alias,
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(root),
        root_path_expanded=str(root),
        repository_name=f"fixture-{alias}",
        logical_root=".",
        privacy="public-dev",
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=(),
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared",
        enabled=True,
        role="entry" if alias == "entry" else "module",
        input_name=None if alias == "entry" else alias,
    )


def _graph(*bindings: OpsGraphSourceBindingConfig) -> OpsGraphConfig:
    return OpsGraphConfig(
        id="pipeline-fixture",
        name="Pipeline fixture",
        root_path="",
        root_path_expanded="",
        repository_name="multi-source",
        privacy="public-dev",
        enabled=True,
        mcp_visible=False,
        extractor_profile="",
        refresh_policy="manual",
        source_bindings=tuple(bindings),
        explicit_source_bindings=True,
    )


def _one_source(tmp_path: Path, name: str = "run"):
    source = tmp_path / name / "source"
    source.mkdir(parents=True)
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    return compare_incumbent_and_subprocess_parity(
        _graph(_binding(source, "entry")),
        store_root=tmp_path / name / "store",
        workspace_root=tmp_path / name / "workspace",
    )


@pytest.mark.int
def test_pipeline_observed_launch_and_current_stage_contract_negotiation(tmp_path) -> None:
    result = _one_source(tmp_path)
    assert result.process_count == 1
    assert result.row_stage_contract == "stage-unassigned-v1"
    assert result.bundle_validated
    assert result.publication_state == "not_started"


@pytest.mark.int
@pytest.mark.parametrize(
    "probe",
    (
        "read", "write", "caller-source-read", "listdir", "scandir",
        "mkdir", "remove", "rmdir", "rename", "replace", "chmod", "link",
        "symlink", "socket", "connect", "bind-listen", "dns",
        "subprocess", "exec", "spawn", "system", "fork", "forkpty",
        "database-import", "publisher-import", "control-import",
    ),
)
def test_pipeline_actual_operation_is_denied_by_installed_worker_guard(
    tmp_path, probe
) -> None:
    root = tmp_path / probe
    root.mkdir()
    outside = root / "outside"
    outside.mkdir()
    (outside / "file").write_bytes(b"sentinel")
    original_mode = (outside / "file").stat().st_mode
    (outside / "destination").write_bytes(b"destination")
    (outside / "empty").mkdir()
    result, _store = run_portable_worker_conformance(
        root,
        f"authority:{probe}",
        probe_path=(
            root / "source" / "main.py"
            if probe == "caller-source-read"
            else outside / "file"
            if probe in {"read", "write"}
            else outside
        ),
    )
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == "unsupported_capability"
    assert result.terminal["publication_state"] == "not_started"
    assert result.process_group_cleaned
    assert (outside / "file").read_bytes() == b"sentinel"
    assert (outside / "file").stat().st_mode == original_mode
    assert (outside / "destination").read_bytes() == b"destination"
    assert (outside / "empty").is_dir()


@pytest.mark.int
@pytest.mark.parametrize(
    "category",
    (
        "artifact_missing", "artifact_stale", "artifact_corrupt",
        "artifact_bounds", "manifest_bounds", "source_unavailable",
        "source_changed", "source_invalid", "source_capture",
        "unsupported_contract", "unsupported_capability",
        "contract_validation", "malformed_protocol", "identity_mismatch",
        "semantic_workload",
    ),
)
def test_pipeline_conformance_injected_typed_failure_terminal_matrix(
    tmp_path, category
) -> None:
    root = tmp_path / category
    root.mkdir()
    result, _store = run_portable_worker_conformance(
        root,
        f"failure:{category}",
    )
    assert result.terminal["message_type"] == "error"
    assert result.terminal["status"] == "failed"
    assert result.terminal["error_category"] == category
    assert result.terminal["portable_snapshot"]["outcome"] == category
    assert result.terminal["portable_snapshot"]["bundle"] is None
    assert result.terminal["publication_state"] == "not_started"
    assert result.process_group_cleaned


@pytest.mark.int
@pytest.mark.parametrize(
    "diagnostic",
    ("store_unavailable", "permission_denied", "receipt_bounds", "write_failed"),
)
def test_pipeline_typed_receipt_write_failure_uses_real_receipt_path(
    tmp_path, diagnostic
) -> None:
    root = tmp_path / diagnostic
    root.mkdir()
    result, _store = run_portable_worker_conformance(
        root,
        f"receipt:{diagnostic}",
    )
    extension = result.terminal["portable_snapshot"]
    assert result.terminal["status"] == "failed"
    assert extension["receipt"] is None
    assert extension["receipt_status"] == "unavailable"
    assert extension["receipt_diagnostic"] == diagnostic
    assert result.process_group_cleaned


@pytest.mark.int
@pytest.mark.parametrize(
    "checkpoint",
    (
        "before_manifest", "during_materialization", "before_semantic",
        "during_semantic", "after_bundle", "before_terminal",
    ),
)
def test_pipeline_real_worker_internal_cancellation_matrix(
    tmp_path, checkpoint
) -> None:
    root = tmp_path / checkpoint
    root.mkdir()
    result, _store = run_portable_worker_conformance(
        root,
        f"cancel:{checkpoint}",
    )
    assert result.terminal["message_type"] == "result"
    assert result.terminal["status"] == "cancelled"
    assert result.terminal["portable_snapshot"]["outcome"] == "cancelled"
    assert result.terminal["portable_snapshot"]["bundle"] is None
    assert result.process_group_cleaned


@pytest.mark.int
def test_pipeline_parent_reclaims_materialization_after_abrupt_child_exit(tmp_path) -> None:
    result, _store = run_portable_worker_conformance(
        tmp_path, "crash:after-materialization"
    )
    assert result.synthesized_terminal
    assert result.terminal["message_type"] == "worker_exit"
    assert result.returncode == 17
    assert result.waited
    assert result.process_group_cleaned
    assert list((tmp_path / "workspace").iterdir()) == []


@pytest.mark.int
def test_pipeline_deterministic_filesystem_store_candidate_evidence(tmp_path) -> None:
    first = _one_source(tmp_path, "first")
    second = _one_source(tmp_path, "second")
    assert first.bundle_bytes_digest == second.bundle_bytes_digest
    assert first.receipt_bytes_digest == second.receipt_bytes_digest


@pytest.mark.int
def test_pipeline_one_source_and_multi_source_parity_against_incumbent(tmp_path) -> None:
    assert _one_source(tmp_path, "single").equal
    entry = tmp_path / "multi" / "entry"
    module = tmp_path / "multi" / "module"
    for root in (entry, module):
        (root / "modules").mkdir(parents=True)
        (root / "modules/default.nix").write_text("{ ... }: {}\n", encoding="utf-8")
    (entry / "flake.nix").write_text(
        "{ inputs, ... }: { imports = [ ./modules/default.nix "
        "inputs.module.nixosModules.default ]; }\n",
        encoding="utf-8",
    )
    (module / "flake.nix").write_text(
        "{ ... }: { nixosModules.default = import ./modules/default.nix; }\n",
        encoding="utf-8",
    )
    result = compare_incumbent_and_subprocess_parity(
        _graph(_binding(entry, "entry"), _binding(module, "module")),
        store_root=tmp_path / "multi" / "store",
        workspace_root=tmp_path / "multi" / "workspace",
    )
    assert result.equal
    assert result.resolution_outcomes.get("exact", 0) >= 1


@pytest.mark.int
def test_pipeline_publisher_validator_replay_and_attempt_conflict(tmp_path) -> None:
    result = _one_source(tmp_path)
    assert result.bundle_validated
    assert result.validator_idempotent
    assert result.conflicting_attempt_rejected


@pytest.mark.int
def test_pipeline_worker_cleanup_leaves_no_command_workspace_entries(tmp_path) -> None:
    result = _one_source(tmp_path)
    assert result.temporary_entries_after == 0
