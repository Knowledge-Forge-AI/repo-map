from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from repomap_kg.artifacts._parity_sealing import (
    _harness_owned_source_graph,
    _seal_graph,
)
from repomap_kg.artifacts.parity_harness import (
    compare_incumbent_and_portable_parity,
    compare_incumbent_and_subprocess_parity,
)
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig


def binding(root: Path, alias: str) -> OpsGraphSourceBindingConfig:
    return OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id("fixture-graph", alias),
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


def graph(*bindings: OpsGraphSourceBindingConfig) -> OpsGraphConfig:
    return OpsGraphConfig(
        id="fixture-graph",
        name="Fixture",
        root_path="",
        root_path_expanded="",
        repository_name="multi-source",
        privacy="public-dev",
        enabled=True,
        mcp_visible=True,
        extractor_profile="",
        refresh_policy="manual",
        source_bindings=tuple(bindings),
        explicit_source_bindings=True,
    )


def test_real_one_source_python_semantics_have_exact_sealed_worker_parity(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    source_file = source / "main.py"
    source_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    sentinel = source / ".identity-sentinel"
    sentinel.write_bytes(b"caller-owned")
    source_file.chmod(0o640)
    before = (
        source.stat().st_ino,
        source_file.read_bytes(),
        source_file.stat().st_mode,
        sentinel.read_bytes(),
    )
    original_rename = Path.rename

    def reject_caller_root_rename(path, target):
        if path == source:
            raise AssertionError("parity harness renamed a caller-owned source root")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", reject_caller_root_rename)

    result = compare_incumbent_and_subprocess_parity(
        graph(binding(source, "entry")),
        store_root=tmp_path / "store",
        workspace_root=tmp_path / "workspace",
    )

    assert result.equal
    assert set(result.family_counts) == {
        "files",
        "raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "canonical_evidence",
        "canonical_node_evidence",
        "canonical_edge_evidence",
    }
    assert result.materialized_bytes == result.artifact_bytes
    assert result.worker_source_copies_unavailable
    assert result.bundle_validated
    assert result.validator_idempotent
    assert result.conflicting_attempt_rejected
    assert result.publication_state == "not_started"
    assert result.temporary_entries_after == 0
    assert result.caller_roots_unchanged
    assert result.process_count == 1
    assert result.row_stage_contract == "stage-unassigned-v1"
    assert (
        source.stat().st_ino,
        source_file.read_bytes(),
        source_file.stat().st_mode,
        sentinel.read_bytes(),
    ) == before
    assert not (tmp_path / ".workspace-sources").exists()


def test_real_multi_source_nix_semantics_preserve_duplicate_paths_and_resolution(tmp_path) -> None:
    entry = tmp_path / "entry"
    module = tmp_path / "module"
    for root in (entry, module):
        (root / "modules").mkdir(parents=True)
        (root / "modules/default.nix").write_text("{ ... }: {}\n", encoding="utf-8")
    (entry / "flake.nix").write_text(
        "{ inputs, ... }: { imports = [ ./modules/default.nix inputs.module.nixosModules.default ]; }\n",
        encoding="utf-8",
    )
    (module / "flake.nix").write_text(
        "{ ... }: { nixosModules.default = import ./modules/default.nix; }\n",
        encoding="utf-8",
    )

    result = compare_incumbent_and_subprocess_parity(
        graph(binding(entry, "entry"), binding(module, "module")),
        store_root=tmp_path / "store",
        workspace_root=tmp_path / "workspace",
    )

    assert result.equal
    assert result.binding_count == 2
    assert result.resolution_outcomes.get("exact", 0) >= 1


def test_subprocess_bundle_and_receipt_bytes_are_relocation_invariant(tmp_path) -> None:
    results = []
    for name in ("first", "second"):
        source = tmp_path / name / "source"
        source.mkdir(parents=True)
        (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
        results.append(
            compare_incumbent_and_subprocess_parity(
                graph(binding(source, "entry")),
                store_root=tmp_path / name / "store",
                workspace_root=tmp_path / name / "workspace",
            )
        )

    first, second = results
    assert first.bundle_id == second.bundle_id
    assert first.receipt_id == second.receipt_id
    assert first.bundle_bytes_digest == second.bundle_bytes_digest
    assert first.receipt_bytes_digest == second.receipt_bytes_digest


def test_compare_incumbent_and_portable_parity_alias(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = compare_incumbent_and_portable_parity(
        graph(binding(source, "entry")),
        store_root=tmp_path / "store",
        workspace_root=tmp_path / "workspace",
    )
    assert result.equal


def test_harness_owned_source_graph_rejects_existing_root(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    owned_root = tmp_path / "existing-root"
    owned_root.mkdir()
    g = graph(binding(source, "entry"))

    with pytest.raises(ValueError, match="parity harness source-copy root already exists"):
        with _harness_owned_source_graph(g, owned_root):
            pass


def test_harness_owned_source_graph_cleans_up_on_exit(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    owned_root = tmp_path / "copy-root"
    g = graph(binding(source, "entry"))
    with _harness_owned_source_graph(g, owned_root) as (sealed_graph, sealed_roots):
        assert owned_root.exists()
        assert len(sealed_roots) == 1
    assert not owned_root.exists()


def test_seal_graph_detects_tampered_source(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    g = graph(binding(source, "entry"))
    incumbent = capture_multi_source_candidate(g)
    store = FileSystemArtifactStore(tmp_path / "store")

    orig_read_bytes = Path.read_bytes

    def tampered_read(self):
        if self.name == "main.py":
            return b"TAMPERED_BYTES"
        return orig_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", tampered_read)

    with pytest.raises(ValueError, match="source changed while sealing parity fixture"):
        _seal_graph(g, incumbent, store)


def test_compare_incumbent_and_subprocess_parity_detects_worker_failure(tmp_path, monkeypatch) -> None:
    import repomap_kg.artifacts.parity_harness as harness_mod

    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")

    def mock_run(*args, **kwargs):
        return SimpleNamespace(
            protocol_error="crashed",
            terminal={"status": "failed"},
            managed_process_launches=((),),
        )

    monkeypatch.setattr(harness_mod, "run_portable_worker", mock_run)

    with pytest.raises(ValueError, match="portable subprocess did not produce a valid success terminal"):
        compare_incumbent_and_subprocess_parity(
            graph(binding(source, "entry")),
            store_root=tmp_path / "store",
            workspace_root=tmp_path / "workspace",
        )


def test_compare_incumbent_and_subprocess_parity_detects_missing_extension(tmp_path, monkeypatch) -> None:
    import repomap_kg.artifacts.parity_harness as harness_mod

    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")

    def mock_run(*args, **kwargs):
        return SimpleNamespace(
            protocol_error=None,
            terminal={"status": "succeeded"},
            managed_process_launches=((),),
        )

    monkeypatch.setattr(harness_mod, "run_portable_worker", mock_run)

    with pytest.raises(ValueError, match="portable subprocess result extension is absent"):
        compare_incumbent_and_subprocess_parity(
            graph(binding(source, "entry")),
            store_root=tmp_path / "store",
            workspace_root=tmp_path / "workspace",
        )


@pytest.mark.parametrize("existing_capability", [False, True])
def test_capability_acquisition_preserves_directory_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_capability: bool,
) -> None:
    import repomap_kg.artifacts.parity_harness as harness

    source = tmp_path / "source"
    source.mkdir()
    source_file = source / "main.py"
    source_file.write_bytes(b"VALUE = 1\n")
    source_file.chmod(0o640)
    before = (source.stat().st_ino, source_file.read_bytes(), source_file.stat().st_mode)
    capability_root = tmp_path / ".workspace-capability"
    sentinel = capability_root / "sentinel"
    failure = OSError("injected capability write failure")
    if existing_capability:
        capability_root.mkdir()
        sentinel.write_bytes(b"pre-existing owner")

    def fail_creation(root, capability):
        assert root == capability_root
        (root / "partial-capability").write_bytes(b"partial")
        raise failure

    monkeypatch.setattr(harness, "create_portable_capability", fail_creation)
    with pytest.raises(OSError) as caught:
        compare_incumbent_and_subprocess_parity(
            graph(binding(source, "entry")),
            store_root=tmp_path / "store",
            workspace_root=tmp_path / "workspace",
        )
    if existing_capability:
        assert isinstance(caught.value, FileExistsError)
        assert sentinel.read_bytes() == b"pre-existing owner"
        assert list(capability_root.iterdir()) == [sentinel]
    else:
        assert caught.value is failure
        assert not capability_root.exists()
    assert (source.stat().st_ino, source_file.read_bytes(), source_file.stat().st_mode) == before
    assert not (tmp_path / ".workspace-sources").exists()
    assert (tmp_path / "workspace").is_dir()
    assert (tmp_path / "store").is_dir()


def test_partial_source_copy_failure_cleans_owned_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import repomap_kg.artifacts._parity_sealing as sealing

    roots = (tmp_path / "entry", tmp_path / "module")
    for root in roots:
        root.mkdir()
        (root / "main.py").write_bytes(b"VALUE = 1\n")
    configured = graph(*(binding(root, alias) for root, alias in zip(roots, ("entry", "module"))))
    before = sealing._source_signature(configured)
    owned_root = tmp_path / "owned-copies"
    copytree = sealing.shutil.copytree
    failure = OSError("injected second copy failure")

    def partial_copy(source, destination, **kwargs):
        if source == roots[1]:
            destination.mkdir()
            (destination / "partial").write_bytes(b"partial")
            raise failure
        return copytree(source, destination, **kwargs)

    monkeypatch.setattr(sealing.shutil, "copytree", partial_copy)
    with pytest.raises(OSError) as caught:
        with _harness_owned_source_graph(configured, owned_root):
            pytest.fail("partial source graph escaped acquisition")
    assert caught.value is failure
    assert not owned_root.exists()
    assert sealing._source_signature(configured) == before


def test_stage_family_iteration_failure_closes_prepared_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import repomap_kg.artifacts.parity_harness as harness

    failure = OSError("injected staged row read failure")
    closed = []

    def failing_rows():
        yield {"path": "main.py"}
        raise failure

    prepared = SimpleNamespace(family_rows={"files": failing_rows()}, close=lambda: closed.append(True))
    monkeypatch.setattr(harness, "build_staged_rows", lambda *args, **kwargs: prepared)
    with pytest.raises(OSError) as caught:
        harness._stage_families((), "fixture", "stage-unassigned")
    assert caught.value is failure
    assert closed == [True]
