"""Runner-owned scoped adapter for portable child worker measurement."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable, Iterator, Mapping

from runner_coverage_capability import (
    CapabilityContainmentError,
    CapabilityValidationError,
    ChildCoverageCapability,
)


RUNNER_MEASUREMENT_RECEIPT_HEADROOM_SECONDS: float = 0.5


class _CoveredManagedProcess:
    """Runner-owned process wrapper providing bounded receipt headroom before signal delegation."""

    def __init__(
        self, inner: Any, token: str, manifest_dir: Path,
        exit_timeout: float | None = None,
    ) -> None:
        self._inner, self._token, self._manifest_dir = inner, token, manifest_dir
        self._exit_timeout = RUNNER_MEASUREMENT_RECEIPT_HEADROOM_SECONDS if exit_timeout is None else exit_timeout
        self._deadline: float | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _wait_for_exit_receipt(self) -> bool:
        if self._deadline is None:
            self._deadline = time.monotonic() + self._exit_timeout
        exit_p = self._manifest_dir / f"{self._token}.exit"
        while time.monotonic() < self._deadline:
            if exit_p.is_file():
                try:
                    if "complete=1" in exit_p.read_text(encoding="utf-8"):
                        while time.monotonic() < self._deadline and self._inner.poll() is None:
                            time.sleep(0.005)
                        return True
                except OSError:
                    pass
            if self._inner.poll() is not None:
                return True
            time.sleep(0.005)
        return False

    def terminate_gracefully(self) -> None:
        self._wait_for_exit_receipt()
        if self._inner.poll() is None:
            self._inner.terminate_gracefully()

    def kill_tree(self) -> None:
        self._wait_for_exit_receipt()
        if self._inner.poll() is None:
            self._inner.kill_tree()

    def cleanup(self, term_timeout: float, kill_timeout: float) -> bool:
        self._wait_for_exit_receipt()
        return self._inner.cleanup(term_timeout, kill_timeout)


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

        from runner_coverage_execution import prepare_child_coverage_environment
        base_child_env = {
            "LANG": "C", "LC_ALL": "C", "PATH": "",
            "HOME": str(spec.environment.get("HOME", "")), "TMPDIR": str(spec.environment.get("TMPDIR", "")),
            "PYTHONNOUSERSITE": "1", "COVERAGE_PROCESS_START": str(capability.config_file),
            "COVERAGE_FILE": str(capability.data_dir / f".coverage.{token}"),
            "COVERAGE_CHILD_MANIFEST_DIR": str(capability.child_manifest_dir),
            "COVERAGE_CHILD_REGISTRATION_TOKEN": token,
            "COVERAGE_SESSION_INVOCATION_ID": capability.invocation_id,
            "COVERAGE_SESSION_SUITE": capability.suite,
            "COVERAGE_SESSION_REVISION": capability.source_commitment,
            "COVERAGE_CHILD_LAUNCH_ROLE": (
                "conformance-abrupt" if cmd_slice == CONFORMANCE_COMMAND and spec.argv[4].startswith("crash:")
                else ("conformance" if cmd_slice == CONFORMANCE_COMMAND else "portable")
            ),
            "COVERAGE_CHILD_TEST_OWNER": hashlib.sha256(
                os.environ.get("PYTEST_CURRENT_TEST", "").encode()
            ).hexdigest(),
        }
        clean_pypath = os.pathsep.join(approved_paths)
        env = prepare_child_coverage_environment(
            base_child_env,
            family="portable_worker",
            measure=True,
            bootstrap_dir=capability.bootstrap_dir,
            capability=session.bootstrap_capability,
            extra_env={"PYTHONPATH": clean_pypath} if clean_pypath else None,
        )
        augmented_spec = replace(spec, environment=env)

        # 7. Synchronous launch and reap under original run_worker_spec
        workload_exc: BaseException | None = None
        result: Any = None
        from repomap_kg.coordinator.process_supervision import launch_managed_process
        launcher = _launch_process or launch_managed_process

        def registered_launch(*args: Any, **kwargs: Any) -> Any:
            process = launcher(*args, **kwargs)
            capability.launched_pids[token] = process.pid
            observer = session.process_observer
            if observer is None:
                raise RuntimeError("scoped_portable_coverage_adapter requires active session.process_observer")
            launch_argv = args[0] if args else kwargs.get("argv")
            launch_env = kwargs.get("environment") or env
            inner_pid = kwargs.get("inner_pid")
            pid_relation = "translated" if kwargs.get("is_container_namespace", False) else kwargs.get("pid_namespace_relation", "shared")
            inv_id = job_context.get("invocation_id") if isinstance(job_context, dict) else env.get("COVERAGE_SESSION_INVOCATION_ID")
            owner_val = getattr(identity, "worker_id", None) or env.get("COVERAGE_CHILD_TEST_OWNER")
            observer.observe_launch(
                host_pid=process.pid, inner_pid=inner_pid, pid_namespace_relation=pid_relation,
                invocation_id=inv_id, argv=launch_argv, env=launch_env, ppid=os.getpid(),
                executable_family="portable_worker", test_owner=owner_val, capability=session.bootstrap_capability,
            )
            return _CoveredManagedProcess(process, token, capability.child_manifest_dir)

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
                    shard_name=f"portable_child.{token}", file_type="missing_or_corrupt",
                    size_bytes=-1, sha256=None, reader_status=f"acceptance_failure: {exc}",
                    stage="post_worker_reap", child_probe_id=f"token={token}",
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
    data_dir: Path, allowed_shards: set[str], parent_shard: str | None,
    snapshot_fn: Callable[..., Any], record_fn: Callable[[Any], None],
    cov_mod: Any = None, registered_children: dict[int, dict[str, Any]] | None = None,
    child_manifest_dir: Path | None = None, source_root: Path | None = None,
    checkout_root: Path | None = None, invocation_id: str | None = None,
    observer: Any = None,
) -> None:
    """Validate that shard directory contains no fabricated or unregistered shards."""
    from runner_coverage_execution import extract_pid_match

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
                raise RuntimeError(f"fabricated .parent coverage shard rejected: {child.name}")
            pid = extract_pid_match(child.name)
            child_info = (registered_children or {}).get(pid) if pid is not None else None
            manifest_dir = child_manifest_dir or (data_dir.parent / "child_procs")
            if child_info is None and pid is not None and manifest_dir and manifest_dir.exists():
                from runner_coverage_capability import _parse_marker
                for fail_candidate in (
                    manifest_dir / f"{pid}.registration_failure",
                    manifest_dir.parent / f"{pid}.registration_failure",
                    manifest_dir / f"{pid}.start",
                    manifest_dir.parent / f"{pid}.start",
                ):
                    if fail_candidate.is_file():
                        parsed = _parse_marker(fail_candidate)
                        child_info = {
                            "role": parsed.get("role"), "owner": parsed.get("owner"),
                            "ppid": int(parsed["ppid"]) if parsed.get("ppid", "").isdigit() else None,
                            "launch_shape": parsed.get("launch_shape"),
                            "failure_class": parsed.get("failure_class", "unregistered_start_marker" if fail_candidate.name.endswith(".start") else None),
                            "failure_reason": parsed.get("failure_reason", "unregistered_with_start_marker" if fail_candidate.name.endswith(".start") else None),
                        }
                        break
            obs: Any = None
            if child_info is None and pid is not None:
                inv_id: str | None = invocation_id
                if inv_id is None and manifest_dir:
                    candidates = (manifest_dir / "invocation_id.txt", manifest_dir.parent / "observations" / "invocation_id.txt")
                    for inv_candidate in candidates:
                        if inv_candidate.is_file():
                            try:
                                inv_id = inv_candidate.read_text(encoding="utf-8").strip()
                                break
                            except OSError:
                                pass
                obs_found = None
                if observer is not None and inv_id is not None:
                    obs_found = observer.find_observation_by_inner_pid(pid, inv_id)
                if obs_found is not None:
                    obs = obs_found
                    child_info = {
                        "role": "observed_unregistered", "owner": obs.test_owner_hash,
                        "ppid": obs.ppid, "launch_shape": obs.launch_shape_hash,
                        "has_config": obs.has_coverage_capability,
                        "has_manifest": obs.has_manifest_authority, "has_token": obs.has_token,
                        "bootstrap_stage": "parent_observed_no_bootstrap_marker",
                        "failure_class": "unregistered_child_process",
                        "failure_reason": "child_never_registered_bootstrap",
                    }

            sha256_val, size_val, sqlite_valid = None, -1, False
            measured_files_count, measured_classification = None, None
            forensics_data, forensic_failure_verdict = None, None
            if child.is_file():
                from runner_coverage_diagnostics import compute_streaming_sha256
                try:
                    sha256_val, size_val, header = compute_streaming_sha256(child)
                except OSError:
                    header = b""
                if header.startswith(b"SQLite format 3\x00"):
                    from runner_coverage_forensics import read_anomalous_shard_forensics
                    (
                        sqlite_valid,
                        measured_files_count,
                        forensics_data,
                        forensic_failure_verdict,
                    ) = read_anomalous_shard_forensics(
                        child,
                        data_dir,
                        source_root=source_root,
                        checkout_root=checkout_root or Path.cwd(),
                        max_paths=100,
                    )
                    if forensics_data is not None:
                        measured_classification = forensics_data.get("classification")
                        if child_info is None:
                            child_info = {}
                        if forensics_data.get("launch_shape") and not child_info.get("launch_shape"):
                            child_info["launch_shape"] = forensics_data["launch_shape"]
                        if not child_info.get("role"):
                            child_info["role"] = "unregistered"
                        if forensics_data.get("ppid") is not None and not child_info.get("ppid"):
                            child_info["ppid"] = forensics_data["ppid"]
                        if forensics_data.get("test_owner") and not child_info.get("owner"):
                            child_info["owner"] = forensics_data["test_owner"]

            snap = snapshot_fn(
                shard_name=child.name,
                file_type="unregistered",
                size_bytes=size_val,
                sha256=sha256_val,
                reader_status="unregistered_shard_rejected",
                stage="pre_combine",
                cov_mod=cov_mod,
                child_probe_id=f"pid={pid}" if pid is not None else None,
                termination_outcome="unregistered_child",
                launch_role=child_info.get("role") if child_info else None,
                test_owner=child_info.get("owner") if child_info else None,
            )
            from runner_coverage_diagnostics import merge_diagnostic_snapshot
            f_dict = forensics_data or {
                "observed_total": measured_files_count,
                "classification": measured_classification,
            }
            snap = merge_diagnostic_snapshot(
                snap, child_info=child_info, obs=obs,
                forensics=f_dict,
                sqlite_valid=sqlite_valid,
                forensic_verdict=forensic_failure_verdict,
            )
            record_fn(snap)
            raise RuntimeError(f"unregistered coverage shard rejected: {child.name}")


__all__ = (
    "RUNNER_MEASUREMENT_RECEIPT_HEADROOM_SECONDS",
    "make_portable_worker_spec_adapter",
    "scoped_portable_coverage_adapter",
    "validate_shard_directory_integrity",
)
