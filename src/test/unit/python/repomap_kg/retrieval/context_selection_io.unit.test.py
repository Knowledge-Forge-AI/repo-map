"""Selection-file bounded I/O regressions for W4 context records."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from common_lore_index.retrieval.context_contracts import ContextRequestError
from common_lore_index.retrieval.source_selection import (
    MAX_SELECTION_FILE_BYTES,
    SourceBindingSelection,
    SourceSelectionRecord,
)
import common_lore_index.retrieval.source_selection as source_selection


def _record() -> SourceSelectionRecord:
    return SourceSelectionRecord.build(
        graph_id="selection-io-graph",
        repository_id="repo1:selection-io-graph",
        backend="sqlite",
        bindings=(
            SourceBindingSelection(
                binding_id="bind1:core",
                revision=1,
                snapshot_id=None,
                selection_policy_id="select1:default",
                source_definition_id="src1:core",
            ),
        ),
    )


def test_write_selection_file_handles_short_os_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "selection.json"
    record = _record()
    real_write = source_selection.os.write
    calls: list[int] = []

    def short_write(fd: int, data: bytes) -> int:
        calls.append(len(data))
        return real_write(fd, data[:1] if len(data) > 1 else data)

    monkeypatch.setattr(source_selection.os, "write", short_write)
    raw = source_selection.write_selection_file(record, output)

    assert len(calls) > 1
    assert output.read_bytes() == raw


def test_read_selection_file_refuses_growth_before_an_over_limit_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "selection.json"
    output.write_bytes(
        (source_selection.json.dumps(_record().to_dict(), separators=(",", ":")) + "\n").encode()
    )
    real_fstat = source_selection.os.fstat
    calls = 0

    def growing_fstat(fd: int) -> object:
        nonlocal calls
        calls += 1
        stat_result = real_fstat(fd)
        if calls == 3:
            return SimpleNamespace(
                st_mode=stat_result.st_mode,
                st_size=stat_result.st_size + 1,
            )
        return stat_result

    monkeypatch.setattr(source_selection.os, "fstat", growing_fstat)
    with pytest.raises(ContextRequestError) as exc:
        source_selection.read_selection_file(output)
    assert exc.value.refusal_reason == "invalid_selection_record"
    assert output.stat().st_size <= MAX_SELECTION_FILE_BYTES
