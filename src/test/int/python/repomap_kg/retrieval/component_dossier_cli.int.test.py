"""Actual dossier processes preserve import purity, exclusivity and safe refusals."""

from pathlib import Path
from typing import Any

import coverage

from repomap_test_support.w5_component_artifacts import make_component_pair
from repomap_test_support.w5_component_cli import build_argv, run_component_cli
from retrieval_semantic_component_dossier_io import read_component_dossier
from runner_coverage import ChildCoverageSession
from runner_coverage_receipts import read_registered_children


def test_cli_build_and_check_without_runtime_or_archived_code_imports(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    output = tmp_path / "dossier.json"
    built = run_component_cli(build_argv(sources, output))
    assert built.returncode == 0, built.stderr
    checked = run_component_cli(["check","--input",str(output)])
    assert checked.returncode == 0, checked.stderr
    report: Any = read_component_dossier(output)
    assert report["generations"][0]["component"]["artifact_correspondence_verified"] is True
    assert all(value is False for value in report["acceptance"].values())


def test_cli_refuses_overwrite_and_retains_original(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    output = tmp_path / "dossier.json"
    argv = build_argv(sources, output)
    assert run_component_cli(argv).returncode == 0
    original = output.read_bytes()
    refused = run_component_cli(argv)
    assert refused.returncode == 3
    assert output.read_bytes() == original
    assert str(output) not in refused.stderr


def test_cli_partial_bundle_refuses_without_emitting_output(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    (sources.models[1]/"report.json").unlink()
    output = tmp_path / "dossier.json"
    refused = run_component_cli(build_argv(sources, output))
    assert refused.returncode == 3
    assert not output.exists()
    assert str(sources.models[1]) not in refused.stderr


def test_build_and_check_compose_with_registered_isolated_children(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path / "inputs")
    output = tmp_path / "dossier.json"
    selected = tmp_path / "synthetic-selection"
    selected.mkdir()
    fixture = selected / "unexecuted_fixture.py"
    fixture.write_text("VALUE = 1\n")
    session = ChildCoverageSession(
        coverage_module=coverage, scratch_dir=tmp_path / "registration-fixture",
        source_root=selected,
    )
    try:
        with session:
            built = run_component_cli(build_argv(sources, output))
            assert built.returncode == 0, built.stderr
            original = output.read_bytes()
            checked = run_component_cli(["check", "--input", str(output)])
            assert checked.returncode == 0, checked.stderr
            assert output.read_bytes() == original
            children = read_registered_children(
                session.child_manifest_dir, expected_invocation=session.invocation_id,
                expected_suite=session.suite,
            )
            assert len(children) == 2
            declared = set()
            for child in children.values():
                assert child["exited"] and child["cov_start"] == 1
                assert not child["bootstrap_error"] and not child["terminal_error"]
                shard = Path(child["shard"])
                declared.add(str(shard.resolve()))
                data = coverage.CoverageData(basename=str(shard))
                data.read()
                assert data.measured_files() <= {str(fixture.resolve())}
                assert not data.lines(str(fixture.resolve()))
            actual = {str(path.resolve()) for path in session.data_dir.glob(".coverage*")}
            assert actual == declared
    finally:
        session.cleanup()
