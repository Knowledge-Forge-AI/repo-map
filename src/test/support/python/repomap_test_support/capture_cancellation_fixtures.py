"""Real capture IO witnesses, isolated from global OS and store behavior."""
from __future__ import annotations
from dataclasses import replace
import os
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO, cast
import pytest
from common_lore_index.graph import multi_source_capture as capture
from common_lore_index.ops.config_records import OpsGraphConfig
from repomap_test_support.materialization_fixtures import SourceProbe
from repomap_test_support.portable_publication_fixtures import create_single_source_graph_config

CAPTURE_CHUNK = 1024 * 1024


def capture_graph(root: Path, *, large: bool = False) -> OpsGraphConfig:
    root.mkdir()
    if large:
        (root / "public.payload").write_bytes(b"# public fixture\n" + b"#" * (3 * CAPTURE_CHUNK) + b"\n")
    (root / "public.py").write_bytes(b"def public_value():\n    return 7\n")
    graph = create_single_source_graph_config(root, graph_id="capture-control", repository_name="public-capture")
    return replace(graph, source_bindings=graph.effective_source_bindings, explicit_source_bindings=True)


def observe_capture_io(monkeypatch: pytest.MonkeyPatch, on_chunk):
    consumed: list[int] = []
    written: list[int] = []
    sources: list[SourceProbe] = []
    original_fdopen, original_open = os.fdopen, Path.open

    def opened(descriptor, mode="r", *args, **kwargs):
        raw = original_fdopen(descriptor, mode, *args, **kwargs)
        probe = SourceProbe(raw, consumed, [], on_chunk)
        sources.append(probe)
        return cast(BinaryIO, probe)

    def path_open(path, mode="r", *args, **kwargs):
        raw = original_open(path, mode, *args, **kwargs)
        if mode != "wb":
            return raw

        def write(data):
            count = raw.write(data)
            written.append(count)
            return count

        return cast(BinaryIO, SimpleNamespace(write=write, close=raw.close))

    facade = {name: getattr(os, name) for name in dir(os) if not name.startswith("__")}
    facade["fdopen"] = opened
    monkeypatch.setattr(capture, "os", SimpleNamespace(**facade))
    monkeypatch.setattr(Path, "open", path_open)
    return consumed, written, sources
