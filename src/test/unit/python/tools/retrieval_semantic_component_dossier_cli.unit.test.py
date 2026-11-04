"""Exclusive outputs and public-safe artifact-refusal CLI behavior."""

from pathlib import Path
from typing import Any

import pytest

import retrieval_semantic_component_dossier_io as io_module
from repomap_test_support.w5_component_artifacts import make_component_pair
from retrieval_semantic_component_dossier import build_component_dossier, main
from retrieval_semantic_component_dossier_io import read_component_dossier, write_component_dossier
from retrieval_semantic_pair_artifacts import PairReportRefusal


def test_output_round_trip_and_no_overwrite(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    report = build_component_dossier(sources.journals, sources.results, sources.paired, sources.models)
    output = tmp_path / "dossier.json"
    digest = write_component_dossier(output, report)
    assert digest.startswith("sha256:")
    assert read_component_dossier(output) == report
    original = output.read_bytes()
    with pytest.raises(PairReportRefusal, match="dossier_output"):
        write_component_dossier(output, report)
    assert output.read_bytes() == original


def test_output_symlink_does_not_mutate_target(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    report = build_component_dossier(sources.journals, sources.results, sources.paired)
    target = tmp_path / "target"
    target.write_bytes(b"preserve")
    output = tmp_path / "dossier.json"
    output.symlink_to(target)
    with pytest.raises(PairReportRefusal):
        write_component_dossier(output, report)
    assert target.read_bytes() == b"preserve"


@pytest.mark.parametrize("raw", [b'{}\n', b'{"schema":1,"schema":2}\n', b'{"value":NaN}\n', b'[]\n'])
def test_structural_reader_refuses_invalid_json(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "input.json"
    path.write_bytes(raw)
    with pytest.raises(PairReportRefusal):
        read_component_dossier(path)


def test_structural_check_does_not_reopen_original_sources(tmp_path: Path) -> None:
    sources = make_component_pair(tmp_path)
    report = build_component_dossier(sources.journals, sources.results, sources.paired)
    output = tmp_path / "dossier.json"
    write_component_dossier(output, report)
    for path in sources.results.values(): path.unlink()
    sources.paired.unlink()
    assert main(["check","--input",str(output)]) == 0


def test_cli_refusal_exit_is_three_and_path_is_not_disclosed(tmp_path: Path, capsys: Any) -> None:
    missing = tmp_path / "private-input-must-not-appear"
    with pytest.raises(SystemExit) as caught:
        main(["check","--input",str(missing)])
    assert caught.value.code == 3
    output = capsys.readouterr()
    assert str(missing) not in output.err
    assert "dossier refused:" in output.err


def test_short_writes_are_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = make_component_pair(tmp_path)
    report = build_component_dossier(sources.journals, sources.results, sources.paired)
    original = io_module.os.write
    def short_write(descriptor, raw):
        return original(descriptor, raw[:37])
    monkeypatch.setattr(io_module.os,"write",short_write)
    output = tmp_path / "dossier.json"
    write_component_dossier(output, report)
    assert read_component_dossier(output) == report


def test_write_failure_removes_only_owned_partial_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = make_component_pair(tmp_path)
    report = build_component_dossier(sources.journals, sources.results, sources.paired)
    def failed_write(*_args):
        raise OSError("/private/fixture failure detail")
    monkeypatch.setattr(io_module.os,"write",failed_write)
    output = tmp_path / "dossier.json"
    with pytest.raises(PairReportRefusal, match="^dossier_output$"):
        write_component_dossier(output, report)
    assert not output.exists()


def test_cleanup_failure_is_a_closed_refusal_and_retains_owned_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = make_component_pair(tmp_path)
    report = build_component_dossier(sources.journals, sources.results, sources.paired)
    output = tmp_path / "dossier.json"
    original_unlink = Path.unlink
    def failed_write(*_args):
        raise OSError("private detail")
    def failed_unlink(path, *args, **kwargs):
        if path == output:
            raise OSError("private cleanup detail")
        return original_unlink(path, *args, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(io_module.os,"write",failed_write)
        scoped.setattr(Path,"unlink",failed_unlink)
        with pytest.raises(PairReportRefusal, match="^dossier_output_cleanup$"):
            write_component_dossier(output, report)
    assert output.exists()
    output.unlink()
