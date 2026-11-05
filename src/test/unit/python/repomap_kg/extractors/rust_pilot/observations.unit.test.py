"""Parent-derived names, lines, pointers and raw observations (spec 6.5, 9, 11.2) and frozen golds."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from common_lore_index.extractors.rust_pilot.helper_protocol import decode_frames
from common_lore_index.extractors.rust_pilot.observations import (
    FileObservations,
    LineIndex,
    attribute_class,
    bounded_text,
    build_file_observations,
    decode_name,
)
from common_lore_index.observations.raw import RawObservation
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import frame, frames, item_frame

NONCE = "a" * 64
FIXTURES = Path(__file__).resolve().parents[5] / "fixtures" / "rust_pilot"


def _build(data: bytes, body: list[bytes], **end: int) -> tuple[
        FileObservations, dict[str, list[RawObservation]]]:
    decoded = decode_frames(frames(NONCE, body, **end), nonce=NONCE, input_length=len(data))
    result = build_file_observations("src/lib.rs", data, decoded, input_sha256=hashlib.sha256(data).hexdigest(),
                                     build_script_name=False)
    grouped: dict[str, list[RawObservation]] = {}
    for item in result.observations:
        grouped.setdefault(item.kind, []).append(item)
    return result, grouped


def _span(data: bytes, needle: bytes, nth: int = 1) -> list[int]:
    start = -1
    for _ in range(nth):
        start = data.index(needle, start + 1)
    return [start, start + len(needle)]


def test_names_lines_and_pointers_come_from_parent_bytes() -> None:
    data = b"\xef\xbb\xbf// c\r\npub mod m {\r\n    #[derive(Debug)] fn f() {}\r\n}\r\nstruct r#S;\r\n"
    mod, fn, st = _span(data, b"pub mod m {\r\n    #[derive(Debug)] fn f() {}\r\n}"), _span(
        data, b"fn f() {}"), _span(data, b"struct r#S;")
    name_at = data.index(b"m {")
    _, grouped = _build(data, [item_frame(0, -1, 1, *mod, n=[name_at, name_at + 1], v=_span(data, b"pub")),
                               item_frame(1, 0, 2, *fn, n=_span(data, b"f", 2), a=[_span(data, b"#[derive(Debug)]")]),
                               item_frame(2, -1, 4, *st, n=_span(data, b"r#S"))])
    items = grouped["rust.item"]
    assert [(i.name, i.start_line, i.end_line, i.metadata["pointer"]) for i in items] == [
        ("m", 2, 4, "/mod:m"), ("f", 3, 3, "/mod:m/fn:f"), ("r#S", 5, 5, "/struct:r#S")]
    assert items[0].metadata["visibility"] == "pub" and items[0].metadata["member_list"] == "complete"
    assert items[1].metadata["attributes"] == {"cfg": False, "cfg_attr": False, "derive": True, "other": 0}
    assert items[1].metadata["parent_pointer"] == "/mod:m" and items[1].metadata["has_body"] is True
    assert items[2].metadata["raw_identifier"] is True and items[0].metadata["body"] == "inline"
    parse = grouped["rust.parse"][0]
    assert parse.metadata["line_count"] == 5 and parse.metadata["completeness"] == "complete"
    assert all(i.metadata["language"] == "rust" and i.extractor == "rust-pilot-tree-sitter" for i in items)


def test_same_namespace_siblings_get_ordinals_and_impls_get_positions() -> None:
    data = b"fn a(){} fn a(){} struct T; enum T{} impl T{} impl T{} mod a;"
    body = [item_frame(0, -1, 2, 0, 8, n=[3, 4]), item_frame(1, -1, 2, 9, 17, n=[12, 13]),
            item_frame(2, -1, 4, 18, 27, n=[25, 26]), item_frame(3, -1, 5, 28, 36, n=[33, 34]),
            item_frame(4, -1, 9, 37, 45, y=[42, 43]), item_frame(5, -1, 9, 46, 54, y=[51, 52]),
            item_frame(6, -1, 1, 55, 61, n=[59, 60], f=2)]
    _, grouped = _build(data, body)
    items = grouped["rust.item"]
    assert [i.metadata["pointer"] for i in items] == [
        "/fn:a@1", "/fn:a@2", "/struct:T@1", "/enum:T@2", "/impl:1", "/impl:2", "/mod:a"]
    assert [i.metadata["name_ambiguity"] for i in items] == [2, 2, 2, 2, 0, 0, 0]
    assert items[4].metadata["self_type_text"] == "T" and items[6].metadata["body"] == "external_unresolved"
    assert "member_list" not in items[6].metadata


def test_rejected_names_drop_their_subtree_and_are_counted() -> None:
    data = b"mod 9x { fn f() {} } fn ok() {}"
    _, grouped = _build(data, [item_frame(0, -1, 1, 0, 20, n=[4, 6]), item_frame(1, 0, 2, 9, 18, n=[12, 13]),
                               item_frame(2, -1, 2, 21, 31, n=[24, 26])])
    assert [i.name for i in grouped["rust.item"]] == ["ok"]
    unsupported = grouped["rust.unsupported"][0]
    assert unsupported.metadata == {**unsupported.metadata, "construct": "name_rejected", "count": 2,
                                    "scope_pointer": "/"}
    assert grouped["rust.parse"][0].metadata["unsupported"] == 2


def test_usable_scope_completeness_and_member_lists() -> None:
    data = b"mod a { fn b() {} } mod c { x!(); } fn d() { ) }"
    body = [item_frame(0, -1, 1, 0, 19, n=[4, 5]), item_frame(1, 0, 2, 8, 17, n=[11, 12]),
            item_frame(2, -1, 1, 20, 35, n=[24, 25]), frame("u", p=2, k=1, s=28, e=33),
            item_frame(3, -1, 2, 36, 48, n=[39, 40], f=1)]
    _, grouped = _build(data, body, root_error=1)
    items = {i.name: i.metadata for i in grouped["rust.item"]}
    assert [items[n]["usable_scope"] for n in "abcd"] == [True, True, True, False]
    assert items["c"]["member_list"] == "macro_incomplete"
    parse = grouped["rust.parse"][0].metadata
    assert (parse["outcome"], parse["completeness"], parse["item_list"]) == ("succeeded", "partial", "partial")
    rejected, _ = _build(data, [item_frame(0, -1, 2, 36, 48, n=[39, 40], f=1)], root_error=1)
    assert rejected.outcome == "parse_rejected" and rejected.achieved == ()
    truncated, _ = _build(data, [item_frame(0, -1, 1, 0, 19, n=[4, 5])], truncated=1)
    assert (truncated.completeness, truncated.achieved) == ("truncated", ("syntax.error_tolerant",))
    _, grouped = _build(data, [item_frame(0, -1, 1, 0, 19, n=[4, 5], f=1)], root_error=1)
    error_mod = grouped["rust.item"][0]
    assert error_mod.metadata["member_list"] == "error_incomplete"


@pytest.mark.parametrize(("text", "expected"), [
    (b"#[cfg(unix)]", "cfg"), (b"#[ cfg_attr(a, b)]", "cfg_attr"), (b"#[derive(Debug)]", "derive"),
    (b"#[rustfmt::skip]", "other"), (b"#[cfg::nested]", "other"), (b"#![cfg(x)]", "other"), (b"# [cfg]", "other")])
def test_attribute_prefix_is_lexical_and_never_evaluated(text: bytes, expected: str) -> None:
    assert attribute_class(text, (0, len(text))) == expected


def test_name_and_text_bounds() -> None:
    assert decode_name(b"r#match", (0, 7)) == ("r#match", True)
    assert decode_name("größe".encode(), (0, 7)) == ("größe", False)
    for data in (b"a b", b"#x", b"\xff", b"r#", b""):
        assert decode_name(data, (0, len(data))) is None
    assert decode_name(b"a" * 257, (0, 257)) is None and decode_name(b"x", None) is None
    assert bounded_text(b"pub(  crate\n)", (0, 13), 32) == "pub( crate )"
    assert bounded_text(b"x" * 33, (0, 33), 32) is None
    index = LineIndex(b"a\r\nb\n\nc")
    assert (index.count, index.lines(0, 1), index.lines(3, 5), index.lines(6, 7)) == (4, (1, 1), (2, 2), (4, 4))


def test_frozen_fixtures_and_golds_bind_each_other() -> None:
    golds = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((FIXTURES / "golds").glob("*.json"))]
    assert len(golds) >= 13 and all(g["schema"] == "cloe-rust-pilot-gold-v1" for g in golds)
    for gold in golds:
        data = (FIXTURES / gold["fixture"]).read_bytes()
        assert (len(data), hashlib.sha256(data).hexdigest()) == (gold["input_bytes"], gold["input_sha256"])
        for item in gold["items"]:
            assert 0 <= item["start_byte"] < item["end_byte"] <= len(data)
            if item["name"] is not None:
                assert item["name"].encode() in data[item["start_byte"]:item["end_byte"]]
    parsed = [g for g in golds if g["outcome"] == "succeeded"]
    assert len(parsed) >= 10
    assert sum(len(g["items"]) for g in parsed if g["fixture"] != "stress_depth.rs") >= 150
    long = next(g for g in golds if g["fixture"] == "q02_long_positions.rs")
    last = long["items"][-1]
    line = (FIXTURES / long["fixture"]).read_bytes().split(b"\n")[last["start_line"] - 1]
    assert long["line_count"] > 300 and line.index(last["name"].encode()) > 300
