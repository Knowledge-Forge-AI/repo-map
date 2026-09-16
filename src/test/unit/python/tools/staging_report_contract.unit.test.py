"""Pure contract tests for the PR26 paired-obligation report."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import staging_report_contract as contract

from staging_report_contract import (
    POLICY,
    SCHEMA,
    digest_partition,
    execution_succeeded,
    load_report,
    main,
    persist_report,
    qualifies,
    validate_manager_report,
    validate_report,
)


DECLARATION: dict[str, Any] = {"nodeid": "a.py::test_a", "role": "a-role", "expected_returncode": 17, "checkpoint": "checkpoint", "launch_owner": "owner"}
DECLARATIONS = (DECLARATION,)
INVOCATION = "e" * 32
SOURCE = "d" * 64
COMMIT = "c" * 40
M_NODE = "m.py::test_m"
A_NODE = DECLARATION["nodeid"]


def _record(nodeid: str, status: str = "passed") -> dict[str, Any]:
    return {
        "test_id": nodeid,
        "test_file": nodeid.split("::", 1)[0],
        "status": status,
        "duration_seconds": 0.25,
        "message": "",
    }


def _summary(line: float = 100.0, branch: float = 100.0) -> dict[str, Any]:
    return {
        "suite_name": "staging",
        "line_hard_threshold": 80.0,
        "branch_hard_threshold": 80.0,
        "line_warn_threshold": 85.0,
        "branch_warn_threshold": 85.0,
        "total_lines": 100,
        "covered_lines": int(line),
        "line_percent": line,
        "total_branches": 100,
        "covered_branches": int(branch),
        "branch_percent": branch,
        "files": [{
            "path": "src/example.py",
            "executable_lines": 100,
            "covered_lines": int(line),
            "line_percent": line,
            "total_branches": 100,
            "covered_branches": int(branch),
            "branch_percent": branch,
        }],
    }


def _role() -> dict[str, Any]:
    return {
        "nodeid": A_NODE,
        "role": "a-role",
        "invocation_id": INVOCATION,
        "source_sha256": SOURCE,
        "launch_id": "launch-a",
        "pid": 101,
        "parent_pid": 100,
        "started_ns": 10,
        "checkpoint": "checkpoint",
        "returncode": 17,
        "settled_ns": 20,
        "cleanup": True,
        "measurement": "unavailable",
    }


def _partition(*, measured: list[str] | None = None, abrupt: list[str] | None = None, deferred: list[str] | None = None) -> dict[str, Any]:
    measured = [M_NODE] if measured is None else measured
    abrupt = [A_NODE] if abrupt is None else abrupt
    deferred = [] if deferred is None else deferred
    required = [*measured, *abrupt]
    value: dict[str, Any] = {
        "collected": [*required, *deferred],
        "required": required,
        "measured": measured,
        "abrupt": abrupt,
        "deferred": deferred,
    }
    value["sha256"] = digest_partition(value)
    return value


def _leg(nodeids: list[str], *, abrupt: bool, coverage: bool, status: str = "passed", records: list[dict[str, Any]] | None = None, cleanup: str = "passed", role_cleanup: bool = True) -> dict[str, Any]:
    records = [_record(nodeid) for nodeid in nodeids] if records is None else records
    measurement: dict[str, Any]
    if abrupt:
        role = _role()
        role["cleanup"] = role_cleanup
        measurement = {"state": "unavailable", "valid": role_cleanup, "summary": None, "session_id": "session-a"}
        roles = [role] if nodeids else []
    elif coverage:
        measurement = {"state": "measured", "valid": True, "summary": _summary(), "session_id": "session-m"}
        roles = []
    else:
        measurement = {"state": "disabled", "valid": False, "summary": None, "session_id": None}
        roles = []
    return {
        "status": status,
        "pytest_exit": 0 if status in {"passed", "not_selected"} else 1,
        "planned": nodeids,
        "records": records,
        "completed": nodeids,
        "measurement": measurement,
        "abrupt_roles": roles,
        "cleanup": cleanup,
    }


def _report(*, scoped: bool = False, coverage: bool = True, smoke: str = "passed", partition: dict[str, Any] | None = None) -> dict[str, Any]:
    partition = _partition() if partition is None else partition
    measured = list(partition["measured"])
    abrupt = list(partition["abrupt"])
    return {
        "schema": SCHEMA,
        "policy": POLICY,
        "invocation_id": INVOCATION,
        "candidate": {"commit": COMMIT, "source_sha256": SOURCE},
        "partition": partition,
        "scoped": scoped,
        "coverage_enabled": coverage,
        "smoke": smoke,
        "go_coverage": None if not coverage else {
            "suite_name": "staging",
            "hard_threshold": 80.0,
            "total_statements": 100,
            "covered_statements": 100,
            "statement_percent": 100.0,
            "branch_status": "N/A",
            "diagnostic_category": "",
        },
        "legs": {
            "M": _leg(measured, abrupt=False, coverage=coverage) if measured else _leg([], abrupt=False, coverage=coverage, status="not_selected"),
            "A": _leg(abrupt, abrupt=True, coverage=coverage) if abrupt else {
                "status": "not_selected",
                "pytest_exit": None,
                "planned": [],
                "records": [],
                "completed": [],
                "measurement": {"state": "unavailable", "valid": False, "summary": None, "session_id": None},
                "abrupt_roles": [],
                "cleanup": "passed",
            },
        },
        "errors": [],
    }


def test_full_report_validates_and_qualifies() -> None:
    report = _report()
    validate_report(report, declarations=DECLARATIONS)
    assert qualifies(report, declarations=DECLARATIONS)
    assert execution_succeeded(report, declarations=DECLARATIONS)


def test_partition_digest_is_ordered_and_rejects_overlap() -> None:
    report = _report()
    report["partition"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="partition.sha256"):
        validate_report(report, declarations=DECLARATIONS)
    report = _report(partition=_partition(measured=[M_NODE], abrupt=[M_NODE]))
    with pytest.raises(ValueError, match="duplicate"):
        validate_report(report, declarations=DECLARATIONS)


def test_partition_requires_ordered_population_and_selected_abrupt_subset() -> None:
    report = _report()
    report["partition"]["collected"] = [A_NODE, M_NODE]
    report["partition"]["sha256"] = digest_partition(report["partition"])
    with pytest.raises(ValueError, match="not disjoint"):
        validate_report(report, declarations=DECLARATIONS)
    scoped = _report(scoped=True, partition=_partition(measured=[A_NODE, M_NODE], abrupt=[]))
    with pytest.raises(ValueError, match="abrupt population"):
        validate_report(scoped, declarations=DECLARATIONS)
    deferred = "deferred.py::test_d"
    partition = _partition(deferred=[deferred])
    partition["collected"] = [M_NODE, deferred, A_NODE]
    partition["sha256"] = digest_partition(partition)
    interleaved = _report(partition=partition)
    validate_report(interleaved, declarations=DECLARATIONS)


def test_runtime_skip_is_structural_evidence_without_failing_suite_policy() -> None:
    report = _report()
    report["legs"]["M"]["records"] = [_record(M_NODE, "skipped")]
    report["legs"]["M"]["records"][0]["message"] = "platform opt-in unavailable"
    validate_report(report, declarations=DECLARATIONS)
    assert execution_succeeded(report, declarations=DECLARATIONS)
    assert qualifies(report, declarations=DECLARATIONS)


def test_diagnostic_success_still_requires_measured_floors() -> None:
    report = _report()
    report["legs"]["M"]["measurement"]["summary"] = _summary(79.0, 100.0)
    assert not execution_succeeded(report, declarations=DECLARATIONS)


def test_summary_files_are_closed_and_safe() -> None:
    report = _report()
    report["legs"]["M"]["measurement"]["summary"]["files"][0]["path"] = "../escape.py"
    with pytest.raises(ValueError, match="relative"):
        validate_report(report, declarations=DECLARATIONS)
    report = _report()
    file_record = copy.deepcopy(report["legs"]["M"]["measurement"]["summary"]["files"][0])
    report["legs"]["M"]["measurement"]["summary"]["files"].append(file_record)
    with pytest.raises(ValueError, match="unique"):
        validate_report(report, declarations=DECLARATIONS)
    report = _report()
    report["legs"]["M"]["measurement"]["summary"]["total_lines"] = 101
    report["legs"]["M"]["measurement"]["summary"]["line_percent"] = 100 * 100 / 101
    with pytest.raises(ValueError, match="reconcile"):
        validate_report(report, declarations=DECLARATIONS)


@pytest.mark.parametrize("field", ["schema", "policy", "invocation_id", "candidate", "partition", "go_coverage", "legs", "errors"])
def test_required_root_fields_are_closed(field: str) -> None:
    report = _report()
    del report[field]
    with pytest.raises(ValueError, match="missing"):
        validate_report(report, declarations=DECLARATIONS)


def test_wrong_role_identity_or_returncode_never_passes() -> None:
    report = _report()
    report["legs"]["A"]["abrupt_roles"][0]["returncode"] = 18
    assert not qualifies(report, declarations=DECLARATIONS)
    with pytest.raises(ValueError, match="lifecycle"):
        validate_report(report, declarations=DECLARATIONS)


def test_failed_and_skipped_evidence_is_retained_but_not_success() -> None:
    report = _report()
    report["errors"] = ["M:assertion"]
    report["legs"]["M"] = _leg([M_NODE], abrupt=False, coverage=True, status="failed", records=[_record(M_NODE, "skipped")])
    validate_report(report, declarations=DECLARATIONS)
    assert not qualifies(report, declarations=DECLARATIONS)
    assert not execution_succeeded(report, declarations=DECLARATIONS)


def test_unsafe_abrupt_cleanup_is_valid_failure_evidence() -> None:
    report = _report()
    report["errors"] = ["A:cleanup"]
    report["legs"]["A"] = _leg([A_NODE], abrupt=True, coverage=True, status="failed", cleanup="failed", role_cleanup=False)
    validate_report(report, declarations=DECLARATIONS)
    assert not qualifies(report, declarations=DECLARATIONS)


def test_enabled_legs_require_distinct_session_ids() -> None:
    report = _report()
    report["legs"]["A"]["measurement"]["session_id"] = "session-m"
    with pytest.raises(ValueError, match="distinct"):
        validate_report(report, declarations=DECLARATIONS)
    report = _report()
    report["legs"]["M"]["measurement"]["session_id"] = None
    with pytest.raises(ValueError, match="session identity"):
        validate_report(report, declarations=DECLARATIONS)


def test_go_summary_is_independent_qualification_evidence() -> None:
    report = _report()
    report["go_coverage"]["covered_statements"] = 79
    report["go_coverage"]["statement_percent"] = 79.0
    validate_report(report, declarations=DECLARATIONS)
    assert not qualifies(report, declarations=DECLARATIONS)


def test_scoped_no_coverage_can_report_behavior_success() -> None:
    partition = _partition(measured=[M_NODE], abrupt=[], deferred=[])
    report = _report(scoped=True, coverage=False, smoke="not_required", partition=partition)
    validate_report(report, declarations=DECLARATIONS)
    assert execution_succeeded(report, declarations=DECLARATIONS)
    assert not qualifies(report, declarations=DECLARATIONS)


def test_manager_identity_is_external_to_payload(tmp_path: Path) -> None:
    report = _report()
    path = tmp_path / "report.json"
    persist_report(path, report)
    assert validate_manager_report(path, expected_commit=COMMIT, expected_source_sha256=SOURCE, expected_invocation_id=INVOCATION, declarations=DECLARATIONS) == report
    with pytest.raises(ValueError, match="identity"):
        validate_manager_report(path, expected_commit="f" * 40, expected_source_sha256=SOURCE, expected_invocation_id=INVOCATION, declarations=DECLARATIONS)


def test_persist_keeps_incomplete_observation_without_accepting_it(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.json"
    incomplete = {"schema": SCHEMA, "errors": ["collection:blocked"], "partition": {}}
    persist_report(path, incomplete)
    assert load_report(path) == incomplete
    assert not qualifies(incomplete)
    assert not list(tmp_path.glob(".*.tmp"))


def test_manager_cli_requires_expected_identities(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    report = _report()
    path = tmp_path / "report.json"
    persist_report(path, report)
    monkeypatch.setattr(contract, "MAINTAINED_ABRUPT_DECLARATIONS", DECLARATIONS)
    assert main(["--report", str(path), "--commit", COMMIT, "--source-sha256", SOURCE, "--invocation-id", INVOCATION]) == 0
    assert json.loads(capsys.readouterr().out)["qualified"] is True
    assert main(["--report", str(path), "--commit", "f" * 40, "--source-sha256", SOURCE, "--invocation-id", INVOCATION]) == 2


def test_missing_or_duplicate_records_are_rejected() -> None:
    report = _report()
    report["legs"]["M"]["records"] = []
    with pytest.raises(ValueError, match="records"):
        validate_report(report, declarations=DECLARATIONS)
    report = _report()
    report["legs"]["M"]["records"].append(copy.deepcopy(report["legs"]["M"]["records"][0]))
    with pytest.raises(ValueError, match="records"):
        validate_report(report, declarations=DECLARATIONS)


def test_intentional_victim_diagnostic_snapshot_auditable_in_coverage_report() -> None:
    from test_report_coverage import coverage_diagnostics
    from runner_coverage_execution import ShardDiagnosticSnapshot

    class DummySession:
        diagnostic_snapshots = (
            ShardDiagnosticSnapshot(
                session_id="dummy-session",
                shard_name="intentional_victim.pid1234",
                file_type="intentional_victim",
                size_bytes=0,
                sha256=None,
                reader_status="intentional_victim_receipt_verified",
                stage="pre_combine",
                termination_outcome="intentional_victim_terminated",
                launch_role="intentional-victim",
                test_owner="e0d161f049355f99326012d6730a079fc946ea779313dddcc55c4d7e93a29fa6",
            ),
        )

    diagnostics = coverage_diagnostics(DummySession())
    assert len(diagnostics) == 1
    d = diagnostics[0]
    assert d["file_type"] == "intentional_victim"
    assert d["reader_status"] == "intentional_victim_receipt_verified"
    assert d["termination_outcome"] == "intentional_victim_terminated"
    assert d["launch_role"] == "intentional-victim"
