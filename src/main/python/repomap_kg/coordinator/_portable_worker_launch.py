"""Parent-owned launch adapter for the portable semantic worker."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import secrets
import sys
import threading
from typing import Mapping

from repomap_kg.coordinator._portable_capability import (
    create_portable_capability,
    load_portable_capability,
    remove_portable_capability,
)
from repomap_kg.coordinator._portable_materialization import (
    OwnedDirectoryIdentity,
    _directory_identity,
    _remove_attempt_root,
)
from repomap_kg.coordinator._protocol_core import ProtocolError, SyntheticWorkerResult
from repomap_kg.coordinator._worker_environment import build_portable_worker_environment
from repomap_kg.coordinator._worker_launch import WorkerLaunchSpec, run_worker_spec


def run_portable_worker(
    capability_path: Path,
    identity: Mapping[str, object],
    limits: object,
    *,
    cancel_event: threading.Event | None = None,
) -> SyntheticWorkerResult:
    """Run the fixed production worker in one parent-owned attempt root."""

    return _run_portable_worker_command(
        capability_path,
        identity,
        limits,
        module="repomap_kg.coordinator.portable_worker",
        cancel_event=cancel_event,
    )


def _run_portable_worker_command(
    capability_path: Path,
    identity: Mapping[str, object],
    limits: object,
    *,
    module: str,
    module_arguments: tuple[str, ...] = (),
    python_paths: tuple[Path, ...] = (),
    job_graph_id: str | None = None,
    cancel_event: threading.Event | None = None,
) -> SyntheticWorkerResult:
    capability = None
    attempt_root: Path | None = None
    attempt_identity: OwnedDirectoryIdentity | None = None
    process_cwd: Path | None = None
    result: SyntheticWorkerResult | None = None
    primary_error: BaseException | None = None
    try:
        capability = load_portable_capability(capability_path)
        token = secrets.token_hex(16)
        attempt_root = capability.workspace_root / f"attempt-{capability.attempt}-{token}"
        attempt_root.mkdir(mode=0o700, exist_ok=False)
        attempt_identity = _directory_identity(attempt_root)
        process_cwd = attempt_root / "process"
        process_cwd.mkdir(mode=0o700, exist_ok=False)
        child_capability = replace(capability, workspace_root=attempt_root.resolve())
        child_capability_path = create_portable_capability(attempt_root, child_capability)
        if (
            capability.job_id != identity.get("job_id")
            or capability.attempt != identity.get("attempt")
        ):
            raise ProtocolError("identity_mismatch")
        repo_root = Path(__file__).resolve().parents[5]
        python_path = repo_root / "src/main/python"
        environment = build_portable_worker_environment(
            workspace_root=process_cwd,
            python_path=python_path if python_path.is_dir() else None,
        )
        if python_paths:
            environment["PYTHONPATH"] = os.pathsep.join(
                str(path) for path in python_paths
            )
        spec = WorkerLaunchSpec(
            argv=(
                sys.executable,
                "-m",
                module,
                *module_arguments,
                "--capability",
                str(child_capability_path),
                "--job-id",
                capability.job_id,
                "--attempt",
                str(capability.attempt),
            ),
            environment=environment,
            cwd=process_cwd,
        )
        result = run_worker_spec(
            spec,
            identity,
            limits,
            job_context={
                "graph_id": job_graph_id or capability.graph_id,
                "source_generation": capability.source_generation,
                "config_generation": capability.config_generation,
                "portable_snapshot": {
                    "contract_version": "1.0",
                    "required": True,
                    "snapshot_manifest": capability.manifest_reference.to_mapping(),
                },
            },
            cancel_event=cancel_event,
        )
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        for cleanup in (
            lambda: remove_portable_capability(capability_path),
            lambda: (
                _remove_attempt_root(
                    attempt_root,
                    attempt_identity
                    if attempt_identity is not None
                    else _directory_identity(attempt_root),
                )
                if attempt_root is not None and attempt_root.is_dir()
                else None
            ),
        ):
            try:
                cleanup()
            except BaseException as caught_cleanup_error:
                cleanup_errors.append(caught_cleanup_error)
        if primary_error is not None:
            for recorded_cleanup_error in cleanup_errors:
                primary_error.add_note(
                    "portable worker cleanup failure: "
                    f"{type(recorded_cleanup_error).__name__}"
                )
        elif cleanup_errors and result is not None:
            result = replace(
                result,
                cleanup_error=",".join(
                    sorted({type(error).__name__ for error in cleanup_errors})
                ),
            )
        elif cleanup_errors:
            raise cleanup_errors[0]
    assert result is not None
    return result


__all__ = ["run_portable_worker"]
