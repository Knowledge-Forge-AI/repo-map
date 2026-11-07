"""Strict helper frame decoding and request framing (spec 6.1, 6.3, 6.4; Q08)."""

from __future__ import annotations

import hashlib
import json

import pytest

from common_lore_index.extractors.rust_pilot.helper_protocol import (
    ProtocolViolation,
    decode_frames,
    encode_request,
    invocation_nonce,
)
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import frame, frames, item_frame

DATA = b"mod m { #[a] fn f() {} }\nstruct S;\n"
NONCE = invocation_nonce(b"\x01" * 32, 3, hashlib.sha256(DATA).hexdigest())
MOD = item_frame(0, -1, 1, 0, 24, n=[4, 5])
FN = item_frame(1, 0, 2, 13, 22, n=[16, 17], a=[[8, 12]])
STRUCT = item_frame(2, -1, 4, 25, 34, n=[32, 33])


def _decode(stdout: bytes) -> object:
    return decode_frames(stdout, nonce=NONCE, input_length=len(DATA))


def _violation(stdout: bytes) -> str:
    with pytest.raises(ProtocolViolation) as raised:
        _decode(stdout)
    return raised.value.code


def test_valid_frames_decode_to_integer_only_records() -> None:
    decoded = decode_frames(frames(NONCE, [MOD, FN, STRUCT, frame("u", p=0, k=4, s=6, e=7)]), nonce=NONCE,
                            input_length=len(DATA))
    assert [(item.index, item.parent, item.tag, item.start, item.end) for item in decoded.items] == [
        (0, -1, 1, 0, 24), (1, 0, 2, 13, 22), (2, -1, 4, 25, 34)]
    assert decoded.items[1].attributes == ((8, 12),) and decoded.unsupported[0].scope == 0
    assert (decoded.helper_version, decoded.helper_abi, decoded.end.items) == ("0.26.0", 15, 3)


@pytest.mark.parametrize(("body", "code"), [
    ([item_frame(0, -1, 1, 0, 99)], "range_bounds"),
    ([MOD, item_frame(1, 0, 2, 26, 30, n=[27, 28])], "range_nesting"),
    ([MOD, item_frame(1, 0, 2, 13, 22, n=[2, 3])], "range_nesting"),
    ([STRUCT.replace(b'"i":2', b'"i":0'), item_frame(1, 0, 2, 26, 30)], "parent_not_container"),
    ([item_frame(0, -1, 1, 0, 24, n=[4, 5], f=2), item_frame(1, 0, 2, 13, 22)], "parent_not_container"),
    ([MOD, FN, item_frame(2, -1, 4, 25, 34, n=[32, 33], a=[[20, 21]])], "attribute_order"),
    ([MOD, item_frame(1, 0, 2, 13, 22, a=[[16, 17]])], "attribute_order"),
    ([MOD, item_frame(1, 0, 2, 13, 22, a=[[10, 12], [8, 11]])], "attribute_order"),
    ([STRUCT.replace(b'"i":2', b'"i":0'), item_frame(1, -1, 4, 0, 10)], "sibling_order"),
    ([item_frame(0, -1, 9, 0, 24, n=[4, 5])], "item_fields"),
    ([item_frame(0, -1, 4, 25, 34, y=[25, 26])], "item_fields"),
    ([item_frame(0, -1, 4, 25, 34, f=2)], "item_flags"),
    ([item_frame(0, -1, 3, 25, 34)], "item_flags"),
    ([item_frame(1, -1, 4, 25, 34)], "item_index"),
    ([item_frame(0, -1, 11, 25, 34)], "integer_field"),
    ([frame("u", p=5, k=1, s=0, e=1)], "integer_field"),
    ([MOD, frame("u", p=0, k=1, s=25, e=26)], "range_nesting"),
])
def test_range_nesting_and_field_violations_refuse_the_file(body: list[bytes], code: str) -> None:
    assert _violation(frames(NONCE, body)) == code


def test_nonce_hello_and_end_framing_are_exact() -> None:
    good = frames(NONCE, [STRUCT.replace(b'"i":2', b'"i":0')])
    assert _violation(good.replace(NONCE.encode(), b"f" * 64, 1)) == "hello_invalid"
    assert _violation(good.replace(NONCE.encode(), b"e" * 64)) == "hello_invalid"
    tail = good.rsplit(b'{"t":"end"', 1)
    assert _violation(tail[0] + b'{"t":"end"' + tail[1].replace(NONCE.encode(), b"e" * 64)) == "nonce_mismatch"
    assert _violation(good + b"\n") == "frame_order"
    assert _violation(good + good) == "frame_order"
    assert _violation(good[:-1]) == "output_shape"
    assert _violation(good.split(b"\n", 1)[1]) == "hello_invalid"
    assert _violation(b"".join(good.splitlines(keepends=True)[:-1])) == "frame_order"
    assert _violation(frame("hello", v=1, nonce=NONCE, ts="0.26.0", abi=15)) == "frame_count"


def test_json_shape_violations_are_refused_without_echoing_content() -> None:
    base = frames(NONCE, [])
    lines = base.splitlines(keepends=True)
    cases = {
        "duplicate_key": b'{"t":"u","p":-1,"p":-1,"k":1,"s":0,"e":1}\n',
        "frame_keys": b'{"t":"u","p":-1,"k":1,"s":0,"e":1,"x":0}\n',
        "non_integer_number": b'{"t":"u","p":-1,"k":1,"s":0.0,"e":1}\n',
        "integer_field": b'{"t":"u","p":-1,"k":true,"s":0,"e":1}\n',
        "integer_out_of_range": b'{"t":"u","p":-1,"k":1,"s":0,"e":100000000000}\n',
        "unknown_frame": b'{"t":"name","p":-1}\n',
        "frame_too_large": b'{"t":"u","p":-1,"k":1,"s":0,"e":1,"pad":"' + b"x" * 520 + b'"}\n',
        "invalid_frame": b'{"t":"u","p":-1,"k":1,"s":0,"e":1,"n":"\xc3\xa9"}\n',
    }
    for code, line in cases.items():
        assert _violation(lines[0] + line + lines[1]) == code, code


def test_end_counts_and_error_consistency_are_rechecked() -> None:
    assert _violation(frames(NONCE, [STRUCT.replace(b'"i":2', b'"i":0')]).replace(b'"items":1', b'"items":2')) == "end_counts"
    assert _violation(frames(NONCE, [frame("u", p=-1, k=8, s=0, e=3)], errors=0, root_error=1)) == "end_counts"
    assert _violation(frames(NONCE, [item_frame(0, -1, 4, 25, 34, f=1)])) == "error_consistency"
    assert _violation(frames(NONCE, [], missing=1)) == "error_consistency"
    ok = decode_frames(frames(NONCE, [frame("u", p=-1, k=8, s=0, e=3)], errors=2, root_error=1, truncated=1),
                       nonce=NONCE, input_length=len(DATA))
    assert ok.end.truncated == 1 and ok.end.errors == 2


def test_request_header_is_bounded_ascii_and_bound_to_the_bytes() -> None:
    request = encode_request(DATA, NONCE)
    header, body = request.split(b"\n", 1)
    assert body == DATA and len(header) < 256
    assert json.loads(header) == {"n": len(DATA), "nonce": NONCE, "sha256": hashlib.sha256(DATA).hexdigest(), "v": 1}
    for data, nonce in ((b"x" * 1_048_577, NONCE), (DATA, "A" * 64), (DATA, NONCE[:-1])):
        with pytest.raises(ProtocolViolation, match="invalid_request"):
            encode_request(data, nonce)


def test_invocation_nonce_binds_run_sequence_and_input() -> None:
    digest = hashlib.sha256(DATA).hexdigest()
    base = invocation_nonce(b"\x01" * 32, 3, digest)
    assert base == NONCE and len(base) == 64
    assert len({base, invocation_nonce(b"\x02" * 32, 3, digest), invocation_nonce(b"\x01" * 32, 4, digest),
                invocation_nonce(b"\x01" * 32, 3, "0" * 64)}) == 4
    for args in ((b"\x01" * 31, 3, digest), (b"\x01" * 32, -1, digest), (b"\x01" * 32, 3, "xyz")):
        with pytest.raises(ProtocolViolation):
            invocation_nonce(*args)
