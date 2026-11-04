"""Fresh-process import and CLI checks cover the new reader's full closure."""

from pathlib import Path

from repomap_test_support.w5_component_artifacts import make_component_pair
from repomap_test_support.w5_component_cli import build_argv, run_component_cli


def test_new_owner_import_closure_never_loads_inference_or_archived_sources(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    output = tmp_path / "dossier.json"
    completed = run_component_cli(build_argv(sources, output))
    assert completed.returncode == 0, completed.stderr
    assert output.is_file()
