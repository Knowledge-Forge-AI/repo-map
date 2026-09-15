from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import pytest

from ci.run_pre_review import (
    Check,
    evaluate,
    execute_all,
)
from ci.pre_review_evidence import (
    LOG_CAP_BYTES,
    finalize_evidence,
    verify_evidence,
)


def make_oversized_payload(file_count: int = 2500) -> dict:
    from repomap_test_support.retention_evidence_fixture import evidence_source
    return evidence_source(status="failed", file_count=file_count, cohort_count=0, root="product")


def test_evaluate_python_retention_inventory_success() -> None:
    check = Check(
        "python-retention-inventory",
        (sys.executable, "tools/ci/python_retention_inventory.py", "--check", "--json"),
        python_owned=True,
    )
    doc = {
        "status": "passed",
        "enforcement_complete": True,
        "counts": {"total_files": 123},
    }
    status, detail, classification = evaluate(check, 0, json.dumps(doc))
    assert status == "passed"
    assert classification == "passed"
    assert "census=123" in detail


def test_evaluate_python_retention_inventory_tool_failure_classification() -> None:
    check = Check(
        "python-retention-inventory",
        (sys.executable, "tools/ci/python_retention_inventory.py", "--check", "--json"),
        python_owned=True,
    )
    doc = {
        "status": "failed",
        "enforcement_complete": False,
        "counts": {"total_files": 10},
        "eligible": {"tools": ["tools/a.py"]},
        "check_results": {
            "tools": {
                "status": "failed",
                "classification": "tool-failure",
                "tool_failure": "QualityProfileError",
            },
        },
    }
    status, detail, classification = evaluate(check, 1, json.dumps(doc))
    assert status == "failed"
    assert classification == "tool-failure"
    assert "status=failed" in detail
    assert "tools=tool-failure" in detail


def test_evaluate_python_retention_inventory_policy_finding_classification() -> None:
    check = Check(
        "python-retention-inventory",
        (sys.executable, "tools/ci/python_retention_inventory.py", "--check", "--json"),
        python_owned=True,
    )
    doc = {
        "status": "failed",
        "enforcement_complete": False,
        "counts": {"total_files": 10},
        "eligible": {"test_support": ["src/test/support/a.py"]},
        "check_results": {
            "test_support": {
                "status": "failed",
            },
        },
    }
    status, detail, classification = evaluate(check, 1, json.dumps(doc))
    assert status == "failed"
    assert classification == "policy-finding"
    assert "status=failed" in detail
    assert "test_support=finding" in detail


def test_evaluate_python_retention_inventory_invalid_json() -> None:
    check = Check(
        "python-retention-inventory",
        (sys.executable, "tools/ci/python_retention_inventory.py", "--check", "--json"),
        python_owned=True,
    )
    status, detail, classification = evaluate(check, 1, "NOT JSON")
    assert status == "failed"
    assert classification == "tool-failure"
    assert "invalid" in detail


def test_oversized_synthetic_regression_visible_failure_and_retrievable_payload(tmp_path: Path) -> None:
    """Oversized synthetic regression proves failure visible despite truncated console and complete parseable payload retrievable."""
    evidence_dir = tmp_path / "evidence"
    scratch_dir = tmp_path / "scratch"
    selected = (
        Check(
            "python-retention-inventory",
            (sys.executable, "tools/ci/python_retention_inventory.py", "--check", "--json"),
            python_owned=True,
        ),
    )

    oversized_doc = make_oversized_payload(file_count=2500)
    oversized_doc["check_results"]["product"]["message"] = str(scratch_dir / "private.json")
    raw_json_str = json.dumps(oversized_doc, indent=2, sort_keys=True)
    raw_bytes = raw_json_str.encode("utf-8")
    assert len(raw_bytes) > LOG_CAP_BYTES, f"Payload must exceed LOG_CAP_BYTES ({LOG_CAP_BYTES}), got {len(raw_bytes)}"

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, raw_json_str, "")

    results = execute_all(
        selected,
        evidence_dir,
        runner=runner,
        scratch_dir=scratch_dir,
    )

    assert len(results) == 1
    result = results[0]

    # 1. Failure is visible in console detail despite large payload
    assert result.status == "failed"
    assert result.classification == "tool-failure"
    assert "status=failed" in result.detail
    assert "census=2500" in result.detail
    assert "residual=2500" in result.detail
    assert "product=tool-failure" in result.detail

    # 2. Log is truncated to LOG_CAP_BYTES
    log_path = evidence_dir / "python-retention-inventory.log"
    assert log_path.is_file()
    assert log_path.stat().st_size <= LOG_CAP_BYTES
    log_content = log_path.read_text(encoding="utf-8")
    assert "[log truncated at bounded evidence cap]" in log_content

    # 3. Compact failure summary appears FIRST in log (before any truncation point)
    summary_pos = log_content.find("--- COMPACT FAILURE SUMMARY ---")
    assert summary_pos != -1
    assert summary_pos < 500  # Within the very beginning of the log
    assert "status: failed" in log_content
    assert "census: 2500" in log_content
    assert "residual: 2500" in log_content
    assert "product: tool-failure (2500 residual)" in log_content

    # 4. Complete parseable payload is retrievable from python-retention-inventory.result.json
    result_json_path = evidence_dir / "python-retention-inventory.result.json"
    assert result_json_path.is_file()
    # It must not be truncated
    retrieved_doc = json.loads(result_json_path.read_text(encoding="utf-8"))
    assert retrieved_doc["schema"] == "repomap-python-retention-evidence-v1"
    assert retrieved_doc["totals"]["census"] == 2500
    assert retrieved_doc["omitted_collections"]["candidate_files"]["count"] == 2500
    assert retrieved_doc["roots"]["product"]["state"] == "tool-failure"
    assert str(scratch_dir) not in result_json_path.read_text()
    assert result_json_path.stat().st_size < 1024 * 1024

    # 5. Evidence manifest declares it, and verification succeeds
    headroom = finalize_evidence(evidence_dir, selected, results)
    verify_evidence(evidence_dir, selected)
    from ci.pre_review_evidence import AGGREGATE_CAP_BYTES
    assert headroom == AGGREGATE_CAP_BYTES - sum(path.stat().st_size for path in evidence_dir.iterdir())

    manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
    payload_artifact = next(
        item for item in manifest["artifacts"]
        if item["path"] == "python-retention-inventory.result.json"
    )
    assert payload_artifact["size_bytes"] == result_json_path.stat().st_size
    assert payload_artifact["size_bytes"] > 0


def test_regression_fail_closed_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove missing, tampered, unexpected, malformed, and oversize fail closed."""
    evidence_dir = tmp_path / "evidence"
    scratch_dir = tmp_path / "scratch"
    selected = (
        Check(
            "python-retention-inventory",
            (sys.executable, "tools/ci/python_retention_inventory.py", "--check", "--json"),
            python_owned=True,
        ),
    )

    doc = make_oversized_payload(file_count=50)
    json_str = json.dumps(doc, indent=2, sort_keys=True)

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, json_str, "")

    results = execute_all(selected, evidence_dir, runner=runner, scratch_dir=scratch_dir)
    finalize_evidence(evidence_dir, selected, results)

    # 1. Missing fails closed
    result_json_path = evidence_dir / "python-retention-inventory.result.json"
    backup_bytes = result_json_path.read_bytes()
    result_json_path.unlink()
    with pytest.raises(RuntimeError, match="missing evidence path: python-retention-inventory.result.json"):
        verify_evidence(evidence_dir, selected)
    result_json_path.write_bytes(backup_bytes)

    # 2. Tampered fails closed
    result_json_path.write_text('{"tampered": true}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="(?:size|digest) mismatch for evidence path"):
        verify_evidence(evidence_dir, selected)
    result_json_path.write_bytes(backup_bytes)

    # 3. Unexpected fails closed
    extra_file = evidence_dir / "unexpected.log"
    extra_file.write_text("extra", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unexpected evidence path: unexpected.log"):
        verify_evidence(evidence_dir, selected)
    extra_file.unlink()

    # 4. Malformed fails closed
    result_json_path.write_text("{broken json syntax\n", encoding="utf-8")
    # update manifest digest/size to isolate malformed json test
    import hashlib
    manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["artifacts"]:
        if item["path"] == "python-retention-inventory.result.json":
            item["sha256"] = hashlib.sha256(result_json_path.read_bytes()).hexdigest()
            item["size_bytes"] = result_json_path.stat().st_size
    manifest["payload_uncompressed_bytes"] = sum(item["size_bytes"] for item in manifest["artifacts"])
    (evidence_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="malformed evidence payload: python-retention-inventory.result.json"):
        verify_evidence(evidence_dir, selected)
    result_json_path.write_bytes(backup_bytes)

    # 5. Oversize fails closed
    import ci.pre_review_evidence as mod
    monkeypatch.setattr(mod, "AGGREGATE_CAP_BYTES", 50)
    with pytest.raises(RuntimeError, match="(?:oversized evidence payload|exceeds the aggregate size cap)"):
        verify_evidence(evidence_dir, selected)


@pytest.mark.parametrize("returncode", [0, 1])
@pytest.mark.parametrize("cap", [1000, 4000])
def test_main_preserves_check_status_when_evidence_exceeds_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    returncode: int, cap: int,
) -> None:
    import ci.pre_review_evidence as evidence
    import ci.run_pre_review as aggregate

    selected = (Check("synthetic-check", ("synthetic-tool",)),)
    evidence_dir = tmp_path / "evidence"
    original_execute = aggregate.execute_all

    def execute(selected, directory, **kwargs):
        def runner(command, **_kwargs):
            return subprocess.CompletedProcess(command, returncode, "x" * 2000, "")

        return original_execute(selected, directory, runner=runner, **kwargs)

    monkeypatch.setattr(aggregate, "_attest_python_owner", lambda _root: None)
    monkeypatch.setattr(aggregate, "checks", lambda *_args: selected)
    monkeypatch.setattr(aggregate, "execute_all", execute)
    monkeypatch.setattr(evidence, "AGGREGATE_CAP_BYTES", cap)
    assert aggregate.main([
        "--evidence-dir", str(evidence_dir), "--tool-root", str(tmp_path / "tools"),
    ]) == (1 if returncode or cap == 1000 else 0)
    output = capsys.readouterr().out
    expected = "PASSED" if returncode == 0 else "FAILED"
    assert f"{expected:6} synthetic-check" in output
    assert "pre-review summary:" in output
    if cap == 1000:
        assert "FAILED evidence-finalization: oversized evidence payload:" in output
        assert "Evidence is incomplete or unqualified" in output
        assert "evidence headroom:" not in output
    else:
        remaining = cap - sum(path.stat().st_size for path in evidence_dir.iterdir())
        assert f"evidence headroom: {remaining} bytes" in output
        assert "WARNING evidence envelope" in output
        assert "FAILED evidence-finalization:" not in output
    assert "Traceback" not in output
    document = json.loads((evidence_dir / "results.json").read_text())
    assert document["results"][0]["returncode"] == returncode
    assert document["results"][0]["status"] == expected.lower()


def test_incomplete_variant_on_raw_non_json_output(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    scratch_dir = tmp_path / "scratch"
    selected = (
        Check(
            "python-retention-inventory",
            (sys.executable, "tools/ci/python_retention_inventory.py", "--check", "--json"),
            python_owned=True,
        ),
    )

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, "NON_JSON_FATAL_OUTPUT\n", "")

    results = execute_all(selected, evidence_dir, runner=runner, scratch_dir=scratch_dir)
    assert len(results) == 1
    assert results[0].status == "failed"
    result_json_path = evidence_dir / "python-retention-inventory.result.json"
    doc = json.loads(result_json_path.read_text(encoding="utf-8"))
    assert doc["schema"] == "repomap-python-retention-evidence-incomplete-v1"
    assert doc["status"] == "failed"
    assert doc["complete"] is False
    finalize_evidence(evidence_dir, selected, results)
    verify_evidence(evidence_dir, selected)


def test_incomplete_variant_on_execution_exception(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    scratch_dir = tmp_path / "scratch"
    selected = (
        Check(
            "python-retention-inventory",
            (sys.executable, "tools/ci/python_retention_inventory.py", "--check", "--json"),
            python_owned=True,
        ),
    )

    def runner(command, **_kwargs):
        raise OSError("synthetic process launch error")

    results = execute_all(selected, evidence_dir, runner=runner, scratch_dir=scratch_dir)
    assert len(results) == 1
    assert results[0].status == "failed"
    result_json_path = evidence_dir / "python-retention-inventory.result.json"
    doc = json.loads(result_json_path.read_text(encoding="utf-8"))
    assert doc["schema"] == "repomap-python-retention-evidence-incomplete-v1"
    assert doc["status"] == "failed"
    finalize_evidence(evidence_dir, selected, results)
    verify_evidence(evidence_dir, selected)


def test_sanitization_mapping_key_collision_rejected(tmp_path: Path) -> None:
    from ci.pre_review_records import sanitize_machine_result
    scratch1 = tmp_path / "scratch1"
    scratch2 = tmp_path / "scratch2"
    colliding = {
        str(scratch1 / "target.py"): "value1",
        str(scratch2 / "target.py"): "value2",
    }
    with pytest.raises(ValueError, match="mapping key collision after sanitization"):
        sanitize_machine_result(colliding, scratch1, scratch2)
