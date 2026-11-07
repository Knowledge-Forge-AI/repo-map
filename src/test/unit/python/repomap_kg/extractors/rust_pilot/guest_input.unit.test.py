"""Exercise the actual stdlib input decoder without importing either native package."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json

import pytest

from common_lore_index.extractors.rust_pilot.guest.parse_helper import InputRefused, read_input


@pytest.mark.parametrize("version", [True, False, 1.0, "1", None, 2])
def test_non_integer_or_unsupported_versions_are_refused(version: object) -> None:
    data = b"fn sample() {}\n"
    header = {"n": len(data), "nonce": "a" * 64, "sha256": hashlib.sha256(data).hexdigest(), "v": version}
    with pytest.raises(InputRefused):
        read_input(BytesIO(json.dumps(header).encode("ascii") + b"\n" + data))


def test_selected_bytes_and_nonce_survive_exact_input_framing() -> None:
    data = "fn \u03b4() {}\r\n".encode("utf-8")
    header = {"n": len(data), "nonce": "a" * 64, "sha256": hashlib.sha256(data).hexdigest(), "v": 1}
    assert read_input(BytesIO(json.dumps(header).encode("ascii") + b"\n" + data)) == ("a" * 64, data)
