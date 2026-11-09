from __future__ import annotations

import os
from pathlib import Path

import pytest

from common_lore_index.artifacts._manifest_records import ArtifactLimits
from common_lore_index.artifacts._sealing_meter import SealingMeter
from common_lore_index.graph._canonical_selection import canonical_relative_path
from common_lore_index.graph._metered_discovery import preflight_inventory
from common_lore_index.graph._sealing_scan import scan_sealing_generations
from common_lore_index.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from common_lore_index.graph.multi_source_pipeline import scan_multi_source_generations
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig


def _graph(root: Path, excludes: tuple[str, ...] = ()) -> OpsGraphConfig:
    binding = OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id("governance3", "entry"),
        source_definition_id="src1:entry",
        alias="entry",
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(root),
        root_path_expanded=str(root),
        repository_name="governance3",
        logical_root=".",
        privacy="public-dev",
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=excludes,
        selection_policy_id=source_selection_policy_id((), excludes),
        resolution_policy="allow-declared",
        enabled=True,
        role="entry",
        input_name=None,
    )
    return OpsGraphConfig(
        id="governance3",
        name="Governance 3",
        root_path="",
        root_path_expanded="",
        repository_name="governance3",
        privacy="public-dev",
        enabled=True,
        mcp_visible=True,
        extractor_profile="default",
        refresh_policy="manual",
        source_bindings=(binding,),
        explicit_source_bindings=True,
    )


def _paths(scan) -> tuple[str, ...]:
    return tuple(item.relative_path for item in scan.snapshots[0].manifest_entries)


def test_capture_only_matches_incumbent_across_real_selection_matrix(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    (root / "ignored" / "nested").mkdir(parents=True)
    (root / "excluded").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / ".profile").write_bytes(b"export PROFILE=1\n")
    (root / "script.sh").write_bytes(b"#!/bin/sh\necho ok\n")
    (root / "main.go").write_bytes(b"package main\n")
    (root / "unknown.bin").write_bytes(b"\x00\xffopaque\n")
    (root / "invalid.utf8").write_bytes(b"\xff\xfe\x00\n")
    (root / "empty").write_bytes(b"")
    (root / "ignored" / "nested" / "hidden.txt").write_bytes(b"ignored\n")
    (root / "excluded" / "secret.txt").write_bytes(b"excluded target\n")
    (outside / "escape.txt").write_bytes(b"outside\n")
    (root / "inside-alias.go").symlink_to(root / "main.go")
    (root / "alias-to-excluded.txt").symlink_to(root / "excluded" / "secret.txt")
    (root / "escaping-link.txt").symlink_to(outside / "escape.txt")
    if hasattr(os, "mkfifo"):
        os.mkfifo(root / "pipe.fifo")

    graph = _graph(root, ("ignored", "excluded"))
    incumbent = scan_multi_source_generations(graph)
    capture_only = scan_sealing_generations(graph)

    assert capture_only.source_generation == incumbent.source_generation
    assert capture_only.config_generation == incumbent.config_generation
    assert capture_only.snapshots == incumbent.snapshots
    assert _paths(capture_only) == (
        ".profile",
        "empty",
        "excluded/secret.txt",
        "invalid.utf8",
        "main.go",
        "script.sh",
        "unknown.bin",
    )


def test_preflight_and_capture_share_canonical_alias_deduplication(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    target = root / "main.go"
    target.write_bytes(b"package main\n")
    (root / "alias.go").symlink_to(target)
    graph = _graph(root)
    meter = SealingMeter(None, governed=True)

    plan = preflight_inventory(graph, meter, ArtifactLimits())
    scan = scan_sealing_generations(graph)

    assert plan.inventory_files == 1
    assert plan.inventory_bytes == target.stat().st_size
    assert plan.inventory_symlinked_files == 1
    assert _paths(scan) == ("main.go",)
    assert meter.snapshot().reader("discovery") == 0


def test_capture_only_scan_respects_excluded_alias_target_and_canonical_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    (root / "private").mkdir(parents=True)
    (root / "private" / "secret.txt").write_text("private\n", encoding="utf-8")
    os.symlink(root / "private" / "secret.txt", root / "alias.txt")
    graph = _graph(root, ("private",))
    scan = scan_sealing_generations(graph)
    assert _paths(scan) == ("private/secret.txt",)
    assert canonical_relative_path(
        root.resolve(), root / "private" / "secret.txt"
    ) == "private/secret.txt"


def test_capture_only_scan_keeps_read_stable_file_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    graph = _graph(root)
    calls = 0
    import common_lore_index.graph.multi_source_capture as capture

    original = capture._read_stable_file

    def counted(path: Path, *, stage_path: Path | None = None):
        nonlocal calls
        calls += 1
        return original(path, stage_path=stage_path)

    monkeypatch.setattr(capture, "_read_stable_file", counted)
    scan_sealing_generations(graph)
    assert calls == 1
