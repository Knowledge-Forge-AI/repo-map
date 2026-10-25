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


def _parse_and_validate_runner_argv(raw_argv: list[str], repo_root: Path):
    import argparse
    from repomap_test_support import d12_core_image
    from repomap_test_support.resource_hygiene_policy import HygieneProfile
    import runner_arguments

    runner_argv, forwarded = runner_arguments.split_forwarded_args(raw_argv)
    parser = argparse.ArgumentParser()
    runner_arguments.add_runner_arguments(
        parser,
        hygiene_profiles=tuple(profile.value for profile in HygieneProfile),
        default_report_root=repo_root / ".test-reports",
        parse_jobs=runner_arguments.parse_jobs,
    )
    args = parser.parse_args(runner_argv)
    runner_arguments.validate_sandbox_admission_options(args)
    d12_core_image.validate_selection(args, forwarded, repo_root=REPO_ROOT, environ={})
    selections = runner_arguments.forwarded_selection_args(forwarded)
    runner_arguments.validate_forwarded_selections(
        ("int",),
        selections,
        {"unit": REPO_ROOT / "src/test/unit/python", "int": REPO_ROOT / "src/test/int/python"},
        REPO_ROOT,
    )
    return args, forwarded


def test_d12_preflight_argv_admits_and_transports_report_dir_without_html(tmp_path: Path) -> None:
    from repomap_test_support import d12_core_image

    module = sandbox_owner
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    report_dir = tmp_path / "d12-native-amd64-report"
    native_argv = [
        "--sandbox", "--suite", "int", "--no-coverage", "--jobs", "1",
        "--pg-container-port", "55433", "--d12-core-image-profile", "linux/amd64",
        "--d12-core-image-preflight", "--d12-core-image-source-sha256", "a" * 64,
        "--report-dir", str(report_dir), "--", d12_core_image.NODE_ID,
    ]
    args, forwarded = _parse_and_validate_runner_argv(native_argv, repo_root)
    assert args.d12_core_image_preflight is True and args.report is False
    assert forwarded == [d12_core_image.NODE_ID]

    with pytest.raises(d12_core_image.D12ProfileError, match="no --report"):
        _parse_and_validate_runner_argv(
            [*native_argv[: native_argv.index("--")], "--report", "--", *forwarded], repo_root
        )
    with pytest.raises(RuntimeError, match="--report requires coverage; omit --no-coverage"):
        _parse_and_validate_runner_argv(["--suite", "int", "--no-coverage", "--report"], repo_root)

    res = module._sandbox_report_arguments(native_argv, repo_root=repo_root)
    inner_argv, report_destination = res
    assert report_destination == report_dir
    assert getattr(res, "gate_request_bytes", None) is None
    assert "--report" not in inner_argv
    assert inner_argv[inner_argv.index("--report-dir") + 1] == str(module.INNER_REPORT_ROOT)
    assert inner_argv[-2:] == ["--", d12_core_image.NODE_ID]

    eq_dir = tmp_path / "eq-report"
    eq_inner, eq_dest = module._sandbox_report_arguments(
        [
            "--suite", "int", "--no-coverage", "--d12-core-image-profile", "linux/amd64",
            "--d12-core-image-preflight", f"--report-dir={eq_dir}", "--", d12_core_image.NODE_ID,
        ],
        repo_root=repo_root,
    )
    assert eq_dest == eq_dir and f"--report-dir={module.INNER_REPORT_ROOT}" in eq_inner
    assert "--report" not in eq_inner

    report_dir.mkdir()
    with pytest.raises(RuntimeError, match="destination .* already exists"):
        module._sandbox_report_arguments(native_argv, repo_root=repo_root)


def test_d12_profile_only_or_forwarded_preflight_does_not_activate_report_export(tmp_path: Path) -> None:
    from repomap_test_support import d12_core_image

    module = sandbox_owner
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    unused_dir = tmp_path / "unused-report"
    for candidate in (
        [
            "--suite", "int", "--no-coverage", "--d12-core-image-profile", "linux/amd64",
            "--report-dir", str(unused_dir), "--", d12_core_image.NODE_ID,
        ],
        [
            "--suite", "int", "--no-coverage", "--report-dir", str(unused_dir),
            "--", "--d12-core-image-preflight", d12_core_image.NODE_ID,
        ],
    ):
        inner, dest = module._sandbox_report_arguments(candidate, repo_root=repo_root)
        assert dest is None and inner == candidate
