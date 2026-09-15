"""REPOMAP-CI2A-R1 bounded smoke lifecycle unit contracts."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from smoke.lifecycle import (
    SmokeBudget,
    SmokeBudgetExceeded,
    validate_control_graph_readback,
    validate_target_database_absent,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_budget_applies_one_total_monotonic_ceiling_and_cleanup_reserve():
    clock = FakeClock()
    budget = SmokeBudget(100, clock=clock, cleanup_reserve_seconds=20)

    assert budget.remaining() == 80
    clock.advance(79)
    assert budget.remaining() == 1
    assert budget.remaining(cleanup=True) == 21

    clock.advance(1)
    with pytest.raises(SmokeBudgetExceeded, match="wall-clock budget"):
        budget.remaining()
    assert budget.remaining(cleanup=True) == 20


def test_budget_records_failed_step_and_still_allows_bounded_cleanup():
    clock = FakeClock()
    budget = SmokeBudget(40, clock=clock, cleanup_reserve_seconds=10)

    with pytest.raises(RuntimeError, match="workload red"):
        with budget.step("workload"):
            clock.advance(12.5)
            raise RuntimeError("workload red")

    with budget.step("cleanup", cleanup=True):
        clock.advance(2.5)

    assert budget.timings == {"workload": 12.5, "cleanup": 2.5}
    assert budget.elapsed() == 15


@pytest.mark.parametrize("seconds", [0, -1])
def test_budget_rejects_values_outside_the_configured_ceiling(seconds):
    with pytest.raises(ValueError, match="smoke budget must be greater than 0 seconds"):
        SmokeBudget(seconds)


def test_budget_accepts_values_above_legacy_clamp():
    clock = FakeClock()
    budget = SmokeBudget(900, clock=clock)
    assert budget.limit_seconds == 900.0


def _completed(returncode: int, payload: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(("python", "-m", "repomap_kg"), returncode, json.dumps(payload), "")


def test_post_drop_readback_accepts_only_typed_missing_database_result() -> None:
    payload = {
        "command": "graph-summary",
        "result": "failure",
        "graph": {
            "result": "failure",
            "db_checked": True,
            "repository_exists": False,
            "diagnostics": [
                {
                    "code": "graph-database-missing",
                    "severity": "error",
                    "message": (
                        "Postgres server is reachable, but the requested graph database is "
                        "missing or not initialized. Initialize or restore the graph database "
                        "before running MCP/ops readback."
                    ),
                }
            ]
        },
    }

    assert validate_target_database_absent(_completed(1, payload)) == payload


@pytest.mark.parametrize(
    ("returncode", "code"),
    (
        (1, "storage-status-unavailable"),
        (1, "authentication-failed"),
        (1, "configuration-error"),
        (2, "graph-database-missing"),
        (0, "graph-database-missing"),
    ),
)
def test_post_drop_readback_rejects_every_unrelated_failure_class(
    returncode: int,
    code: str,
) -> None:
    payload = {
        "command": "graph-summary",
        "result": "failure",
        "graph": {
            "result": "failure",
            "db_checked": True,
            "repository_exists": False,
            "diagnostics": [
                {
                    "code": code,
                    "severity": "error",
                    "message": "unrelated public diagnostic",
                }
            ]
        },
    }

    with pytest.raises(RuntimeError, match="typed target absence"):
        validate_target_database_absent(_completed(returncode, payload))


def test_control_graph_must_remain_readable_and_nonempty() -> None:
    control_graph: dict[str, object] = {
        "result": "success",
        "repository_exists": True,
        "files": 2,
    }
    control: dict[str, object] = {
        "result": "success",
        "graph": control_graph,
    }

    validate_control_graph_readback(control)
    for invalid in (
        None,
        {"result": "failure", "graph": control["graph"]},
        {"result": "success", "graph": {**control_graph, "files": 0}},
        {
            "result": "success",
            "graph": {**control_graph, "repository_exists": False},
        },
    ):
        with pytest.raises(RuntimeError, match="control graph was incoherent"):
            validate_control_graph_readback(invalid)


def test_post_drop_readback_failure_summary_is_bounded_and_sanitized() -> None:
    secret_payload = {
        "command": "graph-summary",
        "result": "failure",
        "graph": {
            "result": "failure",
            "db_checked": True,
            "repository_exists": False,
            "diagnostics": [
                {
                    "code": "storage-status-unavailable",
                    "severity": "error",
                    "message": "psycopg connection failed for operations status password=supersecret postgresql://user:pass@host/db",
                }
            ],
            "secret_field": "confidential_token_12345",
        },
    }

    with pytest.raises(RuntimeError) as exc_info:
        validate_target_database_absent(_completed(1, secret_payload))

    message = str(exc_info.value)
    assert "product command did not prove typed target absence:" in message
    assert "supersecret" not in message
    assert "confidential_token" not in message
    assert "postgresql://" not in message

    prefix, _, json_part = message.partition(": ")
    summary = json.loads(json_part)
    assert summary["stage"] == "post-drop-readback"
    assert summary["exit_classification"] == "failure"
    assert summary["valid_json"] is True
    assert summary["valid_graph"] is True
    assert summary["diagnostic_code"] == "storage-status-unavailable"
    assert summary["diagnostic_severity"] == "error"
    assert summary["diagnostic_message_matched"] is False
    assert "diag_code_missing" in summary["violated"]
    assert "diag_message_match" in summary["violated"]


def test_post_drop_readback_failure_summary_handles_malformed_and_unknown_shapes() -> None:
    unknown_payload = {
        "command": "unexpected-cmd",
        "result": "unrecognized-result",
        "graph": {
            "result": "unexpected",
            "db_checked": "not-a-bool",
            "repository_exists": "not-a-bool",
            "diagnostics": [
                {
                    "code": "arbitrary-attacker-supplied-code",
                    "severity": "catastrophic",
                    "message": "custom message",
                }
            ],
        },
    }
    with pytest.raises(RuntimeError) as exc_info:
        validate_target_database_absent(_completed(2, unknown_payload))

    message = str(exc_info.value)
    assert "arbitrary-attacker-supplied-code" not in message
    assert "catastrophic" not in message
    prefix, _, json_part = message.partition(": ")
    summary = json.loads(json_part)
    assert summary["exit_classification"] == "code_2"
    assert summary["result"] == "unknown"
    assert summary["graph_result"] == "unknown"
    assert summary["diagnostic_code"] == "unknown"
    assert summary["diagnostic_severity"] == "unknown"
    assert summary["db_checked"] is None
    assert summary["repository_exists"] is None


@pytest.mark.parametrize(
    "raw_stdout",
    (
        "",
        "not json at all",
        "[]",
        "123",
        '{"graph": null}',
        '{"graph": {"diagnostics": "not-a-list"}}',
    ),
)
def test_post_drop_readback_failure_summary_handles_invalid_json(raw_stdout: str) -> None:
    proc = subprocess.CompletedProcess(("python", "-m", "repomap_kg"), 1, raw_stdout, "")
    with pytest.raises(RuntimeError, match="product command did not prove typed target absence"):
        validate_target_database_absent(proc)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (
        ("result", ["unhashable", "list"]),
        ("result", {"nested": "dict"}),
        ("result", 42),
        ("graph_result", ["nested", "list"]),
        ("graph_result", {"dict": True}),
        ("diag_code", ["code_list"]),
        ("diag_code", {"code": "dict"}),
        ("diag_severity", ["sev_list"]),
        ("diag_severity", {"sev": "dict"}),
        ("diagnostics_non_list", "not-a-list"),
    ),
)
def test_post_drop_readback_failure_summary_handles_wrong_type_members(
    field: str,
    bad_value: Any,
) -> None:
    payload: dict[str, Any] = {
        "command": "graph-summary",
        "result": "failure",
        "graph": {
            "result": "failure",
            "db_checked": True,
            "repository_exists": False,
            "diagnostics": [
                {
                    "code": "storage-status-unavailable",
                    "severity": "error",
                    "message": "some error message",
                }
            ],
        },
    }
    if field == "result":
        payload["result"] = bad_value
    elif field == "graph_result":
        payload["graph"]["result"] = bad_value
    elif field == "diag_code":
        payload["graph"]["diagnostics"][0]["code"] = bad_value
    elif field == "diag_severity":
        payload["graph"]["diagnostics"][0]["severity"] = bad_value
    elif field == "diagnostics_non_list":
        payload["graph"]["diagnostics"] = bad_value

    with pytest.raises(RuntimeError) as exc_info:
        validate_target_database_absent(_completed(1, payload))

    message = str(exc_info.value)
    assert "product command did not prove typed target absence:" in message
    prefix, _, json_part = message.partition(": ")
    summary = json.loads(json_part)
    assert summary["stage"] == "post-drop-readback"
    assert summary["exit_classification"] == "failure"
    assert summary["valid_json"] is True
    if field == "result":
        assert summary["result"] == "unknown"
    elif field == "graph_result":
        assert summary["graph_result"] == "unknown"
    elif field == "diag_code":
        assert summary["diagnostic_code"] == "unknown"
    elif field == "diag_severity":
        assert summary["diagnostic_severity"] == "unknown"
    elif field == "diagnostics_non_list":
        assert summary["diagnostics_count"] == 0
