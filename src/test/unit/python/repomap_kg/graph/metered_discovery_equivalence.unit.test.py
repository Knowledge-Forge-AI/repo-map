"""Metered walker and classification readers equal the incumbent discovery results."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import common_lore_index.graph.discovery as discovery
from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.artifacts.sealing_governance import (
    CLASSIFICATION_MAX_RETAINED_CHARS,
    SealingBudget,
    SealingBudgetExceeded,
)
from common_lore_index.extractors.shell.zsh_identity import is_zsh_completion_candidate
from common_lore_index.graph._discovery_classify import is_go_generated_file
from common_lore_index.graph._metered_classification import (
    metered_completion,
    metered_first_line,
    metered_is_go_generated,
)
from common_lore_index.graph._metered_discovery import MeteredDiscoveryHooks, metered_walk
from common_lore_index.graph.discovery_file_metadata import first_line


def _observe() -> SealingMeter:
    return SealingMeter(None, governed=False)


def _tree(root: Path) -> Path:
    files = {
        "README.md": b"# x\n", "src/app.py": b"x = 1\n", "src/run.sh": b"#!/bin/bash\necho\n",
        "src/deep/z.txt": b"z\n", "build/out.txt": b"ignored\n", "node_modules/m.js": b"m\n",
        "vendor/keep.txt": b"k\n", "notes/skip.md": b"s\n", ".profile": b"export A=1\n",
        "tool": b"#!/usr/bin/env python3\n", "_comp": b"#compdef x\n",
        "logs/a.log": b"l\n", "logs/b.log": b"l\n",
    }
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / "src" / "inside").symlink_to(root / "src" / "deep")
    (root / "outside").symlink_to(root.parent)
    (root / "src" / "alias.py").symlink_to(root / "src" / "app.py")
    (root / "escape.txt").symlink_to(root.parent / "elsewhere.txt")
    (root.parent / "elsewhere.txt").write_text("outside\n")
    os.mkfifo(root / "fifo")
    return root


def test_metered_walk_equals_os_walk_including_pruning(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")

    def collect(walk) -> list[tuple[str, list[str], list[str]]]:
        rows = []
        for directory, dirnames, filenames in walk:
            rows.append((directory, sorted(dirnames), sorted(filenames)))
            dirnames[:] = sorted(name for name in dirnames if name != "build")
        return rows

    meter = _observe()
    assert collect(metered_walk(root, meter)) == collect(os.walk(root))
    expected_entries = sum(len(d) + len(f) for _, d, f in collect(os.walk(root)))
    assert meter.snapshot().directory_entries == expected_entries
    assert meter.snapshot().opens == len(collect(os.walk(root)))


def test_unreadable_or_vanished_listings_are_skipped_like_onerror_none(tmp_path: Path, monkeypatch) -> None:
    root = _tree(tmp_path / "repo")
    real_scandir = os.scandir

    def failing_scandir(path):
        if str(path).endswith("deep"):
            raise PermissionError(13, "denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", failing_scandir)
    meter = _observe()
    walked = [directory for directory, _, _ in metered_walk(root, meter)]
    assert all(not item.endswith("deep") for item in walked)
    assert [d for d, _, _ in os.walk(root)] == walked
    assert meter.snapshot().opens == len(walked) + 1, "the failed listing attempt still counts"


@pytest.mark.parametrize("exclude_paths", [(), ("notes",), ("logs/*.log",), ("src/deep/z.txt", "*.md")])
def test_metered_discovery_equals_incumbent_discovery(tmp_path: Path, exclude_paths) -> None:
    root = _tree(tmp_path / "repo")
    expected = discovery.discover_repository(root, exclude_paths=exclude_paths)
    meter = _observe()
    assert discovery.discover_repository(
        root, exclude_paths=exclude_paths, io_hooks=MeteredDiscoveryHooks(meter)
    ) == expected
    snapshot = meter.snapshot()
    # R1 hashes every selected entry; the in-root alias of src/app.py is hashed
    # before path deduplication, so its bytes are read once more.
    alias_bytes = len(b"x = 1\n")
    assert snapshot.reader("discovery") == alias_bytes + sum(
        (root / item.path).stat().st_size for item in expected
    )
    assert snapshot.reader("classification") > 0


def test_classify_path_patch_seam_still_routes_default_discovery(tmp_path: Path, monkeypatch) -> None:
    root = _tree(tmp_path / "repo")
    seen: list[str] = []
    real = discovery.classify_path

    def spy(repository_root, file_path, *, profile=None):
        seen.append(file_path.name)
        return real(repository_root, file_path, profile=profile)

    monkeypatch.setattr(discovery, "classify_path", spy)
    discovery.discover_repository(root)
    assert "app.py" in seen and "out.txt" not in seen


def test_governed_entry_ceiling_bounds_traversal_including_filtered_entries(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    total = sum(len(d) + len(f) for _, d, f in os.walk(root))
    meter = SealingMeter(SealingBudget(max_directory_entries=3), governed=True)
    with pytest.raises(SealingBudgetExceeded, match="directory_entries"):
        discovery.discover_repository(root, io_hooks=MeteredDiscoveryHooks(meter))
    assert meter.snapshot().directory_entries == 3 < total
    empty = tmp_path / "empty"
    empty.mkdir()
    assert discovery.discover_repository(
        empty,
        io_hooks=MeteredDiscoveryHooks(
            SealingMeter(SealingBudget(max_directory_entries=0), governed=True)
        ),
    ) == []


FIRST_LINES = [
    b"#!/bin/zsh\nrest\n", b"#!/bin/bash\r\nx\n", b"\r#!/bin/zsh\n", b"   \t#!/usr/bin/env zsh\n",
    b"\xef\xbb\xbf#!/bin/zsh\n", b"echo\n\xff\n", b"#!" + b"z" * 9000 + b"\n", b"x" * 9000 + b"\n\xff",
    b"#!/bin/" + b"\xff" + b"zsh\n", b"plain\xe2\x80", b" " * 5000 + b"#!/bin/zsh\n", b"",
    b"#\n!", "#!/bin/zsh tail\n".encode(),
]


@pytest.mark.parametrize("data", FIRST_LINES)
def test_first_line_reader_preserves_every_shebang_decision(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "script"
    path.write_bytes(data)
    expected = first_line(path)
    observed = metered_first_line(_observe(), path)
    assert observed.startswith("#!") == expected.startswith("#!")
    if expected.startswith("#!"):
        assert observed == expected
    assert discovery.detect_language(path) == discovery.detect_language(
        path, first_line_fn=lambda item: metered_first_line(_observe(), item),
        completion_fn=lambda item: metered_completion(_observe(), item),
    )


def test_profile_reaches_the_first_line_reader_twice_and_each_read_is_metered(tmp_path: Path) -> None:
    path = tmp_path / ".profile"
    path.write_bytes(b"export A=1\n")
    meter = _observe()
    language = discovery.detect_language(
        path, first_line_fn=lambda item: metered_first_line(meter, item),
        completion_fn=lambda item: metered_completion(meter, item),
    )
    assert language == discovery.detect_language(path)
    assert meter.snapshot().opens == 3, "two R2 reads plus the R4 completion check"


def test_first_line_governed_retention_refuses_an_unbounded_shebang(tmp_path: Path) -> None:
    path = tmp_path / "long.sh"
    path.write_bytes(b"#!" + b"a" * CLASSIFICATION_MAX_RETAINED_CHARS + b"\n")
    with pytest.raises(SealingBudgetExceeded, match="classification_retention"):
        metered_first_line(SealingMeter(None, governed=True), path)
    assert metered_first_line(_observe(), path) == first_line(path), "observe-only keeps unbounded retention"
    early = tmp_path / "early.sh"
    early.write_bytes(b"x" * (2 * CLASSIFICATION_MAX_RETAINED_CHARS) + b"\n")
    assert not metered_first_line(SealingMeter(None, governed=True), early).startswith("#!")


GO_FILES = [
    b"// Code generated by tool. DO NOT EDIT.\npackage x\n", b"package x\n" * 50,
    b"package x\n" * 39 + b"// Code generated by y. DO NOT EDIT.\n",
    b"package x\n" * 41 + b"\xff\n", b"package x\n\xff\n// Code generated by t. DO NOT EDIT.\n",
    b"package x\n" * 30 + b"\xff" * 9000, b"\r\n".join([b"// Code generated by c. DO NOT EDIT."] * 2),
]


@pytest.mark.parametrize("data", GO_FILES)
def test_go_generated_reader_keeps_the_forty_line_decode_result(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "file.go"
    path.write_bytes(data)
    expected = is_go_generated_file(path)
    assert metered_is_go_generated(_observe(), path) is expected
    assert metered_is_go_generated(SealingMeter(None, governed=True), path) is expected


def test_go_reader_combined_governed_retention_refuses_intentionally(tmp_path: Path) -> None:
    path = tmp_path / "big.go"
    line = b"// Code generated by tool. DO NOT EDIT." + b" " * 40_000 + b"\n"
    path.write_bytes(line * 30)
    assert is_go_generated_file(path) is True
    with pytest.raises(SealingBudgetExceeded, match="classification_retention"):
        metered_is_go_generated(SealingMeter(None, governed=True), path)
    assert metered_is_go_generated(_observe(), path) is True


COMPLETIONS = [
    b"#compdef foo\n", b"  \t_arguments '-x'\n", b"\r\n\r\n#compdef x", b"\xef\xbb\xbf#compdef x\n",
    b"echo\r_arguments\n", "echo #compdef x\n".encode(), "echo\x85  _arguments\n".encode(),
    b"#compde\nf\n", b"x#compdef\n", b"#compdef x\n\xff", b"#comp" + b"\xc3", b"_argumentsXYZ\n",
    "\x1f#compdef\n".encode(), "\x0b\x0c\x1c_arguments\n".encode(), b"", b"#compdef" * 100_000,
]


@pytest.mark.parametrize("data", COMPLETIONS)
def test_completion_stream_equals_read_text_splitlines_semantics(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "candidate"
    path.write_bytes(data)
    meter = _observe()
    assert metered_completion(meter, path) is is_zsh_completion_candidate(path)
    assert meter.snapshot().reader("classification") == len(data), "R4 reads to EOF"


def test_completion_name_rule_and_unreadable_files_match_without_reading(tmp_path: Path) -> None:
    directory = tmp_path / "functions"
    directory.mkdir()
    named = directory / "_tool"
    named.write_bytes(b"\xff")
    meter = _observe()
    assert metered_completion(meter, named) is True and meter.snapshot().opens == 0
    assert metered_completion(meter, tmp_path / "missing") is is_zsh_completion_candidate(tmp_path / "missing")


def test_completion_refuses_a_body_beyond_the_read_budget_before_opening(tmp_path: Path) -> None:
    path = tmp_path / "candidate"
    path.write_bytes(b"x" * 100)
    meter = SealingMeter(SealingBudget(max_read_bytes=99), governed=True)
    with pytest.raises(SealingBudgetExceeded, match="read_bytes"):
        metered_completion(meter, path)
    assert meter.snapshot().opens == 0
