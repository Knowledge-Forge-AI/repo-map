from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import pytest

from ci.pre_review_evidence import (
    AGGREGATE_CAP_BYTES,
    LOG_CAP_BYTES,
    _expected_payloads,
    finalize_evidence,
    verify_evidence,
)
from ci.python_retention_evidence import (
    compact_retention_evidence,
    create_incomplete_retention_evidence,
)


@dataclass(frozen=True)
class FakeCheck:
    name: str


@dataclass(frozen=True)
class FakeResult:
    name: str
    status: str
    detail: str

    classification: str = ""

    def __post_init__(self) -> None:
        classification = "passed" if self.status == "passed" else "tool-failure" if "bootstrap" in self.detail else "policy-finding"
        object.__setattr__(self, "classification", classification)


def _sample_source_doc(status: str = "passed") -> dict:
    from repomap_test_support.retention_evidence_fixture import evidence_source
    return evidence_source(status=status, file_count=1, cohort_count=1)


def test_expected_payloads_declares_retention_inventory_result() -> None:
    generic = (FakeCheck("ruff"), FakeCheck("mypy"))
    assert _expected_payloads(generic) == ("ruff.log", "mypy.log", "results.json")

    with_retention = (FakeCheck("ruff"), FakeCheck("python-retention-inventory"))
    assert _expected_payloads(with_retention) == (
        "ruff.log",
        "python-retention-inventory.log",
        "python-retention-inventory.result.json",
        "results.json",
    )


def test_evidence_verification_succeeds_with_declared_inventory_payload(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True)
    selected = (FakeCheck("python-retention-inventory"),)
    results = (FakeResult("python-retention-inventory", "failed", "enforcement failed"),)

    (evidence_dir / "python-retention-inventory.log").write_text("header\nlog content\n", encoding="utf-8")
    payload = compact_retention_evidence(_sample_source_doc(status="failed"))
    (evidence_dir / "python-retention-inventory.result.json").write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    finalize_evidence(evidence_dir, selected, results)
    verify_evidence(evidence_dir, selected)

    manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
    artifact_paths = {item["path"] for item in manifest["artifacts"]}
    assert artifact_paths == {
        "python-retention-inventory.log",
        "python-retention-inventory.result.json",
        "results.json",
    }
    retention_artifact = next(
        item for item in manifest["artifacts"]
        if item["path"] == "python-retention-inventory.result.json"
    )
    assert retention_artifact["size_bytes"] > 0
    assert len(retention_artifact["sha256"]) == 64


def test_missing_payload_fails_closed(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True)
    selected = (FakeCheck("python-retention-inventory"),)
    results = (FakeResult("python-retention-inventory", "passed", "ok"),)

    (evidence_dir / "python-retention-inventory.log").write_text("log\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="missing evidence path: python-retention-inventory.result.json"):
        finalize_evidence(evidence_dir, selected, results)


def test_tampered_payload_fails_closed(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True)
    selected = (FakeCheck("python-retention-inventory"),)
    results = (FakeResult("python-retention-inventory", "passed", "ok"),)

    (evidence_dir / "python-retention-inventory.log").write_text("log\n", encoding="utf-8")
    result_path = evidence_dir / "python-retention-inventory.result.json"
    payload = compact_retention_evidence(_sample_source_doc(status="passed"))
    result_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")

    finalize_evidence(evidence_dir, selected, results)

    result_path.write_text('{"status": "tampered"}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="(?:size|digest) mismatch for evidence path"):
        verify_evidence(evidence_dir, selected)


def test_unexpected_payload_fails_closed(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True)
    selected = (FakeCheck("python-retention-inventory"),)
    results = (FakeResult("python-retention-inventory", "passed", "ok"),)

    (evidence_dir / "python-retention-inventory.log").write_text("log\n", encoding="utf-8")
    payload = compact_retention_evidence(_sample_source_doc(status="passed"))
    (evidence_dir / "python-retention-inventory.result.json").write_text(
        json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    finalize_evidence(evidence_dir, selected, results)

    (evidence_dir / "unexpected.json").write_text('{"extra": true}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="unexpected evidence path: unexpected.json"):
        verify_evidence(evidence_dir, selected)


def test_malformed_payload_fails_closed(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True)
    selected = (FakeCheck("python-retention-inventory"),)
    results = (FakeResult("python-retention-inventory", "passed", "ok"),)

    (evidence_dir / "python-retention-inventory.log").write_text("log\n", encoding="utf-8")
    result_path = evidence_dir / "python-retention-inventory.result.json"
    payload = compact_retention_evidence(_sample_source_doc(status="passed"))
    result_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    finalize_evidence(evidence_dir, selected, results)

    result_path.write_text('{bad json syntax!}\n', encoding="utf-8")
    manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["artifacts"]:
        if item["path"] == "python-retention-inventory.result.json":
            item["sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
            item["size_bytes"] = result_path.stat().st_size
    manifest["payload_uncompressed_bytes"] = sum(item["size_bytes"] for item in manifest["artifacts"])
    (evidence_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="malformed evidence payload: python-retention-inventory.result.json"):
        verify_evidence(evidence_dir, selected)


def test_oversized_payload_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True)
    selected = (FakeCheck("python-retention-inventory"),)
    results = (FakeResult("python-retention-inventory", "passed", "ok"),)

    (evidence_dir / "python-retention-inventory.log").write_text("log\n", encoding="utf-8")
    result_path = evidence_dir / "python-retention-inventory.result.json"
    payload = compact_retention_evidence(_sample_source_doc(status="passed"))
    result_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")

    import ci.pre_review_evidence as mod
    monkeypatch.setattr(mod, "AGGREGATE_CAP_BYTES", 10)

    with pytest.raises(RuntimeError, match="(?:oversized evidence payload|exceeds the aggregate size cap)"):
        finalize_evidence(evidence_dir, selected, results)


def test_incomplete_payload_verification_succeeds(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True)
    selected = (FakeCheck("python-retention-inventory"),)
    results = (FakeResult("python-retention-inventory", "failed", "bootstrap failure"),)

    (evidence_dir / "python-retention-inventory.log").write_text("log\n", encoding="utf-8")
    result_path = evidence_dir / "python-retention-inventory.result.json"
    incomplete = create_incomplete_retention_evidence(error="bootstrap failure", raw_output="traceback...")
    result_path.write_text(json.dumps(incomplete, separators=(",", ":")) + "\n", encoding="utf-8")

    finalize_evidence(evidence_dir, selected, results)
    verify_evidence(evidence_dir, selected)


def test_status_mismatch_between_envelope_and_retention_fails_closed(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True)
    selected = (FakeCheck("python-retention-inventory"),)
    results = (FakeResult("python-retention-inventory", "passed", "claimed pass"),)

    (evidence_dir / "python-retention-inventory.log").write_text("log\n", encoding="utf-8")
    result_path = evidence_dir / "python-retention-inventory.result.json"
    # retention payload is failed, but results claims passed!
    payload = compact_retention_evidence(_sample_source_doc(status="failed"))
    result_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="retention status mismatch"):
        finalize_evidence(evidence_dir, selected, results)


def test_incomplete_retention_with_passing_envelope_status_fails_closed(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True)
    selected = (FakeCheck("python-retention-inventory"),)
    results = (FakeResult("python-retention-inventory", "passed", "claimed pass"),)

    (evidence_dir / "python-retention-inventory.log").write_text("log\n", encoding="utf-8")
    result_path = evidence_dir / "python-retention-inventory.result.json"
    incomplete = create_incomplete_retention_evidence(error="fatal", raw_output="error")
    result_path.write_text(json.dumps(incomplete, separators=(",", ":")) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="retention status mismatch"):
        finalize_evidence(evidence_dir, selected, results)


@pytest.mark.parametrize("capped_logs", [False, True])
def test_normal19pass1policy_finalizes(tmp_path: Path, capped_logs: bool) -> None:
    """19 passing checks plus 1 policy finding check finalizes evidence successfully with headroom."""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True)

    check_names = [f"policy-check-{i:02d}" for i in range(19)] + ["python-retention-inventory"]
    selected = tuple(FakeCheck(name) for name in check_names)
    results = tuple(
        FakeResult(name, "passed", "ok") if name != "python-retention-inventory"
        else FakeResult("python-retention-inventory", "failed", "residual policy debt")
        for name in check_names
    )

    for name in check_names:
        (evidence_dir / f"{name}.log").write_text(
            "x" * LOG_CAP_BYTES if capped_logs else f"log for {name}\n", encoding="utf-8"
        )

    from repomap_test_support.retention_evidence_fixture import evidence_source
    ret_payload = compact_retention_evidence(evidence_source(
        status="failed", file_count=1500, cohort_count=1125
    ))
    (evidence_dir / "python-retention-inventory.result.json").write_text(
        json.dumps(ret_payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    headroom = finalize_evidence(evidence_dir, selected, results)
    assert headroom > 1024 * 1024
    assert LOG_CAP_BYTES == 200_000 and AGGREGATE_CAP_BYTES == 5 * 1024 * 1024
    verify_evidence(evidence_dir, selected)
