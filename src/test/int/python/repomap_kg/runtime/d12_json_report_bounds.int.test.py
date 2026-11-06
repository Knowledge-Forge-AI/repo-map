"""Explicit JSON depth contracts retain raw byte provenance across reader bounds."""

from __future__ import annotations

import hashlib
from pathlib import Path
import pytest

from ci.d12_hosted_state import load_safe_json_report


@pytest.mark.parametrize(("shape", "depth", "valid"), [
    ("mapping", 256, True), ("mapping", 257, False),
    ("sequence", 255, True), ("sequence", 256, False),
])
def test_stored_report_depth_bound_retains_provenance_and_file_bytes(
    tmp_path: Path, shape: str, depth: int, valid: bool,
) -> None:
    raw = ((b'{"a":' * depth) + b"{}" + b"}" * depth if shape == "mapping"
           else b'{"a":' + b"[" * depth + b"0" + b"]" * depth + b"}")
    path = tmp_path / "bounded.json"
    path.write_bytes(raw)
    value, provenance, error = load_safe_json_report(path)
    assert (value is not None) is valid
    assert (error is None) is valid
    assert provenance == {
        "status": "valid" if valid else "malformed_json",
        "byte_length": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "redacted": False,
    }
    assert path.read_bytes() == raw
