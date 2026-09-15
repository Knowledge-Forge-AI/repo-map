"""Stdlib-only v1 schema, persistence, and manager validation; CLI: staging_report_contract.py --report PATH --commit SHA --source-sha256 SHA --invocation-id UUIDHEX."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn
from runner_integration_obligations import MAINTAINED_ABRUPT_DECLARATIONS
SCHEMA = "repomap-staging-obligations-v1"
POLICY = "ADR0067-PR26-STAGING-CONTRACT1-v1"
STAGING_REPORT_SCHEMA_VERSION = SCHEMA
MIN_COVERAGE = 80.0
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UUID_HEX = re.compile(r"^[0-9a-f]{32}$")
_PARTS = ("collected", "required", "measured", "abrupt", "deferred")
_SMOKE = frozenset(("passed", "failed", "not_required", "blocked"))
_LEGS = frozenset(("passed", "failed", "blocked", "not_selected"))
_MEASURE = frozenset(("measured", "disabled", "incomplete", "unavailable"))
_TEST = frozenset(("passed", "failed", "skipped", "deselected", "not_run", "xfailed", "xpassed"))
_TOP = frozenset(("schema", "policy", "invocation_id", "candidate", "partition", "scoped", "coverage_enabled", "smoke", "go_coverage", "legs", "errors"))
_LEG = frozenset(("status", "pytest_exit", "planned", "records", "completed", "measurement", "abrupt_roles", "cleanup"))
_RECORD = frozenset(("test_id", "test_file", "status", "duration_seconds", "message"))
_MEASUREMENT = frozenset(("state", "valid", "summary", "session_id"))
_ROLE = frozenset(("nodeid", "role", "invocation_id", "source_sha256", "launch_id", "pid", "parent_pid", "started_ns", "checkpoint", "returncode", "settled_ns", "cleanup", "measurement"))
_SUMMARY = frozenset(("suite_name", "line_hard_threshold", "branch_hard_threshold", "line_warn_threshold", "branch_warn_threshold", "total_lines", "covered_lines", "line_percent", "total_branches", "covered_branches", "branch_percent", "files"))
_FILE = frozenset(("path", "executable_lines", "covered_lines", "line_percent", "total_branches", "covered_branches", "branch_percent"))
_GO = frozenset(("suite_name", "hard_threshold", "total_statements", "covered_statements", "statement_percent", "branch_status", "diagnostic_category"))
class StagingReportValidationError(ValueError):
    """Report schema, identity, or accounting evidence is invalid."""
ReportValidationError = StagingReportValidationError
def _bad(message: str) -> NoReturn:
    raise StagingReportValidationError(message)
def _obj(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _bad(f"{label} must be an object")
    return value
def _fields(value: Mapping[str, Any], required: frozenset[str], label: str) -> None:
    missing, extra = required - set(value), set(value) - required
    if missing:
        _bad(f"{label} missing {sorted(missing)}")
    if extra:
        _bad(f"{label} contains unknown fields {sorted(extra)}")
def _str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        _bad(f"{label} must be a non-empty string")
    return value
def _int(value: Any, label: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or minimum is not None and value < minimum:
        _bad(f"{label} must be an integer" if minimum is None else f"{label} must be an integer >= {minimum}")
    return value
def _num(value: Any, label: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        _bad(f"{label} must be a finite number")
    number = float(value)
    if minimum is not None and number < minimum or maximum is not None and number > maximum:
        _bad(f"{label} is outside its allowed range")
    return number
def _nodes(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        _bad(f"{label} must be an array")
    result = [_str(item, f"{label}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)) or any("*" in item or "?" in item for item in result):
        _bad(f"{label} contains duplicate IDs or glob selectors")
    return result
def _json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
def digest_partition(partition: Mapping[str, Any]) -> str:
    """Hash only ordered population fields; policy/candidate bind at the root."""
    part = _obj(partition, "partition")
    canonical: dict[str, list[str]] = {}
    for field in _PARTS:
        if field not in part or not isinstance(part[field], list):
            _bad(f"partition.{field} must be an array")
        canonical[field] = list(part[field])
    return hashlib.sha256(_json(canonical)).hexdigest()
def _decl(value: Any) -> Mapping[str, Any]:
    getter = value.get if isinstance(value, Mapping) else lambda name, default=None: getattr(value, name, default)
    nodeid, role = _str(getter("nodeid"), "declaration.nodeid"), _str(getter("role"), "declaration.role")
    expected = getter("expected_returncode", getter("expected_exit_code"))
    owner = getter("launch_owner", "")
    _str(owner, f"declaration {nodeid} launch_owner")
    return {"nodeid": nodeid, "role": role, "expected_returncode": _int(expected, "declaration.expected_returncode"), "checkpoint": _str(getter("checkpoint"), "declaration.checkpoint"), "launch_owner": owner}
def _declarations() -> tuple[Mapping[str, Any], ...]:
    result = tuple(_decl(value) for value in MAINTAINED_ABRUPT_DECLARATIONS)
    if not result or len({item["nodeid"] for item in result}) != len(result):
        _bad("maintained abrupt declarations are empty or duplicated")
    return result
def _summary(value: Any) -> None:
    summary = _obj(value, "M measurement.summary")
    _fields(summary, _SUMMARY, "M measurement.summary")
    _str(summary["suite_name"], "M summary.suite_name")
    for field in ("line_hard_threshold", "branch_hard_threshold"):
        _num(summary[field], f"M summary.{field}", MIN_COVERAGE, 100.0)
    for field in ("line_warn_threshold", "branch_warn_threshold"):
        _num(summary[field], f"M summary.{field}", 0.0, 100.0)
    for field in ("total_lines", "covered_lines", "total_branches", "covered_branches"):
        _int(summary[field], f"M summary.{field}", 0)
    if summary["covered_lines"] > summary["total_lines"] or summary["covered_branches"] > summary["total_branches"]:
        _bad("M coverage count exceeds denominator")
    line = _num(summary["line_percent"], "M summary.line_percent", 0.0, 100.0)
    branch = _num(summary["branch_percent"], "M summary.branch_percent", 0.0, 100.0)
    expected_line = 100 * summary["covered_lines"] / summary["total_lines"] if summary["total_lines"] else 0.0
    expected_branch = 100 * summary["covered_branches"] / summary["total_branches"] if summary["total_branches"] else 0.0
    if not math.isclose(line, expected_line, abs_tol=0.11) or not math.isclose(branch, expected_branch, abs_tol=0.11):
        _bad("M coverage percentage does not match counts")
    if not isinstance(summary["files"], list):
        _bad("M summary.files must be an array")
    seen_paths: set[str] = set()
    totals = [0, 0, 0, 0]
    for index, item in enumerate(summary["files"]):
        record = _obj(item, f"M summary.files[{index}]")
        _fields(record, _FILE, f"M summary.files[{index}]")
        path = Path(_str(record["path"], "M summary file path"))
        canonical_path = str(path)
        if path.is_absolute() or ".." in path.parts:
            _bad("M summary file paths must be relative")
        if canonical_path in seen_paths:
            _bad("M summary file paths must be unique")
        seen_paths.add(canonical_path)
        counts = [_int(record[field], f"M summary.files[{index}].{field}", 0) for field in ("executable_lines", "covered_lines", "total_branches", "covered_branches")]
        if counts[1] > counts[0] or counts[3] > counts[2]:
            _bad("M summary file coverage exceeds its denominator")
        for offset, field in enumerate(("line_percent", "branch_percent")):
            percent = _num(record[field], f"M summary.files[{index}].{field}", 0.0, 100.0)
            denominator, numerator = counts[offset * 2], counts[offset * 2 + 1]
            expected = 100 * numerator / denominator if denominator else 0.0
            if not math.isclose(percent, expected, abs_tol=0.11):
                _bad("M summary file percentage does not match counts")
        totals = [left + right for left, right in zip(totals, counts)]
    if totals != [summary[field] for field in ("total_lines", "covered_lines", "total_branches", "covered_branches")]:
        _bad("M summary files do not reconcile aggregate counts")

def _measurement(value: Any, *, label: str, leg: str, coverage: bool) -> Mapping[str, Any]:
    result = _obj(value, label)
    _fields(result, _MEASUREMENT, label)
    state = _str(result["state"], f"{label}.state")
    if state not in _MEASURE or not isinstance(result["valid"], bool):
        _bad(f"{label} has invalid state or valid flag")
    session_id = result["session_id"]
    if session_id is not None and (not isinstance(session_id, str) or not session_id):
        _bad(f"{label}.session_id must be a non-empty string or null")
    if not coverage and session_id is not None:
        _bad(f"{label}.session_id must be null when coverage is disabled")
    summary = result["summary"]
    if summary is not None:
        _summary(summary)
    if leg == "M":
        if coverage and state == "disabled" or not coverage and state != "disabled":
            _bad("M measurement state disagrees with coverage_enabled")
        if state == "measured" and summary is None or state not in ("measured", "disabled") and result["valid"]:
            _bad("M measurement validity does not match its state")
    elif state != "unavailable" or summary is not None:
        _bad("A measurement must be unavailable with no summary")
    return result
def _records(value: Any, planned: list[str], label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        _bad(f"{label}.records must be an array")
    result: list[Mapping[str, Any]] = []
    ids: list[str] = []
    for index, item in enumerate(value):
        record = _obj(item, f"{label}.records[{index}]")
        _fields(record, _RECORD, f"{label}.records[{index}]")
        test_id, test_file = _str(record["test_id"], "record.test_id"), _str(record["test_file"], "record.test_file")
        if test_file != test_id.split("::", 1)[0] or _str(record["status"], "record.status") not in _TEST:
            _bad(f"{label} record has inconsistent test identity or status")
        _num(record["duration_seconds"], "record.duration_seconds", 0.0)
        if not isinstance(record["message"], str):
            _bad("record.message must be a string")
        ids.append(test_id)
        result.append(record)
    if ids != planned or len(ids) != len(set(ids)):
        _bad(f"{label}.records must exactly cover planned nodes in order")
    return result
def _roles(value: Any, planned: list[str], invocation: str, source: str, declarations: Mapping[str, Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        _bad("A.abrupt_roles must be an array")
    result: list[Mapping[str, Any]] = []
    ids: list[str] = []
    launches: list[str] = []
    pids: list[int] = []
    for item in value:
        role = _obj(item, "A.abrupt_role")
        _fields(role, _ROLE, "A.abrupt_role")
        nodeid = _str(role["nodeid"], "A role.nodeid")
        declaration = declarations.get(nodeid)
        if declaration is None:
            _bad(f"A role is not an exact maintained declaration: {nodeid}")
        if role["role"] != declaration["role"] or role["checkpoint"] != declaration["checkpoint"]:
            _bad(f"A role declaration mismatch: {nodeid}")
        if role["invocation_id"] != invocation or role["source_sha256"] != source:
            _bad(f"A role identity mismatch: {nodeid}")
        launch = _str(role["launch_id"], "A role.launch_id")
        pid, parent = _int(role["pid"], "A role.pid", 1), _int(role["parent_pid"], "A role.parent_pid", 1)
        start, settled = _int(role["started_ns"], "A role.started_ns", 1), _int(role["settled_ns"], "A role.settled_ns", 1)
        if pid == parent or settled < start or role["returncode"] != declaration["expected_returncode"] or role["measurement"] != "unavailable" or not isinstance(role["cleanup"], bool):
            _bad(f"A role lifecycle evidence is invalid: {nodeid}")
        ids.append(nodeid); launches.append(launch); pids.append(pid); result.append(role)
    if ids != planned or len(ids) != len(set(ids)) or len(launches) != len(set(launches)) or len(pids) != len(set(pids)):
        _bad("A roles must exactly cover planned nodes with unique launch evidence")
    return result
def _leg(value: Any, planned: list[str], label: str, coverage: bool, invocation: str, source: str, declarations: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    leg = _obj(value, label); _fields(leg, _LEG, label)
    status = _str(leg["status"], f"{label}.status")
    if status not in _LEGS or leg["pytest_exit"] is not None and (isinstance(leg["pytest_exit"], bool) or not isinstance(leg["pytest_exit"], int)):
        _bad(f"{label} has invalid status or pytest exit")
    selected = _nodes(leg["planned"], f"{label}.planned")
    if selected != planned:
        _bad(f"{label}.planned does not match the sealed partition")
    records = _records(leg["records"], planned, label)
    completed = _nodes(leg["completed"], f"{label}.completed")
    if completed != planned:
        _bad(f"{label}.completed must cover every planned teardown")
    measurement = _measurement(leg["measurement"], label=f"{label}.measurement", leg=label, coverage=coverage)
    if coverage and planned and status in ("passed", "failed") and not measurement["session_id"]:
        _bad(f"{label} executed without a coverage session identity")
    roles = _roles(leg["abrupt_roles"], planned, invocation, source, declarations) if label == "A" else []
    if label == "M" and leg["abrupt_roles"]:
        _bad("M cannot contain abrupt roles")
    cleanup = leg["cleanup"]
    if cleanup not in ("passed", "failed", "unknown"):
        _bad(f"{label}.cleanup is invalid")
    if status == "not_selected":
        if planned or records or completed or roles or leg["pytest_exit"] is not None:
            _bad(f"{label} not_selected contains execution evidence")
    elif not planned:
        _bad(f"{label} is selected with an empty population")
    if status == "passed":
        valid_without_coverage = label == "M" and not coverage and measurement["state"] == "disabled"
        invalid_record = any(item["status"] != "passed" and (label != "M" or item["status"] != "skipped" or not item["message"].strip()) for item in records)
        if leg["pytest_exit"] != 0 or invalid_record or cleanup != "passed" or not (measurement["valid"] or valid_without_coverage) or any(not item["cleanup"] for item in roles):
            _bad(f"{label} passed status contradicts evidence")
    return leg

def _go_summary(value: Any) -> None:
    if value is None:
        return
    summary = _obj(value, "go_coverage"); _fields(summary, _GO, "go_coverage")
    _str(summary["suite_name"], "go_coverage.suite_name")
    _num(summary["hard_threshold"], "go_coverage.hard_threshold", MIN_COVERAGE, 100.0)
    total = _int(summary["total_statements"], "go_coverage.total_statements", 0)
    covered = _int(summary["covered_statements"], "go_coverage.covered_statements", 0)
    if covered > total:
        _bad("go_coverage covered statements exceed denominator")
    percent = _num(summary["statement_percent"], "go_coverage.statement_percent", 0.0, 100.0)
    if not math.isclose(percent, 100.0 * covered / total if total else 0.0, abs_tol=0.11):
        _bad("go_coverage percentage does not match counts")
    _str(summary["branch_status"], "go_coverage.branch_status")
    if not isinstance(summary["diagnostic_category"], str):
        _bad("go_coverage.diagnostic_category must be a string")

def validate_report(payload: Mapping[str, Any], *, expected_commit: str | None = None, expected_source_sha256: str | None = None, expected_invocation_id: str | None = None, declarations: Sequence[Any] | None = None) -> None:
    """Raise ValueError unless root identity, accounting, and both legs are exact."""
    report = _obj(payload, "report"); _fields(report, _TOP, "report")
    if report["schema"] != SCHEMA or report["policy"] != POLICY:
        _bad("unsupported schema or policy")
    invocation = _str(report["invocation_id"], "invocation_id")
    if not _UUID_HEX.fullmatch(invocation):
        _bad("invocation_id must be lowercase UUID hex")
    candidate = _obj(report["candidate"], "candidate"); _fields(candidate, frozenset(("commit", "source_sha256")), "candidate")
    commit, source = _str(candidate["commit"], "candidate.commit"), _str(candidate["source_sha256"], "candidate.source_sha256")
    if not _HEX64.fullmatch(source):
        _bad("candidate.source_sha256 must be lowercase SHA-256")
    if expected_commit is not None and commit != expected_commit or expected_source_sha256 is not None and source != expected_source_sha256 or expected_invocation_id is not None and invocation != expected_invocation_id:
        _bad("report identity does not match manager expectation")
    if not isinstance(report["scoped"], bool) or not isinstance(report["coverage_enabled"], bool):
        _bad("scoped and coverage_enabled must be booleans")
    if _str(report["smoke"], "smoke") not in _SMOKE or not isinstance(report["errors"], list) or any(not isinstance(item, str) or not item or len(item) > 512 for item in report["errors"]):
        _bad("smoke or errors is invalid")
    _go_summary(report["go_coverage"])
    partition = _obj(report["partition"], "partition"); _fields(partition, frozenset((*_PARTS, "sha256")), "partition")
    values = {field: _nodes(partition[field], f"partition.{field}") for field in _PARTS}
    collected, required, measured, abrupt, deferred = (values[field] for field in _PARTS)
    measured_set, abrupt_set = set(measured), set(abrupt)
    required_set, deferred_set, collected_set = set(required), set(deferred), set(collected)
    if required_set & deferred_set or collected_set != required_set | deferred_set or required != [node for node in collected if node not in deferred_set] or deferred != [node for node in collected if node in deferred_set] or measured_set & abrupt_set or measured_set | abrupt_set != required_set:
        _bad("partition is not disjoint, exhaustive, or explicitly deferred")
    if measured != [node for node in required if node in measured_set] or abrupt != [node for node in required if node in abrupt_set]:
        _bad("partition M/A order does not follow required population")
    if not isinstance(partition["sha256"], str) or not _HEX64.fullmatch(partition["sha256"]) or partition["sha256"] != digest_partition(partition):
        _bad("partition.sha256 is invalid")
    if not report["scoped"] and (not measured or not abrupt):
        _bad("unscoped report requires non-empty M and A")
    declared = tuple(_decl(item) for item in (declarations if declarations is not None else _declarations()))
    declaration_map = {item["nodeid"]: item for item in declared}
    expected_abrupt = [node for node in required if node in declaration_map]
    if len(declaration_map) != len(declared) or abrupt != expected_abrupt or not report["scoped"] and set(declaration_map) != set(abrupt):
        _bad("abrupt population does not match exact maintained declarations")
    legs = _obj(report["legs"], "legs"); _fields(legs, frozenset(("M", "A")), "legs")
    m_leg = _leg(legs["M"], measured, "M", report["coverage_enabled"], invocation, source, declaration_map)
    a_leg = _leg(legs["A"], abrupt, "A", report["coverage_enabled"], invocation, source, declaration_map)
    m_session, a_session = m_leg["measurement"]["session_id"], a_leg["measurement"]["session_id"]
    if m_session is not None and m_session == a_session:
        _bad("M and A coverage sessions must be distinct")

def _semantics(payload: Mapping[str, Any], diagnostic: bool, declarations: Sequence[Any] | None = None) -> bool:
    try:
        validate_report(payload, declarations=declarations)
    except (TypeError, ValueError):
        return False
    if payload["errors"] or payload["smoke"] not in ({"passed", "not_required"} if diagnostic else {"passed"}):
        return False
    partition, legs = payload["partition"], payload["legs"]
    if not partition["required"] or partition["measured"] and legs["M"]["status"] != "passed" or partition["abrupt"] and legs["A"]["status"] != "passed":
        return False
    if diagnostic and not (partition["measured"] or partition["abrupt"]):
        return False
    if payload["coverage_enabled"] and partition["measured"]:
        measurement = legs["M"]["measurement"]; summary = measurement["summary"]
        go = payload["go_coverage"]
        if measurement["state"] != "measured" or not measurement["valid"] or summary is None or summary["line_percent"] < summary["line_hard_threshold"] or summary["branch_percent"] < summary["branch_hard_threshold"] or go is None or go["total_statements"] <= 0 or go["covered_statements"] / go["total_statements"] * 100.0 < go["hard_threshold"]:
            return False
    if not diagnostic and (payload["scoped"] or not payload["coverage_enabled"]):
        return False
    return True

validate_staging_report = validate_report
def qualifies(payload: Mapping[str, Any], *, declarations: Sequence[Any] | None = None) -> bool:
    return _semantics(payload, False, declarations)

def execution_succeeded(payload: Mapping[str, Any], *, declarations: Sequence[Any] | None = None) -> bool:
    return _semantics(payload, True, declarations)

def persist_report(path: Path | str, payload: Mapping[str, Any], *, validate: bool = False) -> Path:
    """Atomically persist even incomplete observations; manager validates later."""
    if not isinstance(payload, Mapping):
        _bad("report payload must be an object")
    if validate:
        validate_report(payload)
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"; temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
            temporary = stream.name; stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, target); temporary = None
        try:
            directory = os.open(target.parent, os.O_RDONLY)
        except OSError:
            directory = -1
        if directory >= 0:
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return target
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


persist_staging_report = persist_report

def load_report(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        _bad("report JSON root must be an object")
    return value

def validate_manager_report(path: Path | str, *, expected_commit: str, expected_source_sha256: str, expected_invocation_id: str, declarations: Sequence[Any] | None = None) -> dict[str, Any]:
    payload = load_report(path)
    validate_report(payload, expected_commit=expected_commit, expected_source_sha256=expected_source_sha256, expected_invocation_id=expected_invocation_id, declarations=declarations)
    return payload

def build_staging_report(payload: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """Return observed fields only; no identity or lifecycle defaults are supplied."""
    if payload is not None:
        return dict(payload)
    if not set(_TOP) <= kwargs.keys():
        _bad("build_staging_report requires every v1 report field")
    return {field: kwargs[field] for field in _TOP}

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a RepoMap PR26 staging report")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--commit", "--expected-commit", dest="commit", required=True)
    parser.add_argument("--source-sha256", "--expected-source-sha256", dest="source", required=True)
    parser.add_argument("--invocation-id", "--expected-invocation-id", dest="invocation", required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = validate_manager_report(args.report, expected_commit=args.commit, expected_source_sha256=args.source, expected_invocation_id=args.invocation)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"staging report validation failed: {error}", file=sys.stderr); return 2
    result = {"schema": SCHEMA, "qualified": qualifies(payload), "execution_succeeded": execution_succeeded(payload)}
    print(json.dumps(result, sort_keys=True)); return 0 if args.validate_only or result["qualified"] else 1

__all__ = ("MAINTAINED_ABRUPT_DECLARATIONS", "POLICY", "SCHEMA", "STAGING_REPORT_SCHEMA_VERSION", "StagingReportValidationError", "ReportValidationError", "build_staging_report", "digest_partition", "execution_succeeded", "load_report", "main", "persist_report", "persist_staging_report", "qualifies", "validate_manager_report", "validate_report", "validate_staging_report")

if __name__ == "__main__":
    raise SystemExit(main())
