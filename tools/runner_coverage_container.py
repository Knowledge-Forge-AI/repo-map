"""Container child launch, PID translation, and container process observation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import subprocess
import time
from typing import Any
import uuid

from runner_coverage_bootstrap import (
    BootstrapCapabilityRecord,
    resolve_bootstrap_capability,
)


try:
    from test_sandbox_contract import INNER_TEST_SCRATCH_ROOT
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_sandbox_contract import INNER_TEST_SCRATCH_ROOT


def translate_path_to_container(
    path_str: str,
    *,
    capability: BootstrapCapabilityRecord | None = None,
    scratch_root: Path | str | None = None,
    container_scratch_root: Path | str | None = None,
) -> str:
    """Translate a host path to its container-visible mount alias or path."""
    if not path_str:
        return path_str
    if capability is not None:
        if path_str == str(capability.host_visible_path) and capability.container_mount_aliases:
            return capability.container_mount_aliases[0]
        if path_str == str(capability.same_namespace_path) and capability.container_mount_aliases:
            return capability.container_mount_aliases[0]
        for host_p, alias in zip(capability.additional_host_paths, capability.container_mount_aliases[1:]):
            if path_str == str(host_p):
                return alias

    c_root = Path(container_scratch_root) if container_scratch_root else INNER_TEST_SCRATCH_ROOT
    s_root = scratch_root or os.environ.get("REPOMAP_TEST_SCRATCH_ROOT")
    if not s_root and capability is not None and capability.container_mount_aliases:
        try:
            h_p = capability.host_visible_path.resolve()
            a_p = Path(capability.container_mount_aliases[0])
            rel = a_p.relative_to(c_root)
            if h_p.as_posix().endswith(rel.as_posix()):
                s_root = Path(h_p.as_posix()[: -len(rel.as_posix())].rstrip("/"))
        except Exception:
            pass

    if s_root:
        try:
            p = Path(path_str).resolve()
            sr = Path(s_root).resolve()
            if p.is_relative_to(sr):
                return str(c_root / p.relative_to(sr))
        except (ValueError, OSError):
            pass
    return path_str


def translate_pythonpath_to_container(
    pythonpath: str,
    *,
    capability: BootstrapCapabilityRecord | None = None,
    scratch_root: Path | str | None = None,
    container_scratch_root: Path | str | None = None,
) -> str:
    """Translate all paths in a PYTHONPATH string to container-visible paths."""
    if not pythonpath:
        return ""
    translated = [
        translate_path_to_container(
            part,
            capability=capability,
            scratch_root=scratch_root,
            container_scratch_root=container_scratch_root,
        )
        for part in pythonpath.split(os.pathsep)
        if part
    ]
    return os.pathsep.join(translated)


def extract_pid_from_docker_top(top_output: str, match_token: str) -> int:
    """Extract host PID from docker top output using an explicit PID header."""
    top_lines = [line.strip() for line in top_output.splitlines() if line.strip()]
    if not top_lines:
        raise ValueError("docker top output is empty")
    header = top_lines[0].split()
    if "PID" not in header:
        raise ValueError("docker top output missing explicit PID header")
    pid_idx = header.index("PID")

    matching_pids: list[int] = []
    for line in top_lines[1:]:
        if match_token in line:
            parts = line.split(maxsplit=len(header) - 1)
            if len(parts) > pid_idx and parts[pid_idx].isdigit():
                matching_pids.append(int(parts[pid_idx]))

    if len(matching_pids) > 1:
        raise RuntimeError(
            f"ambiguous PID match in docker top for token {match_token!r}: {matching_pids}"
        )
    if not matching_pids:
        raise LookupError(f"no process matched token {match_token!r} in docker top")
    return matching_pids[0]


def extract_pid_from_container_ps(ps_output: str, match_token: str) -> int:
    """Extract inner PID from container ps output using an explicit PID header."""
    ps_lines = [line.strip() for line in ps_output.splitlines() if line.strip()]
    if not ps_lines:
        raise ValueError("container ps output is empty")
    header = ps_lines[0].split()
    if "PID" not in header:
        raise ValueError("container ps output missing explicit PID header")
    pid_idx = header.index("PID")

    matching_pids: list[int] = []
    for line in ps_lines[1:]:
        if match_token in line:
            parts = line.split(maxsplit=len(header) - 1)
            if len(parts) > pid_idx and parts[pid_idx].isdigit():
                matching_pids.append(int(parts[pid_idx]))

    if len(matching_pids) > 1:
        raise RuntimeError(
            f"ambiguous PID match in container ps for token {match_token!r}: {matching_pids}"
        )
    if not matching_pids:
        raise LookupError(f"no process matched token {match_token!r} in container ps")
    return matching_pids[0]


def _query_container_processes(container_id: str) -> str:
    """Query container process table, falling back to python /proc reader if ps is absent."""
    res = subprocess.run(
        ["docker", "exec", container_id, "ps", "-eo", "pid,args"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout
    cmd = (
        "from pathlib import Path; print('PID ARGS'); "
        "[print(p.name, (p/'cmdline').read_bytes().replace(b'\\x00', b' ').decode(errors='ignore')) "
        "for p in sorted(Path('/proc').glob('[0-9]*'), key=lambda x: int(x.name))]"
    )
    for py_bin in ("python3", "python"):
        proc_res = subprocess.run(
            ["docker", "exec", container_id, py_bin, "-c", cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc_res.returncode == 0 and proc_res.stdout.strip():
            return proc_res.stdout
    raise RuntimeError(f"failed to query process table in container {container_id[:12]}")


def launch_observed_container_process(
    container_id: str,
    args: Sequence[str],
    *,
    family: str = "portable_worker",
    observer: Any = None,
    capability: BootstrapCapabilityRecord | None = None,
    env: Mapping[str, str] | None = None,
    extra_env: Mapping[str, str] | None = None,
    scratch_root: Path | str | None = None,
    container_scratch_root: Path | str | None = None,
    invocation_id: str | None = None,
    match_token: str | None = None,
    settle_timeout: float = 5.0,
) -> Any:
    """Launch a container process through production environment preparation and translation."""
    from runner_coverage_execution import (
        ALL_LAUNCH_FAMILIES,
        MEASURED_FAMILIES,
        prepare_child_coverage_environment,
    )

    if family not in ALL_LAUNCH_FAMILIES:
        raise ValueError(f"unknown coverage launch family: {family}")

    base = dict(os.environ if env is None else env)
    cap = capability or resolve_bootstrap_capability(env=base)
    if family in MEASURED_FAMILIES and cap is None:
        raise RuntimeError(
            f"measured container launch family {family!r} requires an explicit BootstrapCapabilityRecord"
        )

    cov_env = prepare_child_coverage_environment(
        base,
        family=family,
        extra_env=extra_env,
        capability=cap,
    )

    token = match_token or f"tok-{uuid.uuid4().hex}"
    full_args = list(args)
    if match_token is None and token not in " ".join(full_args):
        full_args.extend(["--launch-token", token])

    exec_cmd = ["docker", "exec", "-d"]
    for k in (
        "COVERAGE_PROCESS_START", "COVERAGE_CHILD_MANIFEST_DIR",
        "COVERAGE_SESSION_INVOCATION_ID", "COVERAGE_SESSION_SUITE",
        "COVERAGE_SESSION_REVISION", "COVERAGE_CHILD_LAUNCH_ROLE",
        "COVERAGE_CHILD_REGISTRATION_TOKEN",
    ):
        if k in cov_env:
            val = cov_env[k]
            if k in ("COVERAGE_PROCESS_START", "COVERAGE_CHILD_MANIFEST_DIR"):
                val = translate_path_to_container(
                    val,
                    capability=cap,
                    scratch_root=scratch_root,
                    container_scratch_root=container_scratch_root,
                )
            exec_cmd.extend(["-e", f"{k}={val}"])

    if "PYTHONPATH" in cov_env:
        t_pp = translate_pythonpath_to_container(
            cov_env["PYTHONPATH"],
            capability=cap,
            scratch_root=scratch_root,
            container_scratch_root=container_scratch_root,
        )
        exec_cmd.extend(["-e", f"PYTHONPATH={t_pp}"])

    exec_cmd.append(container_id)
    exec_cmd.extend(full_args)

    subprocess.run(exec_cmd, capture_output=True, text=True, check=True)

    deadline = time.monotonic() + settle_timeout
    host_pid: int | None = None
    inner_pid: int | None = None
    last_err: Exception | None = None

    while time.monotonic() < deadline:
        time.sleep(0.1)
        if host_pid is None:
            try:
                top_res = subprocess.run(
                    ["docker", "top", container_id],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                host_pid = extract_pid_from_docker_top(top_res.stdout, token)
            except Exception as exc:
                last_err = exc
        if inner_pid is None:
            try:
                ps_res = _query_container_processes(container_id)
                inner_pid = extract_pid_from_container_ps(ps_res, token)
            except Exception as exc:
                last_err = exc
        if host_pid is not None and inner_pid is not None:
            break

    if host_pid is None or inner_pid is None:
        raise RuntimeError(
            f"failed to obtain container PIDs within {settle_timeout}s: host={host_pid}, inner={inner_pid}"
        ) from last_err

    relation = "translated" if host_pid != inner_pid else "shared"

    obs = observer
    if obs is None:
        cand_manifest = cov_env.get("COVERAGE_CHILD_MANIFEST_DIR")
        cand_inv = invocation_id or cov_env.get("COVERAGE_SESSION_INVOCATION_ID")
        if cand_manifest and cand_inv:
            from runner_coverage_observer import ProcessObserver
            obs = ProcessObserver(
                observation_dir=Path(cand_manifest).parent / "observations",
                invocation_id=cand_inv,
                capability=cap,
            )

    if obs is not None:
        return obs.observe_launch(
            host_pid=host_pid,
            inner_pid=inner_pid,
            pid_namespace_relation=relation,
            argv=full_args,
            executable_family=family,
            env=cov_env,
            invocation_id=invocation_id or getattr(obs, "_invocation_id", None),
            capability=cap,
        )
    return None


__all__ = (
    "extract_pid_from_container_ps",
    "extract_pid_from_docker_top",
    "launch_observed_container_process",
    "translate_path_to_container",
    "translate_pythonpath_to_container",
)
