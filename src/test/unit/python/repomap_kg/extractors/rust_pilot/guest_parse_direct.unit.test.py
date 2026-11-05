"""Direct pure-Python ownership of the maintained parse-helper guest source."""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path

import pytest

from common_lore_index.extractors.rust_pilot.guest import parse_helper
from common_lore_index.extractors.rust_pilot.guest.parse_helper import InputRefused
from common_lore_index.extractors.rust_pilot.helper_protocol import ITEM_KINDS
from repomap_test_support.rust_pilot_fake_tree_sitter.tree_sitter import Language, Parser, Tree
from repomap_test_support.rust_pilot_fake_tree_sitter.tree_sitter_rust import language

FIXTURES = Path(__file__).resolve().parents[5] / "fixtures" / "rust_pilot"
NONCE = "a" * 64


def _wire(data: bytes, **changes: object) -> bytes:
    header: dict[str, object] = {
        "n": len(data), "nonce": NONCE, "sha256": hashlib.sha256(data).hexdigest(), "v": 1,
    }
    header.update(changes)
    return json.dumps(header, separators=(",", ":")).encode("ascii") + b"\n" + data


def test_read_input_accepts_exact_utf8_bytes_and_binds_nonce_and_digest() -> None:
    data = "pub fn δ() {}\r\n".encode("utf-8")
    assert parse_helper.read_input(BytesIO(_wire(data))) == (NONCE, data)


@pytest.mark.parametrize(("stream", "code"), [
    (_wire(b"fn f() {}", n=-1), "header_size"),
    (_wire(b"fn f() {}", n=parse_helper.MAX_INPUT + 1), "header_size"),
    (_wire(b"fn f() {}", nonce="A" * 64), "header_digest"),
    (_wire(b"fn f() {}", sha256="0" * 64), "input_digest"),
    (_wire(b"fn f() {}", v=1.0), "number_refused"),
    (_wire(b"fn f() {}") + b"x", "trailing_input"),
    (_wire(b"fn f() {}")[:-1], "short_input"),
    (b"\xff\nfn f() {}", "header_json"),
])
def test_read_input_refuses_strict_framing_and_digest_failures(
        stream: bytes, code: str) -> None:
    with pytest.raises(InputRefused, match=code):
        parse_helper.read_input(BytesIO(stream))


def test_read_input_rejects_duplicate_header_keys_without_reading_payload() -> None:
    data = b"fn f() {}"
    digest = hashlib.sha256(data).hexdigest().encode("ascii")
    stream = (b'{"n":9,"n":9,"nonce":"' + NONCE.encode() + b'","sha256":"' + digest
              + b'","v":1}\n' + data)
    with pytest.raises(InputRefused, match="duplicate_key"):
        parse_helper.read_input(BytesIO(stream))


def test_frames_compact_bytes_and_refuse_frame_or_output_bounds() -> None:
    frames = parse_helper.Frames()
    value = {"t": "n", "value": "δ"}
    assert frames.add(value)
    assert frames.lines == [
        json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    ]
    assert frames.total == len(frames.lines[0]) and not frames.full
    with pytest.raises(RuntimeError, match="frame_too_large"):
        frames.add({"text": "x" * (parse_helper.MAX_FRAME + 32)})
    frames.total = parse_helper.MAX_OUTPUT
    assert frames.add({"t": "n"}) is False and frames.full


def _fake_tree(data: bytes) -> Tree:
    return Parser(Language(language())).parse(data)


def test_span_field_span_and_visibility_use_fake_tree_byte_ranges() -> None:
    data = b"pub mod m { fn f() {} }"
    tree = _fake_tree(data)
    cursor = tree.walk()
    assert cursor.goto_first_child()
    walker = parse_helper.Walk(cursor, parse_helper.Frames())
    module = cursor.node
    assert parse_helper.span(module) == [0, len(data)]
    assert walker.field_span(module, "name") == [8, 9]
    assert walker.visibility() == [0, 3]


def test_direct_walk_matches_source_bound_q01_gold_item_ranges() -> None:
    gold = json.loads((FIXTURES / "golds" / "q01_all_items.gold.json").read_text(encoding="utf-8"))
    data = (FIXTURES / "q01_all_items.rs").read_bytes()
    assert (len(data), hashlib.sha256(data).hexdigest()) == (gold["input_bytes"], gold["input_sha256"])

    frames = parse_helper.Frames()
    parse_helper.Walk(_fake_tree(data).walk(), frames).run()
    records = [json.loads(line) for line in frames.lines]
    items = [record for record in records if record["t"] == "n"]
    actual = [(item["s"], item["e"], ITEM_KINDS[item["k"]]) for item in items]
    expected = [(item["start_byte"], item["end_byte"], item["item_kind"]) for item in gold["items"]]
    assert actual == expected
    assert frames.items == len(gold["items"]) and items[0]["p"] == -1 and items[1]["p"] == 0
    assert any(record["t"] == "u" for record in records)


@pytest.mark.parametrize(("data", "expected_error"), [
    (b"fn normal() { let value = 3 * 4; value }", False),
    (b"fn absent() { let value = 3 * ; value }", True),
    (b"fn commented() { let value = 3 * /* gap */ ; value }", True),
    (b"struct Fine { field: u8, pair: (u8, u8), }", False),
    (b"struct Broken { field: , }", True),
    (b'fn quoted() { let text = "* ;"; }', False),
    (b"fn macro_tokens() { tokens!(* ;); }", False),
])
def test_stand_in_marks_only_modeled_missing_operands_and_field_types(
        data: bytes, expected_error: bool) -> None:
    from repomap_test_support.rust_pilot_fake_tree_sitter.tree_sitter._grammar import parse_source

    root = parse_source(data)
    assert root.has_error is expected_error
    assert any(child.has_error for child in root.children) is expected_error
