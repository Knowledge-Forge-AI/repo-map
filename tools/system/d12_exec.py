"""Bounded Docker container exec helper for Route B D12 system candidate verification."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
import re
import subprocess
from typing import Any

from tools.system.config import SystemTestError

INNER_DOCKER_HOST = "unix:///run/repomap-docker.sock"


@dataclass(frozen=True)
class ExecRunResult:
    exit_code: int
    output: bytes | tuple[bytes | None, bytes | None]


def build_d12_container_exec_command(
    container_id: str,
    command: Sequence[str],
    *,
    user: str | None = None,
    workdir: str | None = None,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    cid = str(container_id).strip()
    if not cid or any(ch.isspace() for ch in cid):
        raise SystemTestError(
            f"D12 container exec requires a valid non-empty container_id, got {container_id!r}"
        )
    if not isinstance(command, (list, tuple)) or not command:
        raise SystemTestError("D12 container exec requires a non-empty command")
    cmd_list: list[str] = []
    for item in command:
        if not isinstance(item, str) or "\x00" in item:
            raise SystemTestError("D12 container exec command arguments must be strings without NUL")
        cmd_list.append(item)
    if not cmd_list[0].strip():
        raise SystemTestError("D12 container exec requires a non-empty command")
    argv = ["docker", "exec", "-i"]
    if user:
        if not isinstance(user, str) or "\x00" in user:
            raise SystemTestError("D12 container exec user must be a valid string")
        argv.extend(("--user", user))
    if workdir:
        if not isinstance(workdir, str) or "\x00" in workdir:
            raise SystemTestError("D12 container exec workdir must be a valid string")
        argv.extend(("--workdir", workdir))
    if env is not None:
        if not isinstance(env, Mapping):
            raise SystemTestError("D12 container exec environment must be a string mapping")
        for key in sorted(env):
            val = env[key]
            if not isinstance(key, str) or not key or "=" in key or "\x00" in key:
                raise SystemTestError(f"invalid D12 container exec env entry: {key!r}")
            if not isinstance(val, str) or "\x00" in val:
                raise SystemTestError(f"invalid D12 container exec env value for {key!r}")
            argv.extend(("--env", f"{key}={val}"))
    argv.append(cid)
    argv.extend(cmd_list)
    return argv


def run_d12_container_exec(
    container_id: str,
    command: Sequence[str],
    *,
    timeout_seconds: float = 60.0,
    user: str | None = None,
    workdir: str | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    run_cmd: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    if timeout_seconds <= 0:
        raise SystemTestError(
            f"D12 container exec timeout_seconds must be positive, got {timeout_seconds}"
        )
    argv = build_d12_container_exec_command(
        container_id,
        command,
        user=user,
        workdir=workdir,
        env=env,
    )
    exec_env = {k: v for k, v in os.environ.items() if k != "DOCKER_CONTEXT"}
    exec_env["DOCKER_HOST"] = INNER_DOCKER_HOST
    err_msg: str | None = None
    try:
        return run_cmd(
            argv,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=exec_env,
        )
    except subprocess.TimeoutExpired as exc:
        err_msg = f"d12 docker exec timed out after {int(exc.timeout or timeout_seconds)}s"
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        err_msg = f"d12 docker exec failed to start: {reason}"
    raise SystemTestError(err_msg)


class BoundedExecContainer:
    """Proxy around an owned Container that executes exec_run via bounded Docker CLI subprocesses."""

    def __init__(
        self,
        container: Any,
        *,
        deadline: Any | None = None,
        default_timeout_seconds: float = 900.0,
        docker_host: str = INNER_DOCKER_HOST,
        run_cmd: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    ) -> None:
        self._container = container
        self._deadline = deadline
        self._default_timeout_seconds = float(default_timeout_seconds)
        self._docker_host = str(docker_host)
        self._run_cmd = run_cmd

    @property
    def id(self) -> str:
        return str(self._container.id)

    @property
    def attrs(self) -> dict[str, Any]:
        return getattr(self._container, "attrs", {})

    @property
    def status(self) -> str:
        return str(getattr(self._container, "status", ""))

    def start(self) -> None:
        self._container.start()

    def reload(self) -> None:
        if hasattr(self._container, "reload"):
            self._container.reload()

    def wait(self, **kwargs: Any) -> Any:
        return self._container.wait(**kwargs)

    def logs(self, **kwargs: Any) -> Any:
        return self._container.logs(**kwargs)

    def exec_run(
        self,
        cmd: Sequence[str],
        *,
        stdout: bool = True,
        stderr: bool = True,
        stdin: bool = False,
        tty: bool = False,
        privileged: bool = False,
        user: str = "",
        detach: bool = False,
        stream: bool = False,
        socket: bool = False,
        environment: Mapping[str, str] | None = None,
        workdir: str | None = None,
        demux: bool = False,
    ) -> ExecRunResult:
        if stdin or tty or privileged or detach or stream or socket or (not stdout and not stderr):
            raise SystemTestError("unsupported exec_run mode in BoundedExecContainer")
        argv = build_d12_container_exec_command(
            self.id,
            cmd,
            user=user or None,
            workdir=workdir,
            env=environment,
        )
        timeout = self._default_timeout_seconds
        if self._deadline is not None:
            if hasattr(self._deadline, "check_test_budget"):
                self._deadline.check_test_budget("d12 bounded container exec")
            elif hasattr(self._deadline, "check_budget"):
                self._deadline.check_budget()
            if hasattr(self._deadline, "clamp_timeout"):
                timeout = float(self._deadline.clamp_timeout(self._default_timeout_seconds))
        if timeout <= 0:
            raise SystemTestError("D12 container exec budget exhausted before command start")
        exec_env = {k: v for k, v in os.environ.items() if k != "DOCKER_CONTEXT"}
        exec_env["DOCKER_HOST"] = self._docker_host
        err_msg: str | None = None
        try:
            if demux:
                proc = self._run_cmd(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=exec_env,
                    text=False,
                    timeout=timeout,
                    check=False,
                )
                out_b = (proc.stdout or b"") if stdout else None
                err_b = (proc.stderr or b"") if stderr else None
                return ExecRunResult(exit_code=int(proc.returncode), output=(out_b, err_b))
            if stdout and stderr:
                proc = self._run_cmd(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=exec_env,
                    text=False,
                    timeout=timeout,
                    check=False,
                )
                return ExecRunResult(exit_code=int(proc.returncode), output=proc.stdout or b"")
            proc = self._run_cmd(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=exec_env,
                text=False,
                timeout=timeout,
                check=False,
            )
            single = (proc.stdout or b"") if stdout else (proc.stderr or b"")
            return ExecRunResult(exit_code=int(proc.returncode), output=single)
        except subprocess.TimeoutExpired as exc:
            err_msg = f"d12 docker exec timed out after {int(exc.timeout or timeout)}s"
        except OSError as exc:
            reason = exc.strerror or type(exc).__name__
            err_msg = f"d12 docker exec failed to start: {reason}"
        raise SystemTestError(err_msg)


def wrap_create_with_bounded_exec(
    create_fn: Callable[..., tuple[str, Any]],
    *,
    deadline: Any | None = None,
    default_timeout_seconds: float = 900.0,
    run_cmd: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> Callable[..., tuple[str, BoundedExecContainer]]:
    def _wrapped(
        owner: Any, client: Any, image: str, command: Any, **options: Any
    ) -> tuple[str, BoundedExecContainer]:
        identity, container = create_fn(owner, client, image, command, **options)
        return identity, BoundedExecContainer(
            container,
            deadline=deadline,
            default_timeout_seconds=default_timeout_seconds,
            run_cmd=run_cmd,
        )

    return _wrapped


_BUILDKIT_CMD_RE = re.compile(r"(\bRUN\s+|process\s+\"/bin/sh\s+-c\s+)")
_STEP_HEADER_RE = re.compile(r"^(?:#\d+\s+\[|Step\s+\d+(?:/\d+)?\s*:\s*RUN\b|RUN\s+)")
_FAILURE_LINE_RE = re.compile(
    r"(\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Refusal|Exit):|\bAssertionError\b|\bexited\s+-?\d+:)"
)
_OMITTED_MARKER = " ...[omitted]... "


def _compact_buildkit_line(line: str) -> str:
    if len(line) > 220 and _BUILDKIT_CMD_RE.search(line):
        return f"{line[:140]}{_OMITTED_MARKER}{line[-40:]}"
    return line


def format_build_failure_excerpt(stderr: str, stdout: str = "", *, limit: int = 2000) -> str:
    """Return a bounded build failure excerpt anchored on the primary exception before BuildKit echo."""
    raw = stderr.strip() or stdout.strip()
    if not raw or limit <= 0:
        return ""
    lines = raw.splitlines()
    echo_idx = next(
        (
            idx
            for idx, line in enumerate(lines)
            if line.strip() == "------" or line.strip().startswith("Dockerfile:")
        ),
        len(lines),
    )
    pre_lines = lines[:echo_idx] if echo_idx > 0 else lines
    omitted_echo = echo_idx < len(lines) and echo_idx > 0
    compacted: list[str] = []
    seen_cmd_echoes: set[str] = set()
    for line in pre_lines:
        shortened = _compact_buildkit_line(line)
        if shortened != line:
            if shortened in seen_cmd_echoes:
                if not compacted or compacted[-1] != _OMITTED_MARKER.strip():
                    compacted.append(_OMITTED_MARKER.strip())
                continue
            seen_cmd_echoes.add(shortened)
        compacted.append(shortened)
    anchor_idx = next(
        (
            idx
            for idx in range(len(compacted) - 1, -1, -1)
            if "Traceback (most recent call last):" in compacted[idx]
        ),
        None,
    )
    if anchor_idx is None:
        anchor_idx = next(
            (
                idx
                for idx in range(len(compacted) - 1, -1, -1)
                if _FAILURE_LINE_RE.search(compacted[idx])
            ),
            None,
        )
    if anchor_idx is not None and anchor_idx > 0:
        header_idx = next(
            (
                idx
                for idx in range(anchor_idx - 1, -1, -1)
                if _STEP_HEADER_RE.search(compacted[idx]) and " ERROR: process " not in compacted[idx]
            ),
            next((idx for idx, line in enumerate(compacted[:anchor_idx]) if line.strip()), None),
        )
        prefix: list[str] = []
        if header_idx is not None:
            if header_idx > 0:
                prefix.append(_OMITTED_MARKER.strip())
            prefix.append(compacted[header_idx])
            if anchor_idx > header_idx + 1:
                prefix.append(_OMITTED_MARKER.strip())
        else:
            prefix.append(_OMITTED_MARKER.strip())
        selected = [*prefix, *compacted[anchor_idx:]]
    else:
        selected = compacted[anchor_idx:] if anchor_idx is not None else compacted
    if omitted_echo and selected and selected[-1] != _OMITTED_MARKER.strip():
        selected = [*selected, _OMITTED_MARKER.strip()]
    joined = "\n".join(selected).strip()
    if len(joined) <= limit:
        return joined
    if limit <= len(_OMITTED_MARKER):
        return joined[:limit]
    budget = limit - len(_OMITTED_MARKER)
    head_len = max(1, (budget * 3) // 4)
    tail_len = max(0, budget - head_len)
    return f"{joined[:head_len]}{_OMITTED_MARKER}{joined[-tail_len:] if tail_len else ''}"


__all__ = [
    "BoundedExecContainer",
    "ExecRunResult",
    "INNER_DOCKER_HOST",
    "build_d12_container_exec_command",
    "format_build_failure_excerpt",
    "run_d12_container_exec",
    "wrap_create_with_bounded_exec",
]
