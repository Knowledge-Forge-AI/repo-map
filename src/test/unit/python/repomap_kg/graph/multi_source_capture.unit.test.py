from pathlib import Path
from unittest.mock import patch

import pytest

from repomap_kg.graph.discovery_records import FileInfo
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.graph.multi_source_capture import (
    MultiSourceCaptureError,
    _capture_files,
    _capture_inventory,
    _file_signature,
    _inventory_error,
    _manifest,
    _read_stable_file,
    _SourceCapture,
    _SourceChanged,
    _SourceInvalid,
    _SourceUnavailable,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig


def _binding(root: Path, alias: str) -> OpsGraphSourceBindingConfig:
    return OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id("fixture-graph", alias),
        source_definition_id=f"src1:{alias}",
        alias=alias,
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(root),
        root_path_expanded=str(root),
        repository_name=f"fixture-{alias}",
        logical_root=".",
        privacy="public-dev",
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=(),
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared",
        enabled=True,
        role="entry" if alias == "entry" else "module",
        input_name=None if alias == "entry" else alias,
    )


def _graph(*bindings: OpsGraphSourceBindingConfig) -> OpsGraphConfig:
    return OpsGraphConfig(
        id="fixture-graph",
        name="Fixture",
        root_path="",
        root_path_expanded="",
        repository_name="[multi-source]",
        privacy="public-dev",
        enabled=True,
        mcp_visible=True,
        extractor_profile="",
        refresh_policy="manual",
        source_bindings=tuple(bindings),
        explicit_source_bindings=True,
    )


def test_read_stable_file_adverse_retry_and_recovers(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("stable content", encoding="utf-8")
    stage1 = tmp_path / "staged1.txt"

    real_sig = _file_signature
    calls = 0

    def mutate_opened(details):
        nonlocal calls
        sig = real_sig(details)
        calls += 1
        return (sig[0], sig[1] + 1, *sig[2:]) if calls == 2 else sig

    with patch("repomap_kg.graph.multi_source_capture._file_signature", side_effect=mutate_opened):
        digest, size, exe = _read_stable_file(target, stage_path=stage1)
        assert size == len("stable content") and not exe
        assert stage1.read_text(encoding="utf-8") == "stable content"

    calls = 0
    stage2 = tmp_path / "staged2.txt"

    def mutate_after(details):
        nonlocal calls
        sig = real_sig(details)
        calls += 1
        return (sig[0], sig[1] + 1, *sig[2:]) if calls == 3 else sig

    with patch("repomap_kg.graph.multi_source_capture._file_signature", side_effect=mutate_after):
        digest, size, exe = _read_stable_file(target, stage_path=stage2)
        assert stage2.exists()


def test_read_stable_file_exhaustion_raises_source_changed(tmp_path):
    import itertools
    counter = itertools.count()
    target = tmp_path / "file.txt"
    target.write_text("content", encoding="utf-8")
    with (
        patch("repomap_kg.graph.multi_source_capture._file_signature", side_effect=lambda d: (next(counter), 0, 0, 0, 0, 0)),
        pytest.raises(_SourceChanged),
    ):
        _read_stable_file(target)


def test_unsafe_changing_entries_rejected(tmp_path):
    regular = tmp_path / "real.txt"
    regular.write_text("data", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(regular)
    with pytest.raises(_SourceInvalid):
        _read_stable_file(link)

    sub_dir = tmp_path / "subdir"
    sub_dir.mkdir()
    with pytest.raises(_SourceInvalid):
        _read_stable_file(sub_dir)

    for bad_path in ("../escape.nix", "/abs/root.nix"):
        with pytest.raises(_SourceInvalid):
            _capture_files(tmp_path, [FileInfo(bad_path, "nix", "source", "h", False, False)])

    with pytest.raises(_SourceChanged):
        _read_stable_file(tmp_path / "never_existed.txt")


def test_unavailable_source_rejected(tmp_path):
    plain = tmp_path / "plain.txt"
    plain.write_text("plain", encoding="utf-8")
    for bad_root in (tmp_path / "nonexistent", plain):
        with pytest.raises(MultiSourceCaptureError, match="source unavailable") as exc_info:
            _capture_inventory(_graph(_binding(bad_root, "entry")))
        assert exc_info.value.category == "source_unavailable"


def test_inventory_error_mapping():
    assert _inventory_error(_SourceUnavailable()).category == "source_unavailable"
    assert _inventory_error(_SourceChanged()).category == "source_changed"
    assert _inventory_error(_SourceInvalid()).category == "source_invalid"
    assert _inventory_error(_SourceCapture()).category == "source_capture"
    assert _inventory_error(RuntimeError()).category == "source_capture"


def test_manifest_and_file_signature(tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text("sample", encoding="utf-8")
    sig = _file_signature(sample.stat())
    assert len(sig) == 6
    files = [FileInfo("sample.txt", "text", "source", "0" * 64, False, False)]
    entries = _manifest(tmp_path, files, sizes={"sample.txt": len("sample")})
    assert len(entries) == 1 and entries[0].size_bytes == len("sample")
    entries_fallback = _manifest(tmp_path, files)
    assert len(entries_fallback) == 1 and entries_fallback[0].size_bytes == len("sample")
