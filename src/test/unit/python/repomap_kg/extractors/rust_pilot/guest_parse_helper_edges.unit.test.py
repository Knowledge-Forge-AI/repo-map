"""Focused ownership of guest parser framing, unsupported nodes and bounds."""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path

import pytest

from common_lore_index.extractors.rust_pilot.guest import parse_helper
from common_lore_index.extractors.rust_pilot.guest.parse_helper import InputRefused
from repomap_test_support.rust_pilot_fake_tree_sitter.tree_sitter import Language, Parser, Tree
from repomap_test_support.rust_pilot_fake_tree_sitter.tree_sitter_rust import language

FIXTURES = Path(__file__).resolve().parents[5] / "fixtures" / "rust_pilot"
NONCE = "a" * 64


def _wire(data: bytes, **changes: object) -> bytes:
    header: dict[str, object] = {
        "n": len(data),
        "nonce": NONCE,
        "sha256": hashlib.sha256(data).hexdigest(),
        "v": 1,
    }
    header.update(changes)
    return json.dumps(header, separators=(",", ":")).encode("ascii") + b"\n" + data


def _fake_tree(data: bytes) -> Tree:
    return Parser(Language(language())).parse(data)


def _walk(fixture: str) -> tuple[parse_helper.Walk, parse_helper.Frames, list[dict[str, object]]]:
    data = (FIXTURES / fixture).read_bytes()
    frames = parse_helper.Frames()
    walker = parse_helper.Walk(_fake_tree(data).walk(), frames)
    walker.run()
    records = [json.loads(line) for line in frames.lines]
    return walker, frames, records


@pytest.mark.parametrize(
    ("stream", "code"),
    [
        (b"{}", "header_line"),
        (_wire(b"fn f() {}", extra=True), "header_keys"),
        (_wire(b"fn f() {}", v=2), "header_keys"),
        (_wire(b"fn f() {}", n="9"), "header_size"),
        (_wire(b"fn f() {}", nonce=None), "header_digest"),
        (_wire(b"fn f() {}", sha256=None), "header_digest"),
        (_wire(b"fn f() {}", sha256="0" * 63), "header_digest"),
    ],
)
def test_read_input_refuses_header_shape_before_parser_use(
    stream: bytes, code: str,
) -> None:
    with pytest.raises(InputRefused, match=code):
        parse_helper.read_input(BytesIO(stream))


def test_frames_refuse_when_the_frame_count_bound_is_exhausted() -> None:
    frames = parse_helper.Frames()
    frames.lines = [b"{}\n"] * (parse_helper.MAX_FRAMES - 1)
    assert frames.add({"t": "n"}) is False
    assert frames.full
    assert len(frames.lines) == parse_helper.MAX_FRAMES - 1


def test_unsupported_forms_emit_tags_and_keep_signature_items_bounded() -> None:
    walker, frames, records = _walk("unsupported_forms.rs")
    items = [record for record in records if record["t"] == "n"]
    unsupported = [record for record in records if record["t"] == "u"]

    assert walker.errors == 0
    assert frames.unsupported == len(unsupported)
    assert any(item["k"] == parse_helper.ITEM_TAGS["function_signature_item"] for item in items)
    assert {record["k"] for record in unsupported} >= {
        parse_helper.UNSUPPORTED_TAGS["use_declaration"],
        parse_helper.UNSUPPORTED_TAGS["const_item"],
        parse_helper.UNSUPPORTED_TAGS["static_item"],
        6,  # foreign-item refusal
        7,  # inner-attribute refusal
        9,  # closed unknown/associated-item refusal
    }


def test_attribute_and_pending_scope_limits_are_observable() -> None:
    walker, _frames, records = _walk("stress_attributes.rs")
    items = [record for record in records if record["t"] == "n"]
    unsupported = [record for record in records if record["t"] == "u"]
    record_item = next(item for item in items if item["k"] == parse_helper.ITEM_TAGS["struct_item"])

    assert walker.truncated == 1
    attributes = record_item["a"]
    assert isinstance(attributes, list) and len(attributes) == parse_helper.MAX_ATTRIBUTES
    assert any(item["p"] == -1 and item["k"] == 9 for item in unsupported)


def test_explicit_error_and_missing_nodes_produce_only_bounded_diagnostics() -> None:
    from repomap_test_support.rust_pilot_fake_tree_sitter.tree_sitter._grammar import Node

    root = Node("source_file", 0, 2, children=[
        Node("ERROR", 0, 1, error=True),
        Node("}", 1, 1, named=False, missing=True),
    ])
    frames = parse_helper.Frames()
    walker = parse_helper.Walk(Tree(root).walk(), frames)
    walker.run()
    records = [json.loads(line) for line in frames.lines]
    assert walker.errors == walker.missing == 1
    assert records == [{"t": "u", "p": -1, "k": 8, "s": 0, "e": 1}]


def test_depth_and_full_output_bounds_stop_walks_explicitly() -> None:
    deep_walker, deep_frames, _records = _walk("stress_depth.rs")
    assert deep_walker.truncated == 1
    assert not deep_frames.full

    frames = parse_helper.Frames()
    frames.full = True
    walker = parse_helper.Walk(_fake_tree(b"fn f() {}").walk(), frames)
    walker.run()
    assert walker.truncated == 1


def test_empty_tree_returns_without_inventing_a_frame() -> None:
    frames = parse_helper.Frames()
    walker = parse_helper.Walk(_fake_tree(b"").walk(), frames)
    walker.run()

    assert walker.visits == 0
    assert frames.lines == []
