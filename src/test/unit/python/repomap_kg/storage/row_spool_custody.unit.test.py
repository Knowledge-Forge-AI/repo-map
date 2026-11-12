"""A producer failure must retain no unowned private row file or handle."""
from __future__ import annotations

from pathlib import Path

import pytest

from common_lore_index.storage.row_spool import RowSpool, RowSpoolWriter


def test_timing_observer_failure_reclaims_the_created_spool(tmp_path: Path) -> None:
    marker = RuntimeError("synthetic timing observer refusal")

    def refuse(_elapsed: int) -> None:
        raise marker

    leftovers: tuple[Path, ...] = ()
    try:
        with pytest.raises(RuntimeError) as caught:
            RowSpool.from_rows(({"value": "public fixture"},), dir=tmp_path, timing_observer=refuse)
        assert caught.value is marker
        leftovers = tuple(tmp_path.iterdir())
    finally:
        for path in leftovers:
            path.unlink()
    assert leftovers == ()


def test_unfinished_writer_context_reclaims_its_private_file(tmp_path: Path) -> None:
    writer = RowSpoolWriter(dir=tmp_path)
    try:
        with writer:
            writer.write_row({"value": "public fixture"})
        left_on_exit = writer.path.exists()
    finally:
        writer.abort()
    assert left_on_exit is False
