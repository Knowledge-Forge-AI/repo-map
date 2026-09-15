"""Failure-visible report rendering and smoke admission evidence."""

import json
from types import SimpleNamespace

from runner_integration_execution import record_smoke_refusal
from staging_report_contract import qualifies
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
