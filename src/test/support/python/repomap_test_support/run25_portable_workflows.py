"""Test support utilities for Run25 coordinator portable workflows and bootstrap causality."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Mapping

from repomap_kg.artifacts.references import ArtifactLocator, ArtifactReference
from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator._portable_capability import (
    PortableExecutionCapability,
    create_portable_capability as create_portable_capability,
)
from repomap_kg.coordinator.protocol import (
    SyntheticWorkerResult,
    WorkerLaunchSpec,
    run_worker_spec,
)
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.storage.staging_family_contracts import PrivacyClassification

# Mandatory coordinator limits pinned to exact protocol timing: hello .5, heartbeat .15, process .8
RUN25_MANDATORY_LIMITS: dict[str, object] = {
    "process_deadline_seconds": 0.8,
    "heartbeat_seconds": 0.15,
    "hello_deadline_seconds": 0.5,
    "cancellation_after_seconds": 0.08,
    "cancel_deadline_seconds": 0.08,
    "process_termination_grace_seconds": 0.08,
    "max_diagnostic_bytes": 96,
    "max_protocol_line_bytes": 65536,
    "max_array_items": 64,
}

TINY_PORTABLE_CHILD_CODE = '''"""Tiny maintained portable child fixture."""
import argparse, sys
from repomap_kg.coordinator.protocol import (
    MAX_JSONL_LINE_BYTES,
    ProtocolSession,
    decode_jsonl,
    encode_jsonl,
)

def branch_function(flag: bool) -> int:
    if flag:
        chosen = 100
    else:
        chosen = 200
    return chosen

def main() -> int:
    from repomap_kg.coordinator import _portable_authority as authority
    assert authority.install_portable_authority_guard.__module__ == authority.__name__
    from pathlib import Path
    workspace = Path.cwd() / 'guarded-workspace'
    workspace.mkdir()
    authority.install_portable_authority_guard(
        store_root=workspace, workspace_root=workspace,
        code_roots=(Path(__file__).parent, Path(authority.__file__).parents[2]),
    )
    try:
        open(Path.cwd() / 'forbidden-output', 'w')
    except PermissionError:
        pass
    else:
        raise AssertionError('portable guard was weakened')
    val = branch_function(True)
    assert val == 100
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", default="job-1")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--mode", default="success", choices=["success", "cancel", "fail"])
    parser.add_argument("--atexit-sleep", type=float, default=0.0)
    parser.add_argument("--pre-hello-sleep", type=float, default=0.0)
    parser.add_argument("--workload-sleep", type=float, default=0.0)
    parser.add_argument("--exit-code", type=int, default=0)
    args, _ = parser.parse_known_args()
    if args.atexit_sleep > 0:
        import atexit, time
        atexit.register(time.sleep, args.atexit_sleep)
    if args.pre_hello_sleep > 0:
        import time
        time.sleep(args.pre_hello_sleep)
    identity = {"job_id": args.job_id, "attempt": args.attempt}
    session = ProtocolSession(identity)
    hello = {
        "schema_version": 1, "message_type": "worker_hello", "protocol_versions": [1],
        "worker_generation": "worker-v1", "capabilities": ["refresh_graph"], "process_nonce": "nonce-1",
    }
    session.accept_worker(hello)
    sys.stdout.buffer.write(encode_jsonl(hello))
    sys.stdout.buffer.flush()

    line = sys.stdin.buffer.readline(MAX_JSONL_LINE_BYTES + 1)
    job_start = decode_jsonl(line)
    session.accept_coordinator(job_start)

    if args.workload_sleep > 0:
        import time
        time.sleep(args.workload_sleep)

    base_term = {
        "schema_version": 1, **identity, "job_kind": "refresh_graph",
        "graph_id": job_start["graph_id"], "started_at": "2026-09-12T12:00:01Z",
        "finished_at": "2026-09-12T12:00:02Z", "phase": "complete", "warnings": [],
        "diagnostics": [], "source_generation": job_start["source_generation"],
        "config_generation": job_start["config_generation"], "extractor_generation": "eg1:synth",
        "canonicalizer_generation": "kg1:synth", "retryable": False,
    }
    if args.mode == "cancel":
        line2 = sys.stdin.buffer.readline(MAX_JSONL_LINE_BYTES + 1)
        session.accept_coordinator(decode_jsonl(line2))
        terminal = {**base_term, "message_type": "result", "status": "cancelled", "files": 0, "observations": 0, "canonical_nodes": 0, "canonical_edges": 0, "publication_state": "not_started", "latest_run_identity": None, "error_category": None}
    elif args.mode == "fail":
        terminal = {**base_term, "message_type": "error", "status": "failed", "files": 0, "observations": 0, "canonical_nodes": 0, "canonical_edges": 0, "publication_state": "not_started", "latest_run_identity": None, "error_category": "authorization"}
    else:
        terminal = {**base_term, "message_type": "result", "status": "succeeded", "files": 1, "observations": 1, "canonical_nodes": 1, "canonical_edges": 1, "publication_state": "committed", "latest_run_identity": "run-1", "error_category": None}
    session.accept_worker(terminal)
    sys.stdout.buffer.write(encode_jsonl(terminal))
    sys.stdout.buffer.flush()
    return args.exit_code

if __name__ == "__main__":
    sys.exit(main())
'''


def build_clean_explicit_pythonpath(repo_root: Path) -> str:
    """Build a pinned explicit PYTHONPATH without ambient or empty path components."""
    clean_repo_root = repo_root.resolve()
    components = (
        clean_repo_root / "tools",
        clean_repo_root / "src" / "main" / "python",
        clean_repo_root / "src" / "test" / "support" / "python",
    )
    validated = [
        str(c)
        for c in components
        if str(c).strip() and c.is_dir()
    ]
    return os.pathsep.join(validated)


def build_run25_worker_limits() -> SimpleNamespace:
    """Construct the mandatory immutable limits container (.5 hello / .15 heartbeat / .8 process)."""
    return SimpleNamespace(
        process_deadline_seconds=0.8,
        heartbeat_seconds=0.15,
        hello_deadline_seconds=0.5,
        cancellation_after_seconds=0.08,
        cancel_deadline_seconds=0.08,
        process_termination_grace_seconds=0.08,
        max_diagnostic_bytes=96,
        max_protocol_line_bytes=65536,
        max_array_items=64,
    )



def make_test_manifest_reference(
    *,
    digest: str = "sha256:" + "f" * 64,
    size_bytes: int = 256,
    store_version: str = "store-v1",
) -> ArtifactReference:
    """Build a valid ArtifactReference pointing to a manifest descriptor."""
    digest_hex = digest.removeprefix("sha256:")
    return ArtifactReference(
        digest,
        size_bytes,
        "application/x-repomap-snapshot-manifest-v1+json",
        "canonical-json-v1",
        PrivacyClassification.RAW_SOURCE,
        ArtifactLocator("filesystem", f"objects/{digest_hex}", store_version),
    )


def create_run25_test_capability(
    root: Path,
    store: FileSystemArtifactStore,
    workspace: Path,
    *,
    graph_id: str = "run25-graph",
    job_id: str = "job-r25-01",
    attempt: int = 1,
) -> PortableExecutionCapability:
    """Construct and return an admitted, runnable PortableExecutionCapability."""
    src_dir = root / f"src_{job_id}"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "README.md").write_text("# Run25 Test Fixture\n", encoding="utf-8")

    binding = OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id(graph_id, "primary"),
        source_definition_id=f"src1:{graph_id}-primary",
        alias="primary",
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(src_dir),
        root_path_expanded=str(src_dir),
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
        name=f"Run25 Graph {graph_id}",
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
        extractor_generation="eg1:r25",
        canonicalizer_generation="kg1:r25",
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


def build_worker_script_launch_spec(
    repo_root: Path,
    script_content: str,
    cwd: Path,
    *,
    environment: Mapping[str, str] | None = None,
    extra_python_paths: tuple[Path, ...] = (),
) -> WorkerLaunchSpec:
    """Build a WorkerLaunchSpec executing inline python code under controlled environment."""
    base_pythonpath = build_clean_explicit_pythonpath(repo_root)
    if extra_python_paths:
        extra_str = os.pathsep.join(
            str(p.resolve()) for p in extra_python_paths if str(p).strip()
        )
        final_pythonpath = f"{base_pythonpath}{os.pathsep}{extra_str}"
    else:
        final_pythonpath = base_pythonpath

    env = dict(environment) if environment is not None else {}
    env["PYTHONPATH"] = final_pythonpath
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")

    return WorkerLaunchSpec(
        argv=(sys.executable, "-c", script_content),
        environment=env,
        cwd=cwd,
    )


__all__ = (
    "RUN25_MANDATORY_LIMITS",
    "TINY_PORTABLE_CHILD_CODE",
    "build_clean_explicit_pythonpath",
    "build_run25_worker_limits",
    "build_worker_script_launch_spec",
    "create_portable_capability",
    "create_run25_test_capability",
    "make_test_manifest_reference",
    "run_worker_spec",
    "SyntheticWorkerResult",
    "WorkerLaunchSpec",
)
