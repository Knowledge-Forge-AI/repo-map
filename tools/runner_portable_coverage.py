"""Runner-owned scoped adapter for portable child worker measurement."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import sys
import threading
from typing import Any, Callable, Iterator, Mapping

from runner_coverage_capability import (
    CapabilityContainmentError,
    CapabilityValidationError,
    ChildCoverageCapability,
)


def make_portable_worker_spec_adapter(
    original_run_worker_spec: Callable[..., Any],
    capability: ChildCoverageCapability,
    session: Any,
) -> Callable[..., Any]:
    """Create an adapted run_worker_spec function enforcing capability and containment."""
    if not isinstance(capability, ChildCoverageCapability) or capability.session is not session:
        raise CapabilityValidationError("capability is not bound to active session")

    def adapted_run_worker_spec(
        spec: Any,
        identity: Mapping[str, object],
        limits: object,
        *,
        job_context: Mapping[str, object] | None = None,
        cancel_event: threading.Event | None = None,
        _launch_process: Callable[..., Any] | None = None,
    ) -> Any:
        # 1. Validate capability authority at launch
        capability.validate_for_launch()
        if not spec.argv or spec.argv[0] != sys.executable:
            raise CapabilityValidationError("portable interpreter identity mismatch")

        # 2. Validate canonical fixed portable command
        cmd_slice = tuple(spec.argv[1:1 + len(capability.portable_command)])
        permitted_paths = capability.paths_for_command(cmd_slice)
        from runner_coverage_conformance import (
            CONFORMANCE_COMMAND, validate_conformance_arguments,
        )
        if cmd_slice == CONFORMANCE_COMMAND:
            validate_conformance_arguments(tuple(spec.argv[3:]))

        # 3. Validate allowed product paths in spec PYTHONPATH
        spec_pypath = spec.environment.get("PYTHONPATH", "")
        approved_paths: list[str] = []
        if spec_pypath:
            for p in spec_pypath.split(os.pathsep):
                if not p:
                    continue
                p_res = Path(p).resolve()
                if p_res not in permitted_paths:
                    raise CapabilityContainmentError(f"unpermitted path in spec PYTHONPATH: {p}")
                approved_paths.append(str(p_res))
        if cmd_slice == CONFORMANCE_COMMAND and tuple(approved_paths) != tuple(map(str, permitted_paths)):
            raise CapabilityContainmentError("conformance Python paths mismatch")

        # 4. Reject ambient coverage
        for k in spec.environment:
            if k.startswith("COVERAGE_"):
                raise CapabilityValidationError(f"ambient coverage variable rejected: {k}")

        # 5. Pre-register expected child process token
        token = capability.register_prelaunch_child()
        capability.launched_commands[token] = cmd_slice

        # 6. Reconstruct minimal approved env from spec closure + bounded bootstrap
        clean_pypath = os.pathsep.join(approved_paths)
        env = {
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "",
            "HOME": str(spec.environment.get("HOME", "")),
            "TMPDIR": str(spec.environment.get("TMPDIR", "")),
            "PYTHONNOUSERSITE": "1",
            "COVERAGE_PROCESS_START": str(capability.config_file),
            "COVERAGE_FILE": str(capability.data_dir / f".coverage.{token}"),
            "COVERAGE_CHILD_MANIFEST_DIR": str(capability.child_manifest_dir),
            "COVERAGE_CHILD_REGISTRATION_TOKEN": token,
            "COVERAGE_SESSION_INVOCATION_ID": capability.invocation_id,
            "COVERAGE_SESSION_SUITE": capability.suite,
            "COVERAGE_SESSION_REVISION": capability.source_commitment,
            "COVERAGE_CHILD_LAUNCH_ROLE": (
                "conformance-abrupt" if cmd_slice == CONFORMANCE_COMMAND
                and spec.argv[4].startswith("crash:") else
                "conformance" if cmd_slice == CONFORMANCE_COMMAND else "portable"
            ),
            "COVERAGE_CHILD_TEST_OWNER": hashlib.sha256(
                os.environ.get("PYTEST_CURRENT_TEST", "").encode()
            ).hexdigest(),
            "PYTHONPATH": (
                f"{capability.bootstrap_dir}{os.pathsep}{clean_pypath}"
                if clean_pypath
                else str(capability.bootstrap_dir)
            ),
        }
        augmented_spec = replace(spec, environment=env)

        # 7. Synchronous launch and reap under original run_worker_spec
        workload_exc: BaseException | None = None
        result: Any = None
        from repomap_kg.coordinator.process_supervision import launch_managed_process
        launcher = _launch_process or launch_managed_process

        def registered_launch(*args: Any, **kwargs: Any) -> Any:
            process = launcher(*args, **kwargs)
            capability.launched_pids[token] = process.pid
            return process

        try:
            result = original_run_worker_spec(
                augmented_spec,
                identity,
                limits,
                job_context=job_context,
                cancel_event=cancel_event,
                _launch_process=registered_launch,
            )
        except BaseException as exc:
            workload_exc = exc

        # 8. Acceptance validation
        accept_exc: Exception | None = None
        try:
            if token not in capability.launched_pids:
                raise CapabilityValidationError("registered child was not launched")
            if result is not None and (not result.waited or not result.process_group_cleaned):
                raise CapabilityValidationError("registered child was not synchronously reaped")
            capability.validate_for_accept(token)
        except Exception as exc:
            accept_exc = exc
            if hasattr(session, "_create_snapshot") and hasattr(session, "_record_diagnostic"):
                snap = session._create_snapshot(
                    shard_name=f"portable_child.{token}",
                    file_type="missing_or_corrupt",
                    size_bytes=-1,
                    sha256=None,
                    reader_status=f"acceptance_failure: {exc}",
                    stage="post_worker_reap",
                    child_probe_id=f"token={token}",
                    termination_outcome=(
                        "declared_abrupt_measurement_incomplete"
                        if env["COVERAGE_CHILD_LAUNCH_ROLE"] == "conformance-abrupt"
                        else "child_measurement_failed"
                    ),
                    launch_role=env["COVERAGE_CHILD_LAUNCH_ROLE"],
                    test_owner=env["COVERAGE_CHILD_TEST_OWNER"],
                )
                session._record_diagnostic(snap)
            if hasattr(session, "record_measurement_error"):
                session.record_measurement_error(exc)

        # 9. Disposition: preserve primary workload result and exception
        if workload_exc is not None:
            if accept_exc is not None:
                workload_exc.add_note(f"child coverage measurement failure: {accept_exc}")
            raise workload_exc

        return result

    setattr(adapted_run_worker_spec, "_repomap_original", original_run_worker_spec)
    return adapted_run_worker_spec


@contextmanager
def scoped_portable_coverage_adapter(
    session: Any,
    capability: ChildCoverageCapability,
) -> Iterator[Callable[..., Any]]:
    """Context manager installing runner-owned scoped adapter at repomap_kg.coordinator._portable_worker_launch.run_worker_spec."""
    import repomap_kg.coordinator._portable_worker_launch as pwl

    original_fn = pwl.run_worker_spec
    adapter = make_portable_worker_spec_adapter(original_fn, capability, session)
    pwl.run_worker_spec = adapter
    try:
        yield adapter
    finally:
        pwl.run_worker_spec = original_fn


def validate_shard_directory_integrity(
    data_dir: Path,
    allowed_shards: set[str],
    parent_shard: str | None,
    snapshot_fn: Callable[..., Any],
    record_fn: Callable[[Any], None],
    cov_mod: Any = None,
) -> None:
    """Validate that shard directory contains no fabricated or unregistered shards."""
    for child in sorted(data_dir.iterdir(), key=lambda item: item.name):
        if child.name != ".coverage" and not child.name.startswith(".coverage."):
            continue
        resolved_child = str(child.resolve())
        if resolved_child not in allowed_shards:
            if ".parent." in child.name:
                snap = snapshot_fn(
                    shard_name=child.name,
                    file_type="fabricated_parent",
                    size_bytes=child.stat().st_size if child.is_file() else -1,
                    sha256=None,
                    reader_status="rejected_fabricated_parent_shard",
                    stage="pre_combine",
                    cov_mod=cov_mod,
                    termination_outcome="unauthorized_parent_shard",
                )
                record_fn(snap)
                raise RuntimeError(
                    f"fabricated .parent coverage shard rejected: {child.name}"
                )
            snap = snapshot_fn(
                shard_name=child.name,
                file_type="unregistered",
                size_bytes=child.stat().st_size if child.is_file() else -1,
                sha256=None,
                reader_status="unregistered_shard_rejected",
                stage="pre_combine",
                cov_mod=cov_mod,
                termination_outcome="unregistered_child",
            )
            record_fn(snap)
            raise RuntimeError(
                f"unregistered coverage shard rejected: {child.name}"
            )


__all__ = (
    "make_portable_worker_spec_adapter",
    "scoped_portable_coverage_adapter",
    "validate_shard_directory_integrity",
)
