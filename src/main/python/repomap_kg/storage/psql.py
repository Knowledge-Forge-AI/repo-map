"""psql execution and JSON result parsing for storage helpers."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any, Literal as _Literal, TypedDict as _TypedDict

from repomap_kg.storage.errors import StorageSchemaError

__all__ = (
    "run_psql",
    "psql_failure_message",
    "parse_psql_json",
    "last_output_line",
)

PSQL_LAUNCH_ERROR = "unable to launch psql command"
PSQL_INTERRUPTED_ERROR = "psql command interrupted"
_PSQL_FAILURE_DETAIL_LIMIT = 512
_PSQL_FAILURE_TRUNCATION_SUFFIX = " ... [truncated]"


class _RunOptions(_TypedDict, total=False):
    check: bool
    stdout: int
    stderr: int
    text: _Literal[True]
    input: str
    env: dict[str, str]


def run_psql(
    command: Sequence[str],
    *,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    kwargs: _RunOptions = {
        "check": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if input_text is not None:
        kwargs["input"] = input_text
    if env is not None:
        kwargs["env"] = env
    try:
        return subprocess.run(list(command), **kwargs)
    except subprocess.CalledProcessError as error:
        raise StorageSchemaError(psql_failure_message(error)) from error
    except KeyboardInterrupt:
        raise StorageSchemaError(PSQL_INTERRUPTED_ERROR) from None
    except OSError as error:
        raise StorageSchemaError(PSQL_LAUNCH_ERROR) from error


def psql_failure_message(error: subprocess.CalledProcessError) -> str:
    details = (error.stderr or error.stdout or "").strip()
    if details:
        return f"psql failed: {_bounded_psql_failure_details(details)}"
    return f"psql failed with exit code {error.returncode}"


def _bounded_psql_failure_details(details: str) -> str:
    lines = [line.strip() for line in details.splitlines() if line.strip()]
    first_line = lines[0]
    if len(lines) == 1 and len(first_line) <= _PSQL_FAILURE_DETAIL_LIMIT:
        return first_line
    prefix_limit = _PSQL_FAILURE_DETAIL_LIMIT - len(
        _PSQL_FAILURE_TRUNCATION_SUFFIX
    )
    return (
        first_line[:prefix_limit].rstrip()
        + _PSQL_FAILURE_TRUNCATION_SUFFIX
    )


def parse_psql_json(stdout: str, label: str) -> Any:
    try:
        return json.loads(last_output_line(stdout, label=label))
    except json.JSONDecodeError as error:
        raise StorageSchemaError(f"psql did not return {label} as JSON") from error


def last_output_line(stdout: str, *, label: str | None = None) -> str:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        if label is not None:
            raise StorageSchemaError(f"psql did not return {label} as JSON")
        raise StorageSchemaError("psql did not return a load summary")
    return lines[-1]
