"""Fresh-process import and CLI checks cover the new reader's full closure."""

from pathlib import Path

import coverage
import pytest

from repomap_test_support.w5_component_artifacts import make_component_pair
from repomap_test_support.w5_component_cli import build_argv, run_component_cli
from runner_coverage import ChildCoverageSession
from runner_coverage_receipts import read_registered_children


def test_new_owner_import_closure_never_loads_inference_or_archived_sources(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    output = tmp_path / "dossier.json"
    completed = run_component_cli(build_argv(sources, output))
    assert completed.returncode == 0, completed.stderr
    assert output.is_file()


@pytest.mark.parametrize("refused", [False, True])
def test_isolated_cli_keeps_registered_terminal_and_shard_receipts(tmp_path: Path, refused: bool) -> None:
    sources = make_component_pair(tmp_path / "artifacts")
    output = tmp_path / "dossier.json"
    if refused:
        (sources.models[1] / "report.json").unlink()
    selected = tmp_path / "synthetic-source"
    selected.mkdir()
    (selected / "unused_fixture.py").write_text("VALUE = 1\n")
    session = ChildCoverageSession(
        coverage_module=coverage, scratch_dir=tmp_path / "coverage-fixture",
        source_root=selected,
    )
    try:
        with session:
            completed = run_component_cli(build_argv(sources, output))
            assert completed.returncode == (3 if refused else 0), completed.stderr
            children = read_registered_children(session.child_manifest_dir)
            assert len(children) == 1
            pid, child = next(iter(children.items()))
            assert child["invocation"] == session.invocation_id
            assert child["launch_shape"] == "cpython:-c"
            assert child["cov_start"] == 1
            assert child["exited"] and not child["bootstrap_error"]
            assert not child["terminal_error"]
            terminal = (session.child_manifest_dir / f"{pid}.exit").read_text()
            assert "complete=1" in terminal and "error=" in terminal
            shard = next(line[6:] for line in terminal.splitlines() if line.startswith("shard="))
            actual = {str(path.resolve()) for path in session.data_dir.glob(".coverage*")}
            assert actual == {str(Path(shard).resolve())}
            measured = coverage.CoverageData(basename=shard)
            measured.read()
            fixture = str((selected / "unused_fixture.py").resolve())
            assert measured.measured_files() <= {fixture}
            assert not measured.lines(fixture)
            assert not session.measurement_errors
    finally:
        session.cleanup()
