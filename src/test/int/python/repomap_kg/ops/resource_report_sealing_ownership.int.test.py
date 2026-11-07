"""Connected real-filesystem evidence for sealing directory-descriptor ownership.

This proves Python ownership under an injected previous-descriptor close
failure on a real nested tree; it is not a claim of recovery from every kernel
close state. Capture limits and body/digest/metadata rules are unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

import common_lore_index.artifacts._source_sealing_io as sealing_io
from common_lore_index.artifacts._source_sealing_io import open_source_body
from common_lore_index.cli.main import main
from repomap_test_support.resource_report_cli_files import private_directory, report_payload
from repomap_test_support.sqlite_local_fixtures import SHELL_LIB, graph_toml, write_sqlite_home

DEPTH = ("alpha", "beta", "gamma", "delta")


def _nested_source(root: Path) -> Path:
    nested = root.joinpath(*DEPTH)
    nested.mkdir(parents=True)
    (nested / "lib.sh").write_text(SHELL_LIB, encoding="utf-8")
    return root


def _open_count() -> int:
    return len(os.listdir("/dev/fd"))


def _body(root: Path) -> bytes:
    data = SHELL_LIB.encode("utf-8")
    with open_source_body(
        root, "/".join((*DEPTH, "lib.sh")), expected_size=len(data),
        expected_digest=hashlib.sha256(data).hexdigest(), expected_executable=False,
    ) as body:
        return b"".join(body)


@pytest.mark.parametrize("failing_level", (0, 2))
def test_previous_close_failure_on_a_real_tree_keeps_custody_and_leaks_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_level: int,
) -> None:
    root = _nested_source(tmp_path / "source")
    assert sealing_io._supports_dir_fd(), "the qualified integration platform must support anchored IO"
    original_open, original_close = os.open, os.close
    directories: list[int] = []
    active: dict[int, int] = {}
    closes: list[int] = []
    injected = OSError(5, "injected previous directory close failure")

    def recording_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        descriptor = original_open(path, flags, *args, **kwargs)
        if flags & getattr(os, "O_DIRECTORY", 0):
            active[descriptor] = len(directories)
            directories.append(descriptor)
        return descriptor

    def failing_close(descriptor: int) -> None:
        opened = active.pop(descriptor, None)
        if opened is not None:
            closes.append(opened)
        if opened == failing_level and len(directories) == failing_level + 2:
            original_close(descriptor)
            raise injected
        original_close(descriptor)

    before = _open_count()
    monkeypatch.setattr(sealing_io.os, "open", recording_open)
    monkeypatch.setattr(sealing_io.os, "close", failing_close)
    # Instrumentation must preserve the real opener's existing OS capability.
    monkeypatch.setattr(sealing_io.os, "supports_dir_fd", os.supports_dir_fd | {recording_open})
    with pytest.raises(OSError) as raised:
        _body(root)
    monkeypatch.undo()
    assert raised.value is injected
    # Descriptor numbers may be reused; each open instance still closes once.
    assert sorted(closes) == list(range(len(directories))) and not active, (directories, closes)
    assert _open_count() == before, "every directory descriptor was closed exactly once"
    assert _body(root) == SHELL_LIB.encode("utf-8")


def test_local_refresh_of_a_nested_tree_still_publishes_with_a_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    source = _nested_source(tmp_path / "source")
    home = write_sqlite_home(tmp_path / "home", graph_toml("nested", source))
    reports = private_directory(tmp_path / "reports")
    assert main(["ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "nested"]) == 0
    capsys.readouterr()
    assert main(["ops", "refresh-graph", "--repo-map-home", str(home), "--graph", "nested", "--json",
                 "--resource-report", str(reports / "nested.json")]) == 0
    assert json.loads(capsys.readouterr().out)["accepted_generation"] == 1
    payload = report_payload(reports / "nested.json", operation="local_refresh", backend="sqlite",
                             outcome="published", forbidden=(source, "alpha", "lib.sh"))
    files = next(item for item in payload["metrics"] if item["name"] == "sealed_manifest_files")
    assert files["value"] == 1
