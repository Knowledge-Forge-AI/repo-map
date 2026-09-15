from __future__ import annotations



import test_sandbox as sandbox_owner


from pathlib import Path




import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]

from src.test.unit.python.tools.sandbox_hosted_test_fixtures import _capacity_boundary as _capacity_boundary


def test_sandbox_report_arguments_refuses_existing_destination(tmp_path):
    module = sandbox_owner
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    existing = repo_root / "existing-report"
    existing.mkdir()

    with pytest.raises(RuntimeError, match="destination .* already exists"):
        module._sandbox_report_arguments(
            ["--suite", "int", "--report", "--report-dir", str(existing)],
            repo_root=repo_root,
        )

    # default destination collision
    default_reports = repo_root / ".test-reports"
    default_reports.mkdir()
    with pytest.raises(RuntimeError, match="destination .* already exists"):
        module._sandbox_report_arguments(
            ["--suite", "int", "--report"],
            repo_root=repo_root,
        )



def test_sandbox_report_arguments_preserves_forwarded_selectors(tmp_path):
    module = sandbox_owner
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    inner_argv, report_dest = module._sandbox_report_arguments(
        [
            "--suite",
            "int",
            "--report",
            "--report-dir",
            "custom-report",
            "--",
            "test_file.py::test_fn",
        ],
        repo_root=repo_root,
    )
    assert report_dest == repo_root / "custom-report"
    assert inner_argv == [
        "--suite",
        "int",
        "--report",
        "--report-dir",
        str(module.INNER_REPORT_ROOT),
        "--",
        "test_file.py::test_fn",
    ]


def test_sandbox_report_arguments_rewrites_gate_request_without_report(tmp_path):
    module = sandbox_owner
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    req_file = repo_root / "gate-request.json"
    req_content = b'{"schema": "repomap-ci-gate-request-v1", "gate_kind": "main-system"}'
    req_file.write_bytes(req_content)

    res = module._sandbox_report_arguments(
        ["--suite", "system", "--gate-request-json", str(req_file)],
        repo_root=repo_root,
    )
    inner_argv, report_destination = res
    assert report_destination is None
    assert getattr(res, "gate_request_bytes", None) == req_content
    assert inner_argv == [
        "--suite",
        "system",
        "--gate-request-json",
        str(module.INNER_GATE_REQUEST_PATH),
    ]


