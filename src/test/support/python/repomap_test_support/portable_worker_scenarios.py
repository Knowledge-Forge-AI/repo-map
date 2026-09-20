"""Deterministic worker scenarios and lifecycle assertions for portable coordinators."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest import TestCase

from repomap_kg.artifacts.references import ArtifactLocator, ArtifactReference
from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator._portable_capability import (
    PortableExecutionCapability,
    create_portable_capability,
)
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.coordinator._protocol_core import ProtocolError
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


def coordinator_test_limits() -> SimpleNamespace:
    """Return validated deterministic limits for coordinator worker tests."""
    return SimpleNamespace(
        process_deadline_seconds=10.0,
        heartbeat_seconds=2.0,
        hello_deadline_seconds=2.0,
        cancellation_after_seconds=1.0,
        cancel_deadline_seconds=1.0,
        process_termination_grace_seconds=1.0,
        max_diagnostic_bytes=4096,
        max_protocol_line_bytes=65536,
        max_array_items=64,
    )


def make_missing_manifest_reference(
    *,
    digest: str | None = None,
    size_bytes: int = 512,
    store_version: str = "store-v1",
) -> ArtifactReference:
    """Build an explicit, six-field ArtifactReference pointing to a non-existent artifact."""
    d = digest or ("sha256:" + "0" * 64)
    digest_hex = d.removeprefix("sha256:")
    return ArtifactReference(
        d,
        size_bytes,
        "application/x-repomap-snapshot-manifest-v1+json",
        "canonical-json-v1",
        PrivacyClassification.RAW_SOURCE,
        ArtifactLocator("filesystem", f"objects/{digest_hex}", store_version),
    )


def create_test_sealed_capability(
    root: Path,
    store: FileSystemArtifactStore,
    workspace: Path,
    *,
    graph_id: str = "multi-graph",
    job_id: str = "job-sup-coord",
    attempt: int = 1,
) -> PortableExecutionCapability:
    """Build an admitted, runnable PortableExecutionCapability with a sealed manifest."""
    src = root / f"sup_seed_src_{job_id}"
    src.mkdir(parents=True, exist_ok=True)
    (src / "README.md").write_text("# Test Seed\n", encoding="utf-8")
    binding = OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id(graph_id, "primary"),
        source_definition_id=f"src1:{graph_id}-primary",
        alias="primary",
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(src),
        root_path_expanded=str(src),
        repository_name=f"repo-{graph_id}",
        logical_root=".",
        privacy="public-dev",
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=(),
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared",
        enabled=True,
        role="entry",
        input_name=None,
    )
    config = OpsGraphConfig(
        id=graph_id,
        name=f"Graph {graph_id}",
        root_path="",
        root_path_expanded="",
        repository_name=f"repo-{graph_id}",
        privacy="public-dev",
        enabled=True,
        mcp_visible=True,
        extractor_profile="default",
        refresh_policy="manual",
        source_bindings=(binding,),
        explicit_source_bindings=True,
    )
    manifest, reference, _ = seal_configured_sources(
        config,
        store,
        extractor_generation="eg1:1",
        canonicalizer_generation="kg1:1",
    )
    return PortableExecutionCapability(
        schema_version=1,
        job_id=job_id,
        attempt=attempt,
        graph_id=graph_id,
        store_root=store.root,
        workspace_root=workspace,
        manifest_reference=reference,
        source_generation=manifest.source_generation,
        config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
        max_artifact_bytes=10 * 1024 * 1024,
        max_bundle_bytes=10 * 1024 * 1024,
    )


def assert_supervised_run_portable_worker_lifecycle(
    test_case: TestCase,
    private_dir: Path,
    cap: PortableExecutionCapability,
    *,
    include_success: bool = True,
) -> None:
    """Exercise and assert coordinator parent validation, refusals, cancellation, and execution.

    Preconditions:
    - ``cap`` must possess an admitted, valid sealed manifest within ``cap.store_root``.
    - ``private_dir`` must be an owner-private temporary directory.
    """
    limits = coordinator_test_limits()

    # 1. Configured coordinator parent validation rejects mismatched identity
    mismatched_cap_path = create_portable_capability(
        private_dir, replace(cap, job_id="job-mismatch-id")
    )
    with test_case.assertRaises(ProtocolError) as cm_id:
        run_portable_worker(
            mismatched_cap_path,
            {"job_id": "wrong-coordinator-job", "attempt": cap.attempt},
            limits,
        )
    test_case.assertEqual(cm_id.exception.code, "identity_mismatch")
    test_case.assertEqual(str(cm_id.exception), "protocol_error:identity_mismatch")
    test_case.assertFalse(mismatched_cap_path.exists())

    # 2. Independent refusal on missing capability file
    missing_cap_path = private_dir / "nonexistent-capability-file.json"
    with test_case.assertRaises(ValueError):
        run_portable_worker(
            missing_cap_path,
            {"job_id": cap.job_id, "attempt": cap.attempt},
            limits,
        )

    # 3. Independent pre-set cancellation cleans up and records normal cancellation terminal
    cancel_cap_path = create_portable_capability(
        private_dir, replace(cap, job_id="job-cancel-test")
    )
    cancel_ev = threading.Event()
    cancel_ev.set()
    cancel_result = run_portable_worker(
        cancel_cap_path,
        {"job_id": "job-cancel-test", "attempt": cap.attempt},
        limits,
        cancel_event=cancel_ev,
    )
    test_case.assertEqual(cancel_result.terminal.get("status"), "cancelled")
    test_case.assertIsNone(cancel_result.terminal.get("error_category"))
    cancel_snapshot = cancel_result.terminal.get("portable_snapshot")
    assert isinstance(cancel_snapshot, dict)
    test_case.assertEqual(
        cancel_snapshot.get("outcome"),
        "cancelled",
    )
    test_case.assertFalse(cancel_cap_path.exists())

    # 4. Independent missing artifact capability cleanly fails with exact artifact_missing
    missing_ref = make_missing_manifest_reference()
    missing_art_cap = replace(
        cap, manifest_reference=missing_ref, job_id="job-missing-art"
    )
    missing_art_path = create_portable_capability(private_dir, missing_art_cap)
    art_result = run_portable_worker(
        missing_art_path,
        {"job_id": "job-missing-art", "attempt": cap.attempt},
        limits,
    )
    test_case.assertEqual(art_result.terminal.get("status"), "failed")
    test_case.assertEqual(art_result.terminal.get("error_category"), "artifact_missing")
    art_snapshot = art_result.terminal.get("portable_snapshot")
    assert isinstance(art_snapshot, dict)
    test_case.assertEqual(
        art_snapshot.get("outcome"),
        "artifact_missing",
    )
    test_case.assertFalse(missing_art_path.exists())

    # 5. Supervised successful worker execution when full valid preconditions are present
    if include_success:
        success_cap_path = create_portable_capability(
            private_dir, replace(cap, job_id="job-success-test")
        )
        success_result = run_portable_worker(
            success_cap_path,
            {"job_id": "job-success-test", "attempt": cap.attempt},
            limits,
        )
        test_case.assertEqual(success_result.terminal.get("status"), "succeeded")
        test_case.assertIsNone(success_result.terminal.get("error_category"))
        success_snapshot = success_result.terminal.get("portable_snapshot")
        assert isinstance(success_snapshot, dict)
        test_case.assertEqual(
            success_snapshot.get("outcome"),
            "completed",
        )
        test_case.assertFalse(success_cap_path.exists())


__all__ = [
    "assert_supervised_run_portable_worker_lifecycle",
    "coordinator_test_limits",
    "create_test_sealed_capability",
    "make_missing_manifest_reference",
]


# Explicit thematic corpora bound family-frame size without changing product limits.
# Dependencies are generated only inside the disposable scenario source workspace.
PORTABLE_SUCCESS_CORPORA = (
    ("core", (
        "powershell/Advanced.Module.psd1", "powershell/Example.Module.psd1",
        "powershell/Example.Module.psm1", "powershell/basic-script.ps1",
        "shell/awk/basic.awk", "shell/awk/includes-and-extensions.awk",
        "shell/bash/basic.bash", "shell/bats/basic.bats", "shell/zsh/basic.zsh",
        "shell/zunit/basic.zunit", "shell/zsh/autoload-and-fpath.zsh",
        "shell/zsh/zstyle-and-completion.zsh",
    ), ("zsh.autoload", "zsh.zstyle", "awk.include", "powershell.function")),
    ("bash-effects", ("shell/bash/side-effects.bash",), ("shell.host_mutation", "shell.network_call")),
    ("powershell-effects", ("powershell/side-effects.ps1",), ("powershell.host_mutation", "powershell.network_call")),
    ("bash-structure", (
        "shell/bash/functions-and-source.bash", "shell/bash/advanced-safety.bash",
        "shell/bash/commands-pipelines-redirects.bash", "shell/bash/heredocs.bash",
    ), ("shell.function", "shell.source", "shell.pipeline", "shell.redirect", "shell.heredoc")),
    ("false-positives", (
        "shell/bash/false-positives.bash", "shell/zsh/false-positives.zsh",
        "shell/awk/false-positives.awk", "shell/bats/false-positives.bats",
        "shell/zunit/false-positives.zunit",
    ), ("shell.script", "zsh.script", "awk.program", "bats.file", "zunit.file")),
    ("awk-structure", (
        "shell/awk/calls.awk", "shell/awk/functions.awk", "shell/awk/patterns-and-actions.awk",
        "shell/awk/gawk-extensions.awk",
    ), ("awk.function", "awk.builtin_call", "awk.include")),
    ("awk-io", ("shell/awk/io-and-pipes.awk", "shell/awk/redaction.awk"),
     ("awk.file_read", "awk.file_write", "awk.pipe_read", "awk.pipe_write", "awk.system_call")),
    ("bats-helpers", (
        "shell/bats/helpers-and-libraries.bats", "shell/bats/helpers-and-loads.bats",
        "shell/bats/hooks.bats",
    ), ("bats.load", "bats.setup", "bats.teardown", "bats.test_case")),
    ("bats-assertions", (
        "shell/bats/run-and-assertions.bats", "shell/bats/skip-and-fixtures.bats", "shell/bats/redaction.bats",
    ), ("bats.run", "bats.assertion", "bats.skip")),
    ("zunit-structure", (
        "shell/zunit/suites-and-cases.zunit", "shell/zunit/hooks.zunit", "shell/zunit/helpers-fixtures-mocks.zunit",
    ), ("zunit.suite", "zunit.test_case", "zunit.setup", "zunit.teardown", "zunit.mock", "zunit.fixture_reference")),
    ("zunit-assertions", (
        "shell/zunit/assertions-and-commands.zunit", "shell/zunit/skips-and-todos.zunit", "shell/zunit/redaction.zunit",
    ), ("zunit.assertion", "zunit.command_under_test", "zunit.skip", "zunit.todo")),
    ("zsh-values", (
        "shell/zsh/arrays.zsh", "shell/zsh/associative-arrays.zsh", "shell/zsh/globs-and-expansions.zsh",
        "shell/zsh/functions.zsh",
    ), ("zsh.array_assignment", "zsh.associative_array_assignment", "shell.function", "zsh.parameter_expansion")),
    ("zsh-commands", (
        "shell/zsh/commands.zsh", "shell/zsh/heredocs.zsh", "shell/zsh/pipelines-and-redirects.zsh",
    ), ("shell.command", "shell.heredoc", "shell.pipeline", "shell.redirect")),
    ("zsh-startup", (
        "shell/zsh/startup/.zprofile", "shell/zsh/startup/.zshenv", "shell/zsh/startup/.zshrc",
        "shell/zsh/completion/_mytool", "shell/zsh/plugins-and-themes.zsh",
    ), ("zsh.startup_file", "zsh.completion_function", "zsh.plugin", "zsh.theme")),
    ("zsh-effects", ("shell/zsh/side-effects.zsh", "shell/zsh/redaction.zsh"),
     ("shell.host_mutation", "shell.network_call")),
    ("powershell-commands", ("powershell/commands-and-pipelines.ps1",),
     ("powershell.command", "powershell.pipeline", "powershell.command_argument")),
)


def portable_corpus_dependencies(corpus: str) -> dict[str, str]:
    """Materialize only static local helpers; no interpreter or external library is loaded."""
    by_corpus = {
        "core": {
            "shell/awk/lib/common.awk": "function common_lib() { return 1 }\n",
            "shell/zsh/lib/example.zsh": "# Static source dependency\n",
            "powershell/Example.Shared.psm1": "function Get-Shared { 'shared' }\nExport-ModuleMember -Function Get-Shared\n",
            "powershell/helpers/Example.Shared.ps1": "function Get-Helper { 'helper' }\n",
        },
        "bash-structure": dict.fromkeys(("shell/bash/lib/common.bash", "shell/bash/lib/logging.sh"), "# Static helper\n"),
        "awk-structure": {"shell/awk/lib.awk": "function shared() { return 1 }\n"},
        "bats-helpers": dict.fromkeys(("shell/bats/test_helper", "shell/bats/helpers/common", "shell/support/helpers"), "# Static helper\n"),
        "zunit-structure": dict.fromkeys((
            "shell/zunit/helpers/common.zsh", "shell/zunit/helpers/assertions.zsh", "shell/zunit/helpers/extra.zsh",
            "shell/zunit/fixtures/public-input.txt", "shell/zunit/fixtures/extra-input.txt", "shell/zunit/fixtures/curl-response.txt",
        ), "# Static fixture\n"),
    }
    return by_corpus.get(corpus, {})
