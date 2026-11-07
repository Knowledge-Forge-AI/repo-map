"""Metadata-only report separation across configured roots and inode aliases."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from common_lore_index.ops.resource_reports import _admission as admission
from repomap_test_support.resource_report_cli_files import private_directory


def _refused(target: Path, roots: tuple[str, ...]) -> None:
    try:
        destination = admission.admit_report_destination(str(target), roots)
    except admission.ResourceReportRefusal as error:
        assert error.category == "protected_root_overlap"
    else:
        destination.close()
        pytest.fail("report destination overlapped a protected source identity")
    assert not target.exists()


def test_metadata_alias_is_refused_even_when_resolved_spellings_differ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = private_directory(tmp_path / "configured-source")
    reports = private_directory(tmp_path / "alternate-mount")
    real_stat = os.stat

    def stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        # Model the metadata relationship of a case-insensitive or bind alias.
        # All actual destination descriptors and all other metadata stay real.
        if path == source:
            return real_stat(reports, *args, **kwargs)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(admission.os, "stat", stat)
    _refused(reports / "report.json", (str(source),))


def test_case_variant_paths_follow_actual_identity_without_casefold_false_positives(
    tmp_path: Path,
) -> None:
    source = private_directory(tmp_path / "Source")
    reports = private_directory(source / "reports")
    alternate = tmp_path / "SOURCE"
    if alternate.exists():
        assert os.path.samefile(source, alternate)
        _refused(alternate / "reports" / "report.json", (str(source),))
    else:
        separate = private_directory(alternate)
        target = separate / "report.json"
        destination = admission.admit_report_destination(str(target), (str(source),))
        destination.close()
        assert not target.exists() and reports.is_dir()


def test_external_server_memory_directory_is_a_configured_source(tmp_path: Path) -> None:
    memory = private_directory(tmp_path / "server-memory")
    config = SimpleNamespace(
        config_home=str(tmp_path / "home"), config_path=None, graphs=(),
        server_memory=SimpleNamespace(enabled=False, path_expanded=str(memory)),
    )
    _refused(memory / "report.jsonl", admission.configured_roots(config))


def test_config_file_alias_protects_its_resolved_control_directory(tmp_path: Path) -> None:
    launcher = private_directory(tmp_path / "launcher")
    control = private_directory(tmp_path / "control")
    actual = control / "config.toml"
    actual.write_text("# synthetic config metadata only\n", encoding="utf-8")
    alias = launcher / "config.toml"
    alias.symlink_to(actual)
    reports = private_directory(control / "reports")
    config = SimpleNamespace(config_home=None, config_path=str(alias), graphs=())
    _refused(reports / "report.json", admission.configured_roots(config))
