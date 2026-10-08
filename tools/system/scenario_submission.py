"""Bounded marker capture and child reaping for coordinator submissions."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Callable, Protocol

from repomap_kg.runtime.system_test_pause import (
    SYSTEM_TEST_CONSUMER_DEADLINE_SECONDS,
    SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS,
    SYSTEM_TEST_SUBMISSION_REAP_TIMEOUT_SECONDS,
)
from tools.system.config import SystemTestError


class BudgetTimer(Protocol):
    def check_budget(self) -> None: ...
    def remaining_for_test(self) -> float: ...


ComposeRunner = Callable[..., subprocess.CompletedProcess[str]]

_IN_CONTAINER_WAIT_SCRIPT = (
    f"import json, os, sys, time; end = time.monotonic() + {SYSTEM_TEST_CONSUMER_DEADLINE_SECONDS}; p = '/tmp/system_pause_trigger.ready'\n"
    "while time.monotonic() < end:\n"
    "    if os.path.exists(p):\n"
    "        try:\n"
    "            c = open(p, encoding='utf-8').read()\n"
    "            fields = dict(line.split('=', 1) for line in c.splitlines())\n"
    "            if 'job_id' in fields and 'attempt' in fields and 'handoff' in fields:\n"
    "                json.loads(fields['handoff']); sys.stdout.write(c); sys.exit(0)\n"
    "        except (OSError, ValueError): pass\n"
    "    time.sleep(0.05)\n"
    "sys.exit(1)"
)


def _wait_for_marker(
    compose_dir: Path,
    env: dict[str, str],
    timer: BudgetTimer,
    run_compose: ComposeRunner,
) -> tuple[str, int | None, dict[str, Any]]:
    timer.check_budget()
    marker = run_compose(
        compose_dir,
        ["exec", "-T", "coordinator", "python3", "-c", _IN_CONTAINER_WAIT_SCRIPT],
        env=env, timer=timer, timeout=SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS, check=False,
    )
    job_id = ""
    attempt: int | None = None
    handoff: dict[str, Any] = {}
    if marker.returncode == 0 and marker.stdout.strip():
        for line in marker.stdout.strip().splitlines():
            if line.startswith("job_id="):
                job_id = line.split("=", 1)[1].strip()
            elif line.startswith("attempt="):
                try:
                    attempt = int(line.split("=", 1)[1].strip())
                except ValueError as error:
                    raise SystemTestError("worker pause marker carried an invalid attempt") from error
            elif line.startswith("handoff="):
                try:
                    handoff = json.loads(line.split("=", 1)[1])
                except json.JSONDecodeError as error:
                    raise SystemTestError("worker pause marker carried an invalid handoff") from error
                if not isinstance(handoff, dict):
                    raise SystemTestError("worker pause marker carried an invalid handoff")
    return job_id, attempt, handoff

def _process_output(process: subprocess.Popen[str]) -> tuple[int | None, str, str]:
    code = process.poll()
    stdout = process.stdout.read() if process.stdout else ""
    stderr = process.stderr.read() if process.stderr else ""
    return code, stdout, stderr

def _reap(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.communicate(timeout=SYSTEM_TEST_SUBMISSION_REAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=SYSTEM_TEST_SUBMISSION_REAP_TIMEOUT_SECONDS)
    if process.poll() is None:
        raise SystemTestError("background coordinator submission was not reaped")

