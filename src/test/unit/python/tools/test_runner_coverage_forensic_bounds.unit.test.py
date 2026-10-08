"""Diagnostic metadata remains bounded and cannot disclose marker paths."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from runner_coverage_forensics import read_anomalous_shard_forensics


@pytest.fixture
def shard(tmp_path: Path) -> Path:
    path = tmp_path / ".coverage.fixture.pid12345.xyz"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE coverage_schema(version INTEGER);"
            "INSERT INTO coverage_schema VALUES (7);"
            "CREATE TABLE file(id INTEGER PRIMARY KEY, path TEXT);"
        )
    return path


def test_oversized_marker_cannot_expand_diagnostic_output(shard: Path) -> None:
    marker_dir = shard.parent / "child_procs"
    marker_dir.mkdir()
    (marker_dir / "12345.start").write_text(
        "ppid=42\nowner=" + "x" * 100_000 + "\n", encoding="utf-8"
    )
    valid, count, info, verdict = read_anomalous_shard_forensics(shard, shard.parent)
    assert (valid, count, verdict) == (True, 0, None)
    assert info is not None
    assert info.get("ppid") == 42
    assert len(str(info.get("test_owner", ""))) <= 128


def test_marker_owner_redacts_paths_and_credentials(shard: Path) -> None:
    marker_dir = shard.parent / "child_procs"
    marker_dir.mkdir()
    (marker_dir / "12345.start").write_text(
        "owner=/private/fixture/owner token=fixture-secret\n", encoding="utf-8"
    )
    _, _, info, _ = read_anomalous_shard_forensics(shard, shard.parent)
    assert info is not None
    assert "/private/fixture" not in str(info)
    assert "fixture-secret" not in str(info)


def test_symlink_marker_is_not_followed(shard: Path, tmp_path: Path) -> None:
    target = tmp_path / "external-marker"
    target.write_text("ppid=42\nowner=external-owner\n", encoding="utf-8")
    marker_dir = shard.parent / "child_procs"
    marker_dir.mkdir()
    (marker_dir / "12345.start").symlink_to(target)
    valid, count, info, verdict = read_anomalous_shard_forensics(shard, shard.parent)
    assert (valid, count, verdict) == (True, 0, None)
    assert info is not None
    assert "test_owner" not in info
    assert "ppid" not in info


def test_complete_marker_without_final_newline_retains_owner(shard: Path) -> None:
    marker_dir = shard.parent / "child_procs"
    marker_dir.mkdir()
    (marker_dir / "12345.start").write_text("ppid=42\nowner=fixture-owner", encoding="utf-8")
    _, _, info, _ = read_anomalous_shard_forensics(shard, shard.parent)
    assert info is not None
    assert info["test_owner"] == "fixture-owner"
