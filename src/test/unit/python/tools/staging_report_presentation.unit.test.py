"""Failure-visible report rendering and smoke admission evidence."""

import json
from types import SimpleNamespace

from runner_integration_execution import record_smoke_refusal
from src.test.unit.python.tools.staging_execution_fixtures import IDENTITY, _execute
from staging_report_contract import SCHEMA_V1, load_report, main, qualifies
from test_report import TestRecord as ReportRecord, write_html_report


def test_both_obligations_are_visible_with_unknown_not_success(tmp_path):
    payload = {"legs": {
        "M": {"status": "failed", "measurement": {"state": "incomplete"}},
        "A": {"status": "blocked", "measurement": {"state": "unavailable"}},
    }}
    index = write_html_report(report_root=tmp_path, suite_name="staging",
        test_records=(ReportRecord("fixture::test", "fixture", "failed", 0.01),),
        coverage=None, repo_root=tmp_path, staging_obligations=payload)
    text = index.read_text()
    assert "Staging evidence: not qualified" in text
    assert "M: failed; measurement incomplete" in text
    assert "A: blocked; measurement unavailable" in text
    summary = json.loads((index.parent / "summary.json").read_text())
    assert summary["staging_obligations"] == payload
    assert summary["records"][0]["status"] == "failed"


def test_failed_smoke_exports_blocked_unexecuted_obligations(tmp_path, monkeypatch):
    monkeypatch.setattr("runner_integration_execution.candidate_identity",
        lambda root: {"commit": "a" * 40, "source_sha256": "b" * 64})
    record_smoke_refusal(SimpleNamespace(report_dir=tmp_path, no_coverage=False))
    path = tmp_path / "staging/latest/staging_contract_report.json"
    payload = json.loads(path.read_text())
    assert payload["smoke"] == "failed"
    assert payload["partition"] == {}
    assert all(leg["status"] == "blocked" and leg["records"] == []
               for leg in payload["legs"].values())
    assert not qualifies(payload)


def test_cli_validates_a_v1_report_only_under_explicit_legacy_rules(tmp_path, monkeypatch, capsys):
    _result, path, _order, _coverage_env, _sessions = _execute(monkeypatch, tmp_path, staging=True)
    report = load_report(path)
    identity = ["--report", str(path), "--commit", IDENTITY["commit"], "--source-sha256", IDENTITY["source_sha256"],
                "--invocation-id", report["invocation_id"]]
    assert main([*identity, "--legacy-v1"]) == 2, "legacy rules accept only a v1 report"
    legacy = {
        **report, "schema": SCHEMA_V1, "partition": {k: v for k, v in report["partition"].items() if k != "optional"}}
    path.write_text(json.dumps(legacy), encoding="utf-8")
    capsys.readouterr()
    assert main(identity) == 2, "a v1 label is never current qualification"
    assert main([*identity, "--legacy-v1"]) == 0
    result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (result["schema"], result["rules"], result["current_qualification"], result["qualified"]) == (
        SCHEMA_V1, "v1", False, True), result
