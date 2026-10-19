"""Canonical runner command composition, validation, and log preservation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import time

from runner_pgvector_profile import (
    validate_profile_choice,
)

PYTEST_ELAPSED_PATTERN = re.compile(r"\bin\s+([0-9:]+(?:\.[0-9]+)?s?(?:\s+\([0-9:]+\))?)")


@dataclass(frozen=True)
class ExecutionReceipt:
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    elapsed_suffix: str | None


def validate_canonical_no_coverage_args(argv: list[str]) -> None:
    """Validate that invocation satisfies canonical no-coverage standards."""
    forwarded_index = argv.index("--") if "--" in argv else len(argv)
    runner_argv = argv[:forwarded_index]

    if "--no-coverage" not in runner_argv:
        raise RuntimeError("canonical command requires --no-coverage")

    if "--suite" not in runner_argv:
        raise RuntimeError("canonical command requires --suite <suite>")
    suite_idx = runner_argv.index("--suite")
    if suite_idx + 1 >= len(runner_argv):
        raise RuntimeError("canonical command has missing --suite value")
    suite = runner_argv[suite_idx + 1]
    if suite not in {"unit", "int", "smoke", "staging", "system"}:
        raise RuntimeError(f"canonical command has invalid suite: {suite!r}")

    for idx, arg in enumerate(runner_argv):
        if arg == "--pg-test-profile" and idx + 1 < len(runner_argv):
            validate_profile_choice(runner_argv[idx + 1])
        elif arg.startswith("--pg-test-profile="):
            validate_profile_choice(arg.split("=", 1)[1])


@dataclass(frozen=True)
class PytestSummaryCounts:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    deselected: int = 0
    elapsed_suffix: str | None = None


def extract_pytest_elapsed_suffix(output: str) -> str | None:
    """Extract pytest summary elapsed suffix (e.g. '0.42s' or '0:01:14') from console output."""
    matches = PYTEST_ELAPSED_PATTERN.findall(output)
    if matches:
        return matches[-1]
    return None


def parse_pytest_summary(output: str) -> PytestSummaryCounts:
    """Parse pytest counts (passed, failed, skipped, deselected) and elapsed suffix."""
    passed = 0
    failed = 0
    skipped = 0
    deselected = 0
    elapsed_suffix = extract_pytest_elapsed_suffix(output)

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("=") and line.endswith("="):
            m_pass = re.search(r"\b(\d+)\s+passed\b", line)
            m_fail = re.search(r"\b(\d+)\s+failed\b", line)
            m_skip = re.search(r"\b(\d+)\s+skipped\b", line)
            m_desel = re.search(r"\b(\d+)\s+deselected\b", line)
            if m_pass or m_fail or m_skip or m_desel:
                if m_pass:
                    passed = int(m_pass.group(1))
                if m_fail:
                    failed = int(m_fail.group(1))
                if m_skip:
                    skipped = int(m_skip.group(1))
                if m_desel:
                    deselected = int(m_desel.group(1))
                break
    return PytestSummaryCounts(
        passed=passed,
        failed=failed,
        skipped=skipped,
        deselected=deselected,
        elapsed_suffix=elapsed_suffix,
    )


def execute_canonical_command(
    command: list[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 300.0,
) -> ExecutionReceipt:
    """Execute command, capturing full output, exit status, and pytest elapsed suffix."""
    start_time = time.monotonic()
    effective_env = dict(os.environ)
    if env:
        effective_env.update(env)

    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=effective_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        elapsed = time.monotonic() - start_time
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        elapsed_suffix = extract_pytest_elapsed_suffix(combined)
        return ExecutionReceipt(
            command=tuple(command),
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            elapsed_seconds=elapsed,
            elapsed_suffix=elapsed_suffix,
        )
    except subprocess.TimeoutExpired as error:
        elapsed = time.monotonic() - start_time
        stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
        stderr = error.stderr.decode() if isinstance(error.stderr, bytes) else (error.stderr or "")
        return ExecutionReceipt(
            command=tuple(command),
            exit_code=124,
            stdout=stdout,
            stderr=stderr + f"\nCommand timed out after {timeout} seconds",
            elapsed_seconds=elapsed,
            elapsed_suffix=None,
        )


__all__ = (
    "ExecutionReceipt",
    "PytestSummaryCounts",
    "execute_canonical_command",
    "extract_pytest_elapsed_suffix",
    "parse_pytest_summary",
    "validate_canonical_no_coverage_args",
)
