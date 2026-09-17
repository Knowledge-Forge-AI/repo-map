"""Execution helpers, child manifest reconciliation, and combine orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import subprocess
from typing import Any

from runner_coverage_bootstrap import (
    BootstrapCapabilityRecord,
    extend_pythonpath,
    is_runner_bootstrap_path,
    resolve_bootstrap_capability,
)
from runner_coverage_container import (
    extract_pid_from_container_ps as extract_pid_from_container_ps,
    extract_pid_from_docker_top as extract_pid_from_docker_top,
    launch_observed_container_process as launch_observed_container_process,
)
from runner_coverage_combine import (
    execute_shard_combine as execute_shard_combine,
    identify_parent_shard as identify_parent_shard,
)
from runner_coverage_diagnostics import (
    ShardDiagnosticSnapshot as ShardDiagnosticSnapshot,
    _annotate_snapshot as _annotate_snapshot,
    create_shard_snapshot as create_shard_snapshot,
    extract_child_probe_id as extract_child_probe_id,
    extract_pid_match as extract_pid_match,
    record_diagnostic as record_diagnostic,
    validate_shard_file as validate_shard_file,
)
from runner_coverage_receipts import (
    read_registered_children as read_registered_children,
    reconcile_child_manifests as reconcile_child_manifests,
    verify_intentional_victim as verify_intentional_victim,
)


MEASURED_FAMILIES = frozenset({"cli_module", "scale13_refresh", "portable_worker"})
UNMEASURED_FAMILIES = frozenset({
    "scale13_uninstrumented",
    "arch7f_probe",
    "arch7f_pip",
    "intentional_victim",
    "resource_tracker",
    "container_isolated",
    # scale18_worker: RSS benchmark campaign whose memory and throughput
    # measurements are distorted by tracing; scrubbed of coverage capability.
    "scale18_worker",
    "unmeasured",
})
ALL_LAUNCH_FAMILIES = MEASURED_FAMILIES | UNMEASURED_FAMILIES
RESERVED_COVERAGE_ENV_KEYS: frozenset[str] = frozenset({
    "COVERAGE_PROCESS_START", "COVERAGE_PROCESS_CONFIG", "COVERAGE_FILE",
    "COVERAGE_CHILD_MANIFEST_DIR", "COVERAGE_CHILD_REGISTRATION_TOKEN",
    "COVERAGE_CHILD_LAUNCH_ROLE", "COVERAGE_CHILD_TEST_OWNER",
    "COVERAGE_SESSION_INVOCATION_ID", "COVERAGE_SESSION_SUITE",
    "COVERAGE_SESSION_REVISION", "COVERAGE_CHILD_BOOTSTRAP_PAUSE_FIFO",
    "COVERAGE_CHILD_HANDSHAKE_FIFO", "COVERAGE_CHILD_RELEASE_FIFO",
})


def scrub_coverage_environment(
    env: Mapping[str, str] | None = None,
    *,
    session_dir: str | Path | None = None,
    capability: BootstrapCapabilityRecord | None = None,
) -> dict[str, str]:
    cap = capability or resolve_bootstrap_capability(env=env)
    cleaned = dict(os.environ if env is None else env)
    for key in list(cleaned):
        if key.startswith("COVERAGE_"):
            cleaned.pop(key, None)
    pp = cleaned.get("PYTHONPATH")
    if pp:
        s_str = str(session_dir) if session_dir is not None else None
        rem = [
            p for p in pp.split(os.pathsep)
            if p and (s_str is None or p != s_str) and not is_runner_bootstrap_path(p, capability=cap)
        ]
        if rem:
            cleaned["PYTHONPATH"] = os.pathsep.join(rem)
        else:
            cleaned.pop("PYTHONPATH", None)
    return cleaned


def prepare_child_coverage_environment(
    base_env: Mapping[str, str] | None = None,
    *,
    family: str = "cli_module",
    measure: bool | None = None,
    source_root: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
    bootstrap_dir: Path | str | None = None,
    session_dir: Path | str | None = None,
    capability: BootstrapCapabilityRecord | None = None,
) -> dict[str, str]:
    """One tested owner for subprocess coverage capability, PYTHONPATH, and scrubbing."""
    if family not in ALL_LAUNCH_FAMILIES:
        raise ValueError(f"unknown coverage launch family: {family}")

    if extra_env:
        for k in extra_env:
            if k in RESERVED_COVERAGE_ENV_KEYS or k.startswith("COVERAGE_"):
                raise ValueError(
                    f"caller attempted to provide runner-reserved coverage key in extra_env: {k}"
                )

    env = dict(os.environ if base_env is None else base_env)
    cap = capability or resolve_bootstrap_capability(env=env)

    if family in UNMEASURED_FAMILIES:
        is_meas = False
    elif measure is not None:
        is_meas = measure
    else:
        is_meas = bool(
            env.get("COVERAGE_PROCESS_START") or env.get("COVERAGE_PROCESS_CONFIG")
        )

    if not is_meas:
        cleaned = scrub_coverage_environment(
            env, session_dir=session_dir, capability=cap
        )
        prefix_paths = [str(source_root)] if source_root else []
        extra_pp = extra_env.get("PYTHONPATH") if extra_env else None
        filtered_extra = (
            [p for p in extra_pp.split(os.pathsep) if p and not is_runner_bootstrap_path(p, capability=cap)]
            if extra_pp
            else []
        )
        if filtered_extra or prefix_paths:
            cleaned["PYTHONPATH"] = extend_pythonpath(
                cleaned.get("PYTHONPATH"),
                *prefix_paths,
                *filtered_extra,
                capability=cap,
            )
        if extra_env:
            for k, v in extra_env.items():
                if not k.startswith("COVERAGE_") and k != "PYTHONPATH":
                    cleaned[k] = v
        return cleaned

    bdir: Path | None = Path(bootstrap_dir) if bootstrap_dir else None
    if bdir is None and env.get("COVERAGE_CHILD_MANIFEST_DIR"):
        cand = Path(env["COVERAGE_CHILD_MANIFEST_DIR"]).parent / "bootstrap"
        if is_runner_bootstrap_path(cand, capability=cap):
            bdir = cand
    if bdir is None and env.get("PYTHONPATH"):
        for p in env["PYTHONPATH"].split(os.pathsep):
            if p and is_runner_bootstrap_path(p, capability=cap):
                bdir = Path(p)
                break

    if bdir is None:
        cleaned = scrub_coverage_environment(
            env, session_dir=session_dir, capability=cap
        )
        if source_root:
            cleaned["PYTHONPATH"] = str(source_root)
        if extra_env:
            for k, v in extra_env.items():
                if not k.startswith("COVERAGE_"):
                    cleaned[k] = v
        return cleaned

    prefix_paths = [str(bdir)]
    if source_root:
        prefix_paths.append(str(source_root))
    extra_pp = extra_env.get("PYTHONPATH") if extra_env else None
    combined_raw = f"{env.get('PYTHONPATH', '')}{os.pathsep}{extra_pp}" if extra_pp else env.get("PYTHONPATH")
    env["PYTHONPATH"] = extend_pythonpath(combined_raw, *prefix_paths, capability=cap)
    if extra_env:
        for k, v in extra_env.items():
            if k != "PYTHONPATH":
                env[k] = v
    return env


def launch_observed_process(
    args: Sequence[str],
    *,
    family: str,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    extra_env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    text: bool = True,
    pid_namespace_relation: str | None = None,
    inner_pid: int | None = None,
    observer: Any = None,
    capability: BootstrapCapabilityRecord | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Launch a subprocess under the unified family contract and observe it."""
    if family not in ALL_LAUNCH_FAMILIES:
        raise ValueError(f"unknown coverage launch family: {family}")

    is_measured = family in MEASURED_FAMILIES
    if is_measured:
        if pid_namespace_relation is None:
            raise ValueError(
                f"measured coverage launch family {family!r} requires explicit pid_namespace_relation"
            )
        if pid_namespace_relation not in ("shared", "translated", "unknown"):
            raise ValueError(f"unknown pid_namespace_relation: {pid_namespace_relation!r}")
        if pid_namespace_relation == "translated" and inner_pid is None:
            raise ValueError("translated pid_namespace_relation requires inner_pid")
    else:
        if pid_namespace_relation is None:
            pid_namespace_relation = "unknown"

    base_env = env if env is not None else os.environ
    cap = capability or resolve_bootstrap_capability(env=base_env)
    resolved_env = prepare_child_coverage_environment(
        base_env,
        family=family,
        extra_env=extra_env,
        capability=cap,
    )

    obs = observer
    if obs is None and is_measured:
        cand_manifest = (
            resolved_env.get("COVERAGE_CHILD_MANIFEST_DIR")
            or os.environ.get("COVERAGE_CHILD_MANIFEST_DIR")
        )
        cand_inv = (
            resolved_env.get("COVERAGE_SESSION_INVOCATION_ID")
            or os.environ.get("COVERAGE_SESSION_INVOCATION_ID")
        )
        if cand_manifest and cand_inv:
            from runner_coverage_observer import ProcessObserver

            obs = ProcessObserver(
                observation_dir=Path(cand_manifest).parent / "observations",
                invocation_id=cand_inv,
                capability=cap,
            )
        elif (
            resolved_env.get("COVERAGE_PROCESS_START")
            or resolved_env.get("COVERAGE_PROCESS_CONFIG")
            or base_env.get("COVERAGE_PROCESS_START")
            or base_env.get("COVERAGE_PROCESS_CONFIG")
            or os.environ.get("COVERAGE_PROCESS_START")
            or os.environ.get("COVERAGE_PROCESS_CONFIG")
        ):
            raise RuntimeError(
                f"measured launch family {family!r} requires an explicit observer"
            )

    proc = subprocess.Popen(
        list(args),
        cwd=str(cwd) if cwd is not None else None,
        env=resolved_env,
        stdin=subprocess.PIPE if input_text is not None else kwargs.get("stdin"),
        stdout=kwargs.get("stdout", subprocess.PIPE),
        stderr=kwargs.get("stderr", subprocess.PIPE),
        text=text,
    )
    if obs is not None:
        obs.observe_launch(
            host_pid=proc.pid,
            inner_pid=inner_pid,
            pid_namespace_relation=pid_namespace_relation,
            argv=list(args),
            env=resolved_env,
            executable_family=family,
            capability=cap,
        )
    stdout, stderr = proc.communicate(input=input_text)
    if kwargs.get("check") and proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, list(args), output=stdout, stderr=stderr
        )
    return subprocess.CompletedProcess(
        args=list(args),
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def launch_unified_coverage_process(
    args: Sequence[str],
    *,
    family: str,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    base_env: Mapping[str, str] | None = None,
    extra_env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    text: bool = True,
    pid_namespace_relation: str | None = None,
    inner_pid: int | None = None,
    observer: Any = None,
    capability: BootstrapCapabilityRecord | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Typed unified coverage process launcher delegating to launch_observed_process."""
    effective_env = env if env is not None else base_env
    return launch_observed_process(
        args,
        family=family,
        cwd=cwd,
        env=effective_env,
        extra_env=extra_env,
        input_text=input_text,
        text=text,
        pid_namespace_relation=pid_namespace_relation,
        inner_pid=inner_pid,
        observer=observer,
        capability=capability,
        **kwargs,
    )


__all__ = (
    "ALL_LAUNCH_FAMILIES",
    "MEASURED_FAMILIES",
    "RESERVED_COVERAGE_ENV_KEYS",
    "ShardDiagnosticSnapshot",
    "UNMEASURED_FAMILIES",
    "create_shard_snapshot",
    "execute_shard_combine",
    "extract_child_probe_id",
    "extract_pid_from_container_ps",
    "extract_pid_from_docker_top",
    "extract_pid_match",
    "identify_parent_shard",
    "is_runner_bootstrap_path",
    "launch_observed_container_process",
    "launch_observed_process",
    "launch_unified_coverage_process",
    "prepare_child_coverage_environment",
    "read_registered_children",
    "reconcile_child_manifests",
    "record_diagnostic",
    "scrub_coverage_environment",
    "validate_shard_file",
    "verify_intentional_victim",
)
