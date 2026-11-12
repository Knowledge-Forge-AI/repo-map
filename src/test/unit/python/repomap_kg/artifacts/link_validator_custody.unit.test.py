"""A failed private link index setup reclaims its acquired resources."""
from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from common_lore_index.artifacts._bundle_stream_links import DiskFamilyLinkValidator


@pytest.mark.parametrize("failure", ["connect", "setup"])
def test_partial_link_index_initialization_reclaims_connection_and_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    original_connect = sqlite3.connect
    marker = RuntimeError("synthetic link-index refusal")
    connections: list[sqlite3.Connection] = []

    class Connection:
        def execute(self, *_args, **_kwargs):
            raise marker

        def close(self):
            connections[0].close()

    def connect(*args, **kwargs):
        if failure == "connect":
            raise marker
        connections.append(original_connect(*args, **kwargs))
        return Connection()

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(RuntimeError) as caught:
        DiskFamilyLinkValidator(spool_dir=tmp_path)
    assert caught.value is marker
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
    assert not tuple(tmp_path.iterdir())
