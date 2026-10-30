"""Diagnostic privacy, strict persistence and lack of qualification authority."""
from copy import deepcopy
import errno
import json
from pathlib import Path
from typing import Any

import pytest
import runner_failure_evidence as evidence
from staging_report_contract import execution_succeeded, qualifies, validate_report


def payload():
    return {"schema": evidence.FAILURE_SCHEMA, "invocation_id": "fixture-1",
            "candidate_at_start": None, "partition_state": "not_established",
            "execution_succeeded": False,
            "primary": evidence.error_record(ValueError("opaque-fixture"), "candidate_identity"),
            "secondary": [], "secondary_omitted": 0}


def test_error_projection_uses_builtin_slots_without_text_or_custom_properties():
    def refuse(_value):
        pytest.fail("custom exception text or descriptor evaluated")

    # Construct the deliberately incompatible descriptors dynamically: production
    # typing must not require writable built-in slots to become read-only properties.
    meta = type("Meta", (type,), {"__name__": property(refuse)})
    SecretError = meta("SecretError", (OSError,), {
        "errno": property(refuse), "__cause__": property(refuse), "__str__": refuse,
    })
    error = SecretError(errno.EIO, "opaque-fixture")
    cause = KeyError("opaque-fixture")
    BaseException.__dict__["__cause__"].__set__(error, cause)
    record = evidence.error_record(error, "source_verify")
    assert record == {"stage": "source_verify", "type": "SecretError", "errno": errno.EIO,
                      "causes": [{"type": "KeyError", "errno": None}], "causes_truncated": False}
    assert "opaque-fixture" not in json.dumps(record)


def test_cause_chain_cycles_and_limits_are_bounded():
    errors = [ValueError() for _ in range(8)]
    for left, right in zip(errors, errors[1:]):
        left.__cause__ = right
    record = evidence.error_record(errors[0], "discovery_collection")
    assert len(record["causes"]) == evidence.MAX_CAUSES and record["causes_truncated"]
    errors[0].__cause__ = errors[0]
    assert evidence.error_record(errors[0], "discovery_collection")["causes_truncated"]
    errors[0].__cause__ = None
    errors[0].__context__ = errors[1]
    errors[0].__suppress_context__ = True
    assert evidence.error_record(errors[0], "discovery_collection")["causes"] == []
    unusual = type("unbounded-" + "x" * 100, (Exception,), {})()
    assert evidence.error_record(unusual, "source_verify")["type"] == "Exception"


@pytest.mark.parametrize("fault", ["extra", "bool-errno", "stage", "type", "candidate", "success",
                                  "secondaries", "causes", "omitted", "invocation"])
def test_strict_diagnostic_schema_refuses_untrusted_fields(fault):
    value = payload()
    if fault == "extra":
        value["message"] = "opaque-fixture"
    elif fault in ("bool-errno", "stage", "type", "causes"):
        field, replacement = {"bool-errno": ("errno", True), "stage": ("stage", "unknown"),
                              "type": ("type", "not-an-identifier"), "causes": ("causes", [{}] * 5)}[fault]
        value["primary"][field] = replacement
    elif fault == "candidate":
        value["candidate_at_start"] = {"commit": "fake", "source_sha256": "b" * 64}
    elif fault == "success":
        value["execution_succeeded"] = True
    elif fault == "secondaries":
        value["secondary"] = [value["primary"]] * 17
    elif fault == "omitted":
        value["secondary_omitted"] = -1
    else:
        value["invocation_id"] = "../escape"
    with pytest.raises(evidence.FailureDiagnosticError):
        evidence.validate_diagnostic(value)


@pytest.mark.parametrize("fault", ["symlink", "mode", "duplicate", "oversized", "directory", "hardlink"])
def test_reader_refuses_unsafe_or_unbounded_diagnostic_files(tmp_path: Path, fault):
    path = tmp_path / "record.json"
    evidence.persist_diagnostic(path, payload())
    if fault == "mode":
        path.chmod(0o644)
    elif fault == "duplicate":
        path.write_text('{"schema":0,"schema":1}')
    elif fault == "oversized":
        path.write_bytes(b" " * (evidence.MAX_BYTES + 1))
    elif fault in ("symlink", "directory"):
        real = path.with_suffix(".original")
        path.rename(real)
        path.symlink_to(real) if fault == "symlink" else path.mkdir()
    else:
        (tmp_path / "other.json").hardlink_to(path)
    with pytest.raises((OSError, evidence.FailureDiagnosticError)):
        evidence.read_diagnostic(path, evidence.FAILURE_SCHEMA)


def test_owned_updates_refuse_existing_targets_and_drift(tmp_path: Path):
    path = tmp_path / "diagnostic.json"
    value = payload()
    previous = evidence.persist_diagnostic(path, value)
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(evidence.FailureDiagnosticError):
        evidence.persist_diagnostic(path, value)
    changed = deepcopy(value)
    changed["secondary"].append(evidence.error_record(OSError(errno.EIO, "opaque"), "go_cleanup"))
    previous = evidence.persist_diagnostic(path, changed, previous)
    assert evidence.read_diagnostic(path, evidence.FAILURE_SCHEMA) == changed
    path.write_text("{}")
    with pytest.raises(evidence.FailureDiagnosticError):
        evidence.persist_diagnostic(path, changed, previous)
    assert path.read_text() == "{}"


def test_failure_cap_and_diagnostic_only_never_qualifies(tmp_path: Path):
    report: dict[str, Any] = {"invocation_id": "cap", "candidate": None, "partition": {}, "errors": []}
    failure = evidence.FailureEvidence(tmp_path / "contract.json", report)
    failure.capture(FileNotFoundError(), "candidate_identity")
    for _ in range(20):
        failure.capture(OSError(), "go_cleanup")
    failure.persist()
    path = evidence.diagnostic_path(tmp_path, "runner_failure_report", "cap")
    value = evidence.read_diagnostic(path, evidence.FAILURE_SCHEMA)
    assert value["primary"]["type"] == "FileNotFoundError"
    assert len(value["secondary"]) == 16 and value["secondary_omitted"] == 4
    with pytest.raises(ValueError):
        validate_report(value)
    assert not qualifies(value) and not execution_succeeded(value)


def test_contract_writer_failure_retains_original_cause_even_if_diagnostic_cannot_write(tmp_path, monkeypatch, capsys):
    def refuse(*_args, **_kwargs):
        raise PermissionError(errno.EACCES, "opaque-fixture")

    report: dict[str, Any] = {"invocation_id": "write", "candidate": None, "partition": {}, "errors": []}
    failure = evidence.FailureEvidence(tmp_path / "contract.json", report, contract_writer=refuse)
    failure.capture(ValueError("opaque-fixture"), "candidate_identity")
    monkeypatch.setattr(evidence, "persist_diagnostic", refuse)
    assert failure.persist_contract() is False
    assert failure.primary is not None
    assert failure.primary["stage"] == "candidate_identity"
    assert failure.secondary[0]["stage"] == "report_persistence"
    assert "opaque-fixture" not in capsys.readouterr().err
