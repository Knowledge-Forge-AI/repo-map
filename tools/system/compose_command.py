"""Compose command execution for the system gate with no-build and pull-never enforcement."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any

from tools.system.config import SystemTestError

FORBIDDEN_COMPOSE_SUBCOMMANDS = frozenset({"build", "pull", "push"})
FORBIDDEN_COMPOSE_BUILD_FLAGS = frozenset({"--build"})
FORBIDDEN_COMPOSE_PULL_FLAGS = frozenset({"--pull=always", "--pull=missing"})
_GLOBAL_VALUE_FLAGS = frozenset({
    "-f", "--file", "-p", "--project-name", "--profile",
    "--project-directory", "--env-file", "--ansi", "--progress", "--parallel",
})
_EXEC_VALUE_FLAGS = frozenset({"-u", "--user", "--index", "-e", "--env", "-w", "--workdir"})
_RUN_VALUE_FLAGS = frozenset({
    "--name", "--entrypoint", "-e", "--env", "--env-file", "-l", "--label",
    "-u", "--user", "-v", "--volume", "-p", "--publish", "-w", "--workdir", "--pull",
})


def _check_compose_option(token: str, next_token: str | None) -> None:
    if token in FORBIDDEN_COMPOSE_BUILD_FLAGS:
        raise SystemTestError(f"forbidden build flag {token!r}")
    if token in FORBIDDEN_COMPOSE_PULL_FLAGS or (
        token.startswith("--pull=") and token != "--pull=never"
    ):
        raise SystemTestError(f"forbidden --pull policy in {token!r}; only '--pull never' is allowed")
    if token == "--pull" and next_token != "never":
        raise SystemTestError(
            f"forbidden --pull policy {next_token or ''!r}; only '--pull never' is allowed"
        )


def _scan_option_slice(tokens: list[str], value_flags: frozenset[str], *, stop_at_service: bool) -> int:
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok == "--":
            return idx
        nxt = tokens[idx + 1] if idx + 1 < len(tokens) else None
        if stop_at_service and not tok.startswith("-"):
            return idx
        _check_compose_option(tok, nxt)
        idx += 2 if (tok in value_flags and nxt is not None) else 1
    return len(tokens)


def normalize_compose_args(args: list[str]) -> list[str]:
    tokens = [str(x) for x in args]
    subcmd_idx = 0
    while subcmd_idx < len(tokens):
        tok = tokens[subcmd_idx]
        if tok in _GLOBAL_VALUE_FLAGS:
            subcmd_idx += 2
        elif tok.startswith("-"):
            subcmd_idx += 1
        else:
            break
    if subcmd_idx >= len(tokens):
        return tokens
    subcmd = tokens[subcmd_idx]
    if subcmd in FORBIDDEN_COMPOSE_SUBCOMMANDS:
        raise SystemTestError(
            f"forbidden subcommand {subcmd!r}; system gate must use prebuilt images only"
        )
    rest = tokens[subcmd_idx + 1 :]
    if subcmd == "exec":
        _scan_option_slice(rest, _EXEC_VALUE_FLAGS, stop_at_service=True)
        return tokens
    if subcmd == "run":
        opt_end = _scan_option_slice(rest, _RUN_VALUE_FLAGS, stop_at_service=True)
        run_opts = rest[:opt_end]
        has_pull_never = "--pull=never" in run_opts or any(
            run_opts[i] == "--pull" and i + 1 < len(run_opts) and run_opts[i + 1] == "never"
            for i in range(len(run_opts))
        )
        injected = [] if has_pull_never else ["--pull", "never"]
        return [*tokens[: subcmd_idx + 1], *injected, *rest]
    if subcmd == "up":
        _scan_option_slice(rest, frozenset({"--pull"}), stop_at_service=False)
        injected_up: list[str] = []
        if "--no-build" not in rest:
            injected_up.append("--no-build")
        has_pull_never = "--pull=never" in rest or any(
            rest[i] == "--pull" and i + 1 < len(rest) and rest[i + 1] == "never"
            for i in range(len(rest))
        )
        if not has_pull_never:
            injected_up.extend(["--pull", "never"])
        return [*tokens[: subcmd_idx + 1], *injected_up, *rest]
    _scan_option_slice(rest, frozenset({"--pull"}), stop_at_service=False)
    return tokens


_normalize_compose_args = normalize_compose_args


def _run_compose(
    compose_dir: Path,
    args: list[str],
    *,
    timer: Any | None = None,
    env: dict[str, str] | None = None,
    stdin_input: str | None = None,
    timeout: float = 60.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    safe_args = normalize_compose_args(list(args))
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    effective_timeout = timer.clamp_timeout(timeout) if timer is not None else timeout
    cmd = ["docker", "compose", *safe_args]
    result = subprocess.run(
        cmd,
        cwd=compose_dir,
        capture_output=True,
        text=True,
        input=stdin_input,
        env=run_env,
        timeout=effective_timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise SystemTestError(
            f"docker compose command failed ({' '.join(safe_args)}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result
