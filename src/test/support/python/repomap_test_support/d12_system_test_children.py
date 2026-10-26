"""Isolated stdlib child helpers for D12 proof transfer and lock contention tests (ADR 0096).

During measured unit and integration runs, ``ChildCoverageSession`` exports
``COVERAGE_PROCESS_START`` (and pinned Coverage ``7.15.4`` also honors
``COVERAGE_PROCESS_CONFIG`` in ``a1_coverage.pth``) and prepends its bootstrap
``sitecustomize.py`` directory to ``PYTHONPATH``. Direct ``[sys.executable, "-I", "-c", ...]``
test helper children ignore ``PYTHONPATH`` under ``-I`` (skipping manifest registration) while
``site.py`` still processes ``site-packages/a1_coverage.pth``, producing unregistered
``launch_shape=cpython:-c`` coverage shards.

This test-support module encapsulates the two D12 stdlib child helper shapes so both
scrub inherited coverage startup state via
``prepare_child_coverage_environment(..., family="unmeasured")`` without exposing a
generic arbitrary Python snippet runner.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

_TOOLS_DIR = str(Path(__file__).resolve().parents[5] / "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from runner_coverage_execution import prepare_child_coverage_environment
from test_sandbox_arguments import INNER_D12_SYSTEM_PROOF_PATH, transfer_system_proof

Sanitizer = Callable[..., Mapping[str, str]]
ChildRunner = Callable[..., subprocess.CompletedProcess[str]]
PopenFactory = Callable[..., Any]

_CLEAN_ENV_PROLOGUE = (
    "import os\n"
    "leaked = sorted(k for k in os.environ if k.startswith('COVERAGE_'))\n"
    "if leaked:\n"
    "    raise SystemExit(f'leaked coverage env: {leaked}')\n"
)

_FLOCK_HOLDER_SCRIPT = (
    _CLEAN_ENV_PROLOGUE
    + "import fcntl, sys\n"
    "fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o600)\n"
    "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "sys.stdout.write('locked\\n')\n"
    "sys.stdout.flush()\n"
    "sys.stdin.read()\n"
)


def poisoned_coverage_base_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a copy of ``base_env`` (or ``os.environ``) seeded with invalid coverage sentinels."""
    seeded = dict(os.environ if base_env is None else base_env)
    seeded["COVERAGE_PROCESS_START"] = "/nonexistent/ci69-broken-coverage.rc"
    seeded["COVERAGE_PROCESS_CONFIG"] = "invalid_coverage_config=1"
    return seeded


def _resolve_child_env(
    base_env: Mapping[str, str] | None,
    *,
    sanitizer: Sanitizer = prepare_child_coverage_environment,
) -> dict[str, str]:
    cleaned = dict(sanitizer(base_env=base_env, family="unmeasured"))
    unresolved = sorted(k for k in cleaned if k.startswith("COVERAGE_"))
    if unresolved:
        raise RuntimeError(f"refusing unmeasured child spawn with unresolved coverage env: {unresolved}")
    return cleaned


def transfer_proof_locally(
    runner: Any,
    container_id: str,
    proof_bytes: bytes,
    *,
    target_path: Path = INNER_D12_SYSTEM_PROOF_PATH,
    base_env: Mapping[str, str] | None = None,
    sanitizer: Sanitizer = prepare_child_coverage_environment,
    run_child: ChildRunner = subprocess.run,
) -> tuple[list[str], str]:
    """Invoke ``transfer_system_proof`` (which returns ``None``) in a scrubbed child and compute SHA-256 locally."""
    recorded: list[str] = []
    child_env = _resolve_child_env(base_env, sanitizer=sanitizer)

    def _local_exec(
        _runner: Any,
        cmd: Sequence[str],
        *,
        input_text: str | None = None,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        tokens = [str(part) for part in cmd]
        recorded.extend(tokens)
        expected_prefix = ["docker", "exec", "-i", container_id, "python3", "-I", "-c"]
        if (
            len(tokens) != 8
            or tokens[:7] != expected_prefix
            or str(target_path) not in tokens[7]
            or "O_EXCL" not in tokens[7]
            or "0o600" not in tokens[7]
        ):
            raise ValueError(f"unexpected transfer_system_proof command shape: {tokens!r}")
        script = _CLEAN_ENV_PROLOGUE + tokens[7]
        return run_child(
            [sys.executable, "-I", "-c", script],
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=child_env,
        )

    transfer_system_proof(
        runner,
        container_id,
        proof_bytes,
        captured=_local_exec,
        inner_proof_path=target_path,
    )
    return recorded, hashlib.sha256(proof_bytes).hexdigest()


@contextmanager
def hold_exclusive_flock(
    lock_file: Path,
    *,
    base_env: Mapping[str, str] | None = None,
    sanitizer: Sanitizer = prepare_child_coverage_environment,
    popen_fn: PopenFactory = subprocess.Popen,
) -> Iterator[subprocess.Popen[str]]:
    """Acquire and hold ``LOCK_EX | LOCK_NB`` on ``lock_file`` in an unmeasured child process."""
    child_env = _resolve_child_env(base_env, sanitizer=sanitizer)
    proc = popen_fn(
        [sys.executable, "-I", "-c", _FLOCK_HOLDER_SCRIPT, str(lock_file)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_env,
    )
    try:
        ready = proc.stdout.readline() if proc.stdout is not None else ""
        if ready.strip() != "locked":
            proc.wait(timeout=5)
            err = proc.stderr.read().strip() if proc.stderr is not None else ""
            raise RuntimeError(f"flock holder child failed for {lock_file}: {err or ready.strip()}")
        yield proc
    finally:
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()


__all__ = [
    "hold_exclusive_flock",
    "poisoned_coverage_base_env",
    "transfer_proof_locally",
]
