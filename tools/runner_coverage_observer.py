"""Subprocess observation tracking, host/inner PID mapping, and observed launch seam."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from runner_coverage_bootstrap import (
    BootstrapCapabilityRecord,
    is_runner_bootstrap_path,
    resolve_bootstrap_capability,
)
from runner_coverage_container import (
    launch_observed_container_process as launch_observed_container_process,
)

PID_NAMESPACE_RELATIONS: frozenset[str] = frozenset({"shared", "translated", "unknown"})


def resolve_pid_namespace_mapping(
    host_pid: int,
    inner_pid: int | None,
    relation: str,
) -> tuple[int | None, str]:
    """Centralized resolution of host/inner PID relation with no implicit defaults."""
    if relation not in PID_NAMESPACE_RELATIONS:
        raise ValueError(f"unknown pid_namespace_relation: {relation!r}")
    if relation == "shared":
        return host_pid, "shared"
    if relation == "translated":
        if inner_pid is None:
            raise ValueError("translated pid_namespace_relation requires inner_pid")
        return inner_pid, "translated"
    return None, "unknown"


@dataclass(frozen=True, init=False)
class ProcessObservationRecord:
    """Bounded parent-side process facts captured at launch time."""

    process_identity: str
    host_pid: int
    inner_pid: int | None
    pid_namespace_relation: str
    invocation_id: str | None
    ppid: int | None
    start_time: float | None
    executable_family: str | None
    launch_shape_hash: str | None
    test_owner_hash: str | None
    has_coverage_capability: bool
    has_bootstrap_pythonpath: bool
    has_manifest_authority: bool
    has_token: bool
    container_cgroup_id: str | None

    def __init__(
        self,
        process_identity: str,
        host_pid: int,
        inner_pid: int | None = None,
        pid_namespace_relation: str = "unknown",
        invocation_id: str | None = None,
        ppid: int | None = None,
        start_time: float | None = None,
        executable_family: str | None = None,
        launch_shape_hash: str | None = None,
        test_owner_hash: str | None = None,
        has_coverage_capability: bool = False,
        has_bootstrap_pythonpath: bool = False,
        has_manifest_authority: bool = False,
        has_token: bool = False,
        container_cgroup_id: str | None = None,
    ) -> None:
        if pid_namespace_relation not in PID_NAMESPACE_RELATIONS:
            raise ValueError(f"unknown pid_namespace_relation: {pid_namespace_relation!r}")
        object.__setattr__(self, "process_identity", process_identity)
        object.__setattr__(self, "host_pid", host_pid)
        object.__setattr__(self, "inner_pid", inner_pid)
        object.__setattr__(self, "pid_namespace_relation", pid_namespace_relation)
        object.__setattr__(self, "invocation_id", invocation_id)
        object.__setattr__(self, "ppid", ppid)
        object.__setattr__(self, "start_time", start_time)
        object.__setattr__(self, "executable_family", executable_family)
        object.__setattr__(self, "launch_shape_hash", launch_shape_hash)
        object.__setattr__(self, "test_owner_hash", test_owner_hash)
        object.__setattr__(self, "has_coverage_capability", has_coverage_capability)
        object.__setattr__(self, "has_bootstrap_pythonpath", has_bootstrap_pythonpath)
        object.__setattr__(self, "has_manifest_authority", has_manifest_authority)
        object.__setattr__(self, "has_token", has_token)
        object.__setattr__(self, "container_cgroup_id", container_cgroup_id)

    def to_dict(self) -> dict[str, Any]:
        keys = (
            "process_identity",
            "host_pid",
            "inner_pid",
            "pid_namespace_relation",
            "invocation_id",
            "ppid",
            "start_time",
            "executable_family",
            "launch_shape_hash",
            "test_owner_hash",
            "has_coverage_capability",
            "has_bootstrap_pythonpath",
            "has_manifest_authority",
            "has_token",
            "container_cgroup_id",
        )
        return {k: getattr(self, k) for k in keys}


class ProcessObserver:
    """Parent/runner-side observer tracking launched subprocesses."""

    def __init__(
        self,
        observation_dir: Path | str,
        invocation_id: str,
        *,
        source_revision: str | None = None,
        owner: Any = None,
        capability: BootstrapCapabilityRecord | None = None,
    ) -> None:
        if invocation_id is None or not str(invocation_id).strip():
            raise ValueError("ProcessObserver requires non-empty invocation_id")
        if observation_dir is None or not str(observation_dir).strip():
            raise ValueError("ProcessObserver requires non-empty observation_dir")
        self._records: dict[int, ProcessObservationRecord] = {}
        self._inner_to_host: dict[tuple[str, int], int] = {}
        self._ambiguous_inner: set[tuple[str, int]] = set()
        self._observation_dir = Path(observation_dir)
        self._invocation_id = str(invocation_id)
        self._source_revision = source_revision
        self._owner = owner
        self._capability = capability or resolve_bootstrap_capability()

    def observe_launch(
        self,
        *,
        host_pid: int,
        pid_namespace_relation: str,
        inner_pid: int | None = None,
        invocation_id: str | None = None,
        argv: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        ppid: int | None = None,
        executable_family: str | None = None,
        container_cgroup_id: str | None = None,
        test_owner: str | None = None,
        capability: BootstrapCapabilityRecord | None = None,
    ) -> ProcessObservationRecord:
        resolved_inner, resolved_rel = resolve_pid_namespace_mapping(
            host_pid, inner_pid, pid_namespace_relation
        )

        env_map = env or {}
        exec_fam = executable_family or (
            Path(argv[0]).name if argv else Path(sys.executable).name
        )
        raw_cmd = " ".join(argv) if argv else ""
        cmd_h = (
            hashlib.sha256(raw_cmd.encode("utf-8")).hexdigest()[:16]
            if raw_cmd
            else None
        )
        has_cov = bool(
            env_map.get("COVERAGE_PROCESS_START")
            or env_map.get("COVERAGE_PROCESS_CONFIG")
        )
        m_dir = env_map.get("COVERAGE_CHILD_MANIFEST_DIR")
        has_m = bool(m_dir and Path(m_dir).is_dir())
        has_tok = bool(env_map.get("COVERAGE_CHILD_REGISTRATION_TOKEN"))
        cap = capability or self._capability or resolve_bootstrap_capability(env=env_map)
        has_boot = any(
            is_runner_bootstrap_path(p, capability=cap)
            for p in env_map.get("PYTHONPATH", "").split(os.pathsep)
            if p
        )
        to = (
            test_owner
            or env_map.get("COVERAGE_CHILD_TEST_OWNER")
            or env_map.get("PYTEST_CURRENT_TEST")
        )
        owner_h = (
            to
            if to and len(to) == 64 and all(c in "0123456789abcdef" for c in to)
            else (
                hashlib.sha256(to.encode("utf-8")).hexdigest()
                if to
                else None
            )
        )
        inv_id = (
            invocation_id
            or self._invocation_id
            or env_map.get("COVERAGE_SESSION_INVOCATION_ID")
        )

        rec = ProcessObservationRecord(
            process_identity=f"proc:{host_pid}:{time.time()}",
            host_pid=host_pid,
            inner_pid=resolved_inner,
            pid_namespace_relation=resolved_rel,
            invocation_id=inv_id,
            ppid=ppid or os.getpid(),
            start_time=time.time(),
            executable_family=exec_fam,
            launch_shape_hash=cmd_h,
            test_owner_hash=owner_h,
            has_coverage_capability=has_cov,
            has_bootstrap_pythonpath=has_boot,
            has_manifest_authority=has_m,
            has_token=has_tok,
            container_cgroup_id=container_cgroup_id,
        )
        self._records[host_pid] = rec
        if (
            resolved_inner is not None
            and resolved_rel != "unknown"
            and inv_id == self._invocation_id
        ):
            key = (inv_id, resolved_inner)
            if key in self._inner_to_host and self._inner_to_host[key] != host_pid:
                self._ambiguous_inner.add(key)
            else:
                self._inner_to_host[key] = host_pid

        if self._observation_dir:
            target = self._observation_dir / f"parent_obs_{host_pid}.json"
            try:
                self._observation_dir.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(rec.to_dict()), encoding="utf-8")
            except OSError as exc:
                raise RuntimeError(
                    f"failed to write observation record {target}: {exc}"
                ) from exc
        return rec

    def find_observation_by_inner_pid(
        self, inner_pid: int, invocation_id: str | None = None
    ) -> ProcessObservationRecord | None:
        if invocation_id is None or invocation_id != self._invocation_id:
            return None
        key = (invocation_id, inner_pid)
        if key in self._ambiguous_inner:
            return None

        host_pid = self._inner_to_host.get(key)
        if host_pid is None and self._observation_dir:
            for p in sorted(self._observation_dir.glob("parent_obs_*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    r = ProcessObservationRecord(**data)
                    if r.invocation_id != self._invocation_id:
                        continue  # Workstream I: stale/foreign invocation records rejected
                    self._records[r.host_pid] = r
                    if r.inner_pid is not None and r.pid_namespace_relation != "unknown":
                        k = (r.invocation_id, r.inner_pid)
                        if k in self._inner_to_host and self._inner_to_host[k] != r.host_pid:
                            self._ambiguous_inner.add(k)
                        else:
                            self._inner_to_host[k] = r.host_pid
                except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
                    raise RuntimeError(f"malformed process observation file {p}: {exc}") from exc
                except OSError as exc:
                    raise RuntimeError(f"unreadable process observation file {p}: {exc}") from exc
            if key in self._ambiguous_inner:
                return None
            host_pid = self._inner_to_host.get(key)

        if host_pid is not None:
            rec = self._records.get(host_pid)
            if (
                rec is not None
                and rec.invocation_id == self._invocation_id
                and rec.pid_namespace_relation != "unknown"
            ):
                return rec
        return None


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
    """Launch an observed process delegating to runner_coverage_execution."""
    from runner_coverage_execution import launch_observed_process as _impl
    return _impl(
        args,
        family=family,
        cwd=cwd,
        env=env,
        extra_env=extra_env,
        input_text=input_text,
        text=text,
        pid_namespace_relation=pid_namespace_relation,
        inner_pid=inner_pid,
        observer=observer,
        capability=capability,
        **kwargs,
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
    """Launch unified coverage process delegating to runner_coverage_execution."""
    from runner_coverage_execution import launch_unified_coverage_process as _impl
    return _impl(
        args, family=family, cwd=cwd, env=env, base_env=base_env,
        extra_env=extra_env, input_text=input_text, text=text,
        pid_namespace_relation=pid_namespace_relation, inner_pid=inner_pid,
        observer=observer, capability=capability, **kwargs,
    )


def popen_observed_process(
    args: Sequence[str],
    *,
    family: str,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    extra_env: Mapping[str, str] | None = None,
    text: bool = True,
    pid_namespace_relation: str | None = None,
    inner_pid: int | None = None,
    observer: Any = None,
    capability: BootstrapCapabilityRecord | None = None,
    **kwargs: Any,
) -> subprocess.Popen[str]:
    """Launch an observed process delegating to runner_coverage_execution."""
    from runner_coverage_execution import popen_observed_process as _impl
    return _impl(
        args, family=family, cwd=cwd, env=env, extra_env=extra_env,
        text=text, pid_namespace_relation=pid_namespace_relation,
        inner_pid=inner_pid, observer=observer, capability=capability,
        **kwargs,
    )


__all__ = (
    "PID_NAMESPACE_RELATIONS",
    "ProcessObservationRecord",
    "ProcessObserver",
    "launch_observed_container_process",
    "launch_observed_process",
    "launch_unified_coverage_process",
    "popen_observed_process",
    "resolve_pid_namespace_mapping",
)
