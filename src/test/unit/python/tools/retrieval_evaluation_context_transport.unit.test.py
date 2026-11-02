"""Terminal attempt transport preserves bytes and refuses corrupted frames."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from retrieval_evaluation_context_transport import (
    ATTEMPT_ARCHIVE_PREFIX, decode_context_attempt_archive, emit_context_attempt_archive,
)


def test_terminal_attempt_transport_round_trips_exact_binary_and_json_bytes(tmp_path: Path) -> None:
    expected = {
        "declaration.json": b'{"attempt_id":"controlled-attempt"}\n',
        "source-manifest.json": b'{"sources":[]}\n',
        "sources.zip": b"\x00controlled-source-archive\xff",
        "observations.jsonl": b'{"status":"completed"}\n',
        "terminal.json": b'{"status":"completed"}\n',
        "report.json": b'{"observation_count":1}\n',
    }
    for name, raw in expected.items():
        (tmp_path / name).write_bytes(raw)
    out = io.StringIO()
    emit_context_attempt_archive(tmp_path, stream=out)
    line = out.getvalue()
    assert len(line.splitlines()) == 1
    assert decode_context_attempt_archive(line) == expected
    record = json.loads(line.removeprefix(ATTEMPT_ARCHIVE_PREFIX))
    record["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        decode_context_attempt_archive(ATTEMPT_ARCHIVE_PREFIX + json.dumps(record))
    with pytest.raises(ValueError):
        decode_context_attempt_archive(line[:-12])


def test_attempt_transport_rejects_symlink_instead_of_reading_target(tmp_path: Path) -> None:
    target = tmp_path / "controlled-target"
    target.write_text("not attempt evidence")
    (tmp_path / "declaration.json").symlink_to(target)
    with pytest.raises(OSError):
        emit_context_attempt_archive(tmp_path, stream=io.StringIO())
