"""Window2 regression and bounded whole-window comparison diagnostics (T1 only)."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ci import qualification_rust_runtime as runtime
from ci import rust_pilot_qualification as command
from ci.qualification_rust_manifest import ManifestError, validate_manifest
from repomap_test_support.rust_pilot_fake_tree_sitter.tree_sitter._grammar import parse_source

ROOT = Path(__file__).resolve().parents[6]
MANIFEST = ROOT / "tools/ci/rust_pilot_qualification_manifest.json"
FIXTURES = ROOT / "src/test/fixtures/rust_pilot"


def _comparison(monkeypatch: pytest.MonkeyPatch, *, changes: tuple[str, ...] = ()):
    manifest = json.loads(MANIFEST.read_bytes())
    sources = tuple(p for p in manifest["fixture"]["files"] if not p.startswith("golds/"))
    calls = []

    def admit(relative):
        calls.append(relative)
        observations = () if relative == "q06_invalid_utf8.rs" else (object(),)
        return SimpleNamespace(observations=observations)

    def document(relative, _data, _observations, _outcome, _scenario):
        entry = manifest["fixture"]["files"][relative]
        value = json.loads((FIXTURES / entry["gold"]).read_bytes())
        if relative in changes:
            value["line_count"] += 1
        return value

    monkeypatch.setattr(runtime, "_document", document)
    summary = SimpleNamespace(file_outcomes=())
    return SimpleNamespace(admit=admit), summary, sources, manifest, calls


@pytest.mark.parametrize("suffix", [b"", b"\n", b"\r\n", b" \t\n"])
def test_missing_closing_token_stand_in_excludes_trailing_whitespace(suffix: bytes) -> None:
    source = b"mod unfinished {\n    struct Pending;"
    node = parse_source(source + suffix).children[0]
    assert node.type == "mod_item" and node.has_error
    assert node.end_byte == len(source)
    assert node.fields["body"].children[-1].is_missing


def test_window2_gold_preserves_digest_bound_native_document_endpoint() -> None:
    path = FIXTURES / "golds/q04_missing_brace.gold.json"
    gold = json.loads(path.read_bytes())
    assert gold["items"][2]["end_byte"] == 252
    canonical = json.dumps(gold, sort_keys=True, separators=(",", ":")).encode()
    # Retained ARM1 document digest, reconstructed by exactly one changed digit.
    assert hashlib.sha256(canonical).hexdigest() == (
        "d738feee3215c67b3b928572ef259768059865186f6e973ea851169b2b56f92e"
    )


def test_window2_validator_rejects_the_spent_window_identifier(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_bytes())
    assert manifest["window"] == "RUST-PILOT-QW2"
    manifest["window"] = "RUST-PILOT-QW1"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ManifestError) as raised:
        validate_manifest(path, ROOT)
    assert raised.value.code == "manifest_identity"


def test_multiple_mismatches_retain_every_compared_document_and_still_refuse(
        monkeypatch: pytest.MonkeyPatch) -> None:
    targets = ("q01_all_items.rs", "unsupported_forms.rs")
    controller, summary, sources, manifest, calls = _comparison(monkeypatch, changes=targets)
    with pytest.raises(runtime.RuntimeGap) as raised:
        runtime.compare_gold_claims(controller, summary, FIXTURES, sources, manifest)
    error = raised.value
    assert error.code == "gold_mismatch"
    assert calls == list(sources) and len(calls) == 13
    assert error.evidence["comparison_complete"] is True
    assert error.evidence["mismatch_count"] == 2
    rows = error.evidence["comparisons"]
    assert [row["fixture"] for row in rows] == list(sources)
    assert [row["fixture"] for row in rows if row["mismatched_fields"]] == list(targets)
    for row in rows:
        assert set(row["actual"]) == set(row["expected"])
        for kind in ("actual", "gold"):
            document = row["actual" if kind == "actual" else "expected"]
            canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            assert row[kind + "_document_sha256"] == hashlib.sha256(canonical).hexdigest()


def test_matching_window_retains_bounded_canonical_documents_without_native_credit(
        monkeypatch: pytest.MonkeyPatch) -> None:
    controller, summary, sources, manifest, calls = _comparison(monkeypatch)
    result = runtime.compare_gold_claims(controller, summary, FIXTURES, sources, manifest)
    assert calls == list(sources)
    assert result["item_claims"] == 420 and len(result["files"]) == 13
    assert result["comparison_complete"] is True
    assert all(row["actual"] == row["expected"] for row in result["comparisons"])
    encoded = json.dumps(result["comparisons"], sort_keys=True, separators=(",", ":")).encode()
    assert result["retained_document_bytes"] == len(encoded) <= runtime.MAX_GOLD_EVIDENCE_BYTES
    assert "qualified" not in result


def test_diagnostic_cap_refuses_without_retaining_the_oversized_document(
        monkeypatch: pytest.MonkeyPatch) -> None:
    controller, summary, sources, manifest, calls = _comparison(monkeypatch)
    monkeypatch.setattr(runtime, "MAX_GOLD_EVIDENCE_BYTES", 2)
    with pytest.raises(runtime.RuntimeGap) as raised:
        runtime.compare_gold_claims(controller, summary, FIXTURES, sources, manifest)
    error = raised.value
    assert error.code == "gold_evidence_bound"
    assert calls == [sources[0]]
    assert error.evidence["comparison_complete"] is False
    assert error.evidence["comparisons"] == []
    assert error.evidence["retained_document_bytes"] == 2


def test_read_failure_keeps_prior_comparisons_as_incomplete(
        monkeypatch: pytest.MonkeyPatch) -> None:
    controller, summary, sources, manifest, _calls = _comparison(monkeypatch)
    manifest = copy.deepcopy(manifest)
    manifest["fixture"]["files"][sources[1]]["gold"] = "golds/absent.json"
    with pytest.raises(runtime.RuntimeGap) as raised:
        runtime.compare_gold_claims(controller, summary, FIXTURES, sources, manifest)
    assert raised.value.code == "gold_read_failed"
    assert raised.value.evidence["comparison_complete"] is False
    assert [row["fixture"] for row in raised.value.evidence["comparisons"]] == [sources[0]]


def test_wrong_total_claim_count_refuses_with_complete_document_evidence(
        monkeypatch: pytest.MonkeyPatch) -> None:
    controller, summary, sources, manifest, _calls = _comparison(monkeypatch)
    manifest["fixture"]["expected_item_claims"] = 421
    with pytest.raises(runtime.RuntimeGap) as raised:
        runtime.compare_gold_claims(controller, summary, FIXTURES, sources, manifest)
    assert raised.value.code == "gold_claim_count"
    assert raised.value.evidence["comparison_complete"] is True
    assert len(raised.value.evidence["comparisons"]) == 13


def test_comparison_cap_reserves_metadata_inside_the_unchanged_amd_report_envelope() -> None:
    assert command.MAX_REPORT_BYTES == 1_048_576
    assert runtime.MAX_GOLD_EVIDENCE_BYTES == command.MAX_REPORT_BYTES - 256 * 1024


def test_report_overflow_keeps_a_bounded_failed_report_without_false_zero_counters(
        tmp_path: Path) -> None:
    report = command._initial()
    report.update(result="passed", qualified=True, candidate_sha="a" * 40,
                  private_marker="withheld-test-value", padding="x" * 1_048_576)
    original = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("ascii")
    with pytest.raises(RuntimeError, match="report_bound_exceeded"):
        command._write_report(tmp_path, report)
    raw = (tmp_path / "rust-pilot-qualification.json").read_bytes()
    assert len(raw) <= 1_048_576 and b"withheld-test-value" not in raw
    failed = json.loads(raw)
    assert (failed["result"], failed["qualified"], failed["reason"]) == (
        "failed", False, "report_bound_exceeded")
    assert failed["evidence_retention"]["complete"] is False
    assert failed["evidence_retention"]["original_report_sha256"] == hashlib.sha256(original).hexdigest()
    assert failed["evidence_retention"]["original_report_bytes"] == len(original) + 1
    assert all(row["value"] is None and row["cross_checked"] is False
               for row in failed["counters"].values())


def test_report_byte_bound_includes_its_final_newline(tmp_path: Path) -> None:
    report = {"value": ""}
    base = len(json.dumps(report, sort_keys=True, separators=(",", ":")).encode("ascii")) + 1
    report["value"] = "x" * (1_048_576 - base)
    command._write_report(tmp_path / "exact", report)
    assert (tmp_path / "exact/rust-pilot-qualification.json").stat().st_size == 1_048_576
    report["value"] += "x"
    with pytest.raises(RuntimeError, match="report_bound_exceeded"):
        command._write_report(tmp_path / "over", report)
    assert (tmp_path / "over/rust-pilot-qualification.json").stat().st_size < 1_048_576


@pytest.mark.parametrize("failure", [KeyError, TypeError, AttributeError, RuntimeError])
def test_unexpected_comparison_failure_preserves_prior_documents_without_exception_text(
        monkeypatch: pytest.MonkeyPatch, failure: type[Exception]) -> None:
    controller, summary, sources, manifest, _calls = _comparison(monkeypatch)
    original = runtime._document

    def fail_second(relative, *args):
        if relative == sources[1]:
            raise failure("withheld-test-value")
        return original(relative, *args)

    monkeypatch.setattr(runtime, "_document", fail_second)
    with pytest.raises(runtime.RuntimeGap) as raised:
        runtime.compare_gold_claims(controller, summary, FIXTURES, sources, manifest)
    assert raised.value.code == "gold_comparison_failed"
    assert raised.value.evidence["comparison_complete"] is False
    assert [row["fixture"] for row in raised.value.evidence["comparisons"]] == [sources[0]]
    assert "withheld-test-value" not in json.dumps(raised.value.evidence)


@pytest.mark.parametrize("stage", ["graph_quality", "accounting", "cleanup"])
def test_actual_adapter_keeps_completed_gold_after_a_later_stage_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    from ci import qualification_rust_accounting as accounting
    from ci import qualification_rust_scenarios as scenarios
    from common_lore_index.canonicalization import rust_pilot_family
    from common_lore_index.extractors.contracts.vocabulary import ContractError
    from common_lore_index.extractors.rust_pilot import controller as controller_module, prepared_profile

    controller, summary, _sources, manifest, _calls = _comparison(monkeypatch)
    summary.run_outcome = "processed"
    snapshot = {"run_id": "t1", "files": [], "receipts": [],
                "residue": {"owned_containers_remaining": 0}}
    closed: list[bool] = []

    def close():
        closed.append(True)
        if stage == "cleanup":
            raise ContractError("owned_cleanup_failed")

    def refuse(*_args, **_kwargs):
        raise runtime.RuntimeGap("injected_late_failure")

    controller.close = close
    controller._boundary = SimpleNamespace(limit_work_deadline=lambda _deadline: None)
    controller.helper_closure_sha256 = manifest["closure"]["helper_closure_sha256"]
    controller.process = lambda *_args: summary
    controller.verify_live = lambda: True
    controller.audit_snapshot = lambda: snapshot
    monkeypatch.setattr(controller_module, "RustPilotController", lambda **_kwargs: controller)
    monkeypatch.setattr(prepared_profile, "load_profile", lambda *_args, **_kwargs:
                        SimpleNamespace(profile_sha256=manifest["closure"]["profile_digests"]["arm64"]))
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(scenarios, "preflight_scenarios", lambda *_args, **_kwargs: {"t1": {"passed": True}})
    monkeypatch.setattr(runtime, "_containment", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runtime, "_audit", lambda *_args: (snapshot, {"costs": {}, "counters": {}}))
    monkeypatch.setattr(runtime, "_legacy_measure", lambda *_args: {"_observations": ()})
    monkeypatch.setattr(runtime, "_incumbent", lambda *_args: {})
    witness = SimpleNamespace(verify_live=lambda: True, result=SimpleNamespace(graph=object()))
    monkeypatch.setattr(rust_pilot_family, "canonicalize_rust_pilot", lambda *_args, **_kwargs: witness)
    monkeypatch.setattr(runtime, "_navigation", lambda *_args: {})
    monkeypatch.setattr(runtime, "_graph_quality", refuse if stage == "graph_quality" else lambda *_args: {})
    monkeypatch.setattr(accounting, "require_component_accounting",
                        refuse if stage == "accounting" else lambda *_args: {})
    with pytest.raises(runtime.RuntimeGap) as raised:
        runtime._run_native_component(ROOT, FIXTURES, tmp_path / "profile", "t1-image", tmp_path,
                                      manifest, platform="linux/arm64", cross_cpu_profile=None,
                                      work_deadline=runtime.time.monotonic() + 1200.0)
    assert raised.value.code == ("cleanup_incomplete" if stage == "cleanup" else "injected_late_failure")
    gold = raised.value.evidence["completed_gold"]
    assert gold["comparison_complete"] is True and gold["mismatch_count"] == 0
    assert len(gold["comparisons"]) == 13 and gold["item_claims"] == 420
    assert closed == [True]


@pytest.mark.parametrize("error_class", ["RuntimeError", "ContractError"])
def test_unexpected_acquisition_outcome_reports_unknown_downloads(
        tmp_path: Path, error_class: str) -> None:
    code = r'''
from pathlib import Path
import sys
root=Path(sys.argv[1]);sys.path[:0]=[str(root/'tools'),str(root/'src/main/python'),str(root/'src/test/support/python')]
from ci import rust_pilot_qualification as command, qualification_rust_acquisition as acquisition
from common_lore_index.extractors.contracts.vocabulary import ContractError
command._positive_d12=lambda *_args:('a'*40,'b'*40,'t1-image','t1-recipe')
command._bind_candidate=lambda *_args:None
command._verify_sdk=lambda *_args,**_kwargs:None
def refuse(*_args,**_kwargs):
    raise (ContractError if sys.argv[2]=='ContractError' else RuntimeError)('unexpected_acquisition_failure')
acquisition.acquire_exact_amd_wheels=refuse
raise SystemExit(command.main(sys.argv[3:]))
'''
    args = ["amd64", "--repo-root", str(ROOT), "--d12-state-dir", str(tmp_path / "d12"),
            "--d12-sealed-json", str(tmp_path / "d12/sealed.json"), "--manifest", str(MANIFEST),
            "--work-dir", str(tmp_path / "work"), "--report-dir", str(tmp_path / "report")]
    done = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(ROOT), error_class, *args],
                          env={"PATH": os.environ.get("PATH", "")}, capture_output=True,
                          check=False, timeout=30)
    assert done.returncode == 1, done.stderr
    report = json.loads((tmp_path / "report/rust-pilot-qualification.json").read_bytes())
    assert report["qualified"] is False
    assert report["counters"]["downloads"] == {
        "value": None, "basis": "acquisition_outcome_unknown", "cross_checked": False}
