"""Parent side of the bounded helper byte protocol (spec 6.1, 6.3, 6.4).

The parent writes one header line and exactly ``n`` input bytes. The helper
answers with integer-only frames. Decoding here is strict: exact key sets,
exact ``int`` values, one ``hello`` first and one ``end`` last, both bound to
the per-invocation nonce, no byte after ``end`` and every range rechecked
against the input length and the item nesting rules. Any violation raises
:class:`ProtocolViolation`; the file is then a ``crashed`` defect, never
retried. Helper metadata such as ``hello`` is informational only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from common_lore_index.extractors.contracts.vocabulary import ContractError

PROTOCOL_VERSION = 1
MAX_INPUT = 1_048_576
MAX_HEADER_LINE = 256
MAX_FRAME = 512
MAX_FRAMES = 50_000
MAX_OUTPUT = 4 * 1_048_576
MAX_ATTRIBUTES = 16
MAX_SCOPE_DEPTH = 256
INT_RANGE = (-1, 2**31)
ITEM_KINDS = {1: "mod", 2: "fn", 3: "fn", 4: "struct", 5: "enum", 6: "union", 7: "type",
              8: "trait", 9: "impl", 10: "macro"}
CONTAINER_TAGS = frozenset({1, 8, 9})
UNSUPPORTED_CONSTRUCTS = {1: "macro_invocation", 2: "const_item", 3: "static_item",
                          4: "use_declaration", 5: "extern_crate_declaration", 6: "foreign_item",
                          7: "inner_attribute", 8: "error_region", 9: "other_item"}
FLAG_HAS_ERROR = 1
FLAG_NO_BODY = 2
FLAG_SIGNATURE = 4
_HEX64 = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"[0-9A-Za-z.+-]{1,32}")
_KEYS = {
    "hello": frozenset({"t", "v", "nonce", "ts", "abi"}),
    "n": frozenset({"t", "i", "p", "k", "s", "e", "n", "a", "v", "y", "r", "f"}),
    "u": frozenset({"t", "p", "k", "s", "e"}),
    "end": frozenset({"t", "nonce", "root_error", "errors", "missing", "items", "unsupported", "truncated"}),
}

Span = tuple[int, int]


class ProtocolViolation(ContractError):
    """Strict-protocol refusal; the message is the closed code only."""


@dataclass(frozen=True)
class ItemFrame:
    index: int
    parent: int
    tag: int
    start: int
    end: int
    name: Span | None
    attributes: tuple[Span, ...]
    visibility: Span | None
    self_type: Span | None
    trait_ref: Span | None
    flags: int


@dataclass(frozen=True)
class UnsupportedFrame:
    scope: int
    tag: int
    start: int
    end: int


@dataclass(frozen=True)
class EndFrame:
    root_error: int
    errors: int
    missing: int
    items: int
    unsupported: int
    truncated: int


@dataclass(frozen=True)
class DecodedParse:
    items: tuple[ItemFrame, ...]
    unsupported: tuple[UnsupportedFrame, ...]
    end: EndFrame
    helper_version: str
    helper_abi: int


def invocation_nonce(run_nonce: bytes, seq: int, input_sha256: str) -> str:
    """Per-file nonce: SHA-256 over the run nonce, the sequence and the input digest."""

    if type(run_nonce) is not bytes or len(run_nonce) != 32 or type(seq) is not int or seq < 0:
        raise ProtocolViolation("invalid_nonce_material")
    if _HEX64.fullmatch(input_sha256) is None:
        raise ProtocolViolation("invalid_nonce_material")
    material = b"rust-pilot-invocation-v1\x00" + run_nonce + seq.to_bytes(8, "big") + bytes.fromhex(input_sha256)
    return hashlib.sha256(material).hexdigest()


def encode_request(data: bytes, nonce: str) -> bytes:
    """Header line followed by exactly the input bytes."""

    if type(data) is not bytes or len(data) > MAX_INPUT or _HEX64.fullmatch(nonce) is None:
        raise ProtocolViolation("invalid_request")
    header = json.dumps({"n": len(data), "nonce": nonce, "sha256": hashlib.sha256(data).hexdigest(),
                         "v": PROTOCOL_VERSION}, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(header) + 1 > MAX_HEADER_LINE:
        raise ProtocolViolation("invalid_request")
    return header + b"\n" + data


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolViolation("duplicate_key")
        result[key] = value
    return result


def _reject(_value: str) -> Any:
    raise ProtocolViolation("non_integer_number")


def _bounded_int(value: str) -> int:
    if len(value) > 11:
        raise ProtocolViolation("integer_out_of_range")
    return int(value)


def _frame(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_FRAME:
        raise ProtocolViolation("frame_too_large")
    try:
        value = json.loads(line.decode("ascii"), object_pairs_hook=_unique, parse_float=_reject,
                           parse_constant=_reject, parse_int=_bounded_int)
    except ProtocolViolation:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ProtocolViolation("invalid_frame") from None
    if type(value) is not dict or type(value.get("t")) is not str or value["t"] not in _KEYS:
        raise ProtocolViolation("unknown_frame")
    if set(value) != _KEYS[value["t"]]:
        raise ProtocolViolation("frame_keys")
    return value


def _int(value: object, low: int = INT_RANGE[0], high: int = INT_RANGE[1]) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ProtocolViolation("integer_field")
    return value


def _span(value: object, length: int) -> Span:
    if type(value) is not list or len(value) != 2:
        raise ProtocolViolation("range_shape")
    start, end = _int(value[0], 0), _int(value[1], 0)
    if not start <= end <= length:
        raise ProtocolViolation("range_bounds")
    return start, end


def _optional_span(value: object, length: int) -> Span | None:
    return None if value is None else _span(value, length)


def _inside(inner: Span | None, outer: Span) -> bool:
    return inner is None or (outer[0] <= inner[0] and inner[1] <= outer[1])


def _item(value: dict[str, Any], index: int, items: list[ItemFrame], last_end: dict[int, int],
          length: int) -> ItemFrame:
    if _int(value["i"]) != index:
        raise ProtocolViolation("item_index")
    parent, tag, flags = _int(value["p"], -1, index - 1), _int(value["k"], 1, 10), _int(value["f"], 0, 7)
    start, end = _span([value["s"], value["e"]], length)
    attributes = value["a"]
    if type(attributes) is not list or len(attributes) > MAX_ATTRIBUTES:
        raise ProtocolViolation("attribute_shape")
    item = ItemFrame(index, parent, tag, start, end, _optional_span(value["n"], length),
                     tuple(_span(pair, length) for pair in attributes),
                     _optional_span(value["v"], length), _optional_span(value["y"], length),
                     _optional_span(value["r"], length), flags)
    if (bool(flags & FLAG_NO_BODY) and tag != 1) or bool(flags & FLAG_SIGNATURE) != (tag == 3):
        raise ProtocolViolation("item_flags")
    if (tag == 9 and item.name is not None) or (tag != 9 and (item.self_type or item.trait_ref)):
        raise ProtocolViolation("item_fields")
    scope = (0, length)
    if parent >= 0:
        owner = items[parent]
        if owner.tag not in CONTAINER_TAGS or owner.flags & FLAG_NO_BODY:
            raise ProtocolViolation("parent_not_container")
        scope = (owner.start, owner.end)
    own = (start, end)
    if not _inside(own, scope) or not all(_inside(part, own) for part in
                                          (item.name, item.visibility, item.self_type, item.trait_ref)):
        raise ProtocolViolation("range_nesting")
    cursor = last_end.get(parent, scope[0])
    if start < cursor:
        raise ProtocolViolation("sibling_order")
    for attribute in item.attributes:
        if attribute[0] < cursor or attribute[1] > start or attribute[0] == attribute[1]:
            raise ProtocolViolation("attribute_order")
        cursor = attribute[1]
    last_end[parent] = end
    return item


def _unsupported(value: dict[str, Any], items: list[ItemFrame], length: int) -> UnsupportedFrame:
    scope_index = _int(value["p"], -1, len(items) - 1)
    frame = UnsupportedFrame(scope_index, _int(value["k"], 1, 9), *_span([value["s"], value["e"]], length))
    if scope_index >= 0 and (items[scope_index].tag not in CONTAINER_TAGS
                             or items[scope_index].flags & FLAG_NO_BODY):
        raise ProtocolViolation("parent_not_container")
    scope = (0, length) if scope_index < 0 else (items[scope_index].start, items[scope_index].end)
    if not _inside((frame.start, frame.end), scope):
        raise ProtocolViolation("range_nesting")
    return frame


def _end(value: dict[str, Any], nonce: str, items: int, unsupported: list[UnsupportedFrame],
         item_frames: list[ItemFrame]) -> EndFrame:
    if value["nonce"] != nonce:
        raise ProtocolViolation("nonce_mismatch")
    end = EndFrame(_int(value["root_error"], 0, 1), _int(value["errors"], 0), _int(value["missing"], 0),
                   _int(value["items"], 0), _int(value["unsupported"], 0), _int(value["truncated"], 0, 1))
    error_regions = sum(1 for frame in unsupported if frame.tag == 8)
    if end.items != items or end.unsupported != len(unsupported):
        raise ProtocolViolation("end_counts")
    if end.errors < error_regions or (not end.truncated and end.errors != error_regions):
        raise ProtocolViolation("end_counts")
    if not end.root_error and (end.errors or end.missing or any(i.flags & FLAG_HAS_ERROR for i in item_frames)):
        raise ProtocolViolation("error_consistency")
    return end


def decode_frames(stdout: bytes, *, nonce: str, input_length: int) -> DecodedParse:
    """Decode the complete helper stdout or raise :class:`ProtocolViolation`."""

    if type(stdout) is not bytes or len(stdout) > MAX_OUTPUT or not stdout.endswith(b"\n"):
        raise ProtocolViolation("output_shape")
    if _HEX64.fullmatch(nonce) is None or not 0 <= input_length <= MAX_INPUT:
        raise ProtocolViolation("invalid_request")
    lines = stdout[:-1].split(b"\n")
    if len(lines) < 2 or len(lines) > MAX_FRAMES:
        raise ProtocolViolation("frame_count")
    hello = _frame(lines[0])
    if hello["t"] != "hello" or _int(hello["v"]) != PROTOCOL_VERSION or hello["nonce"] != nonce:
        raise ProtocolViolation("hello_invalid")
    if type(hello["ts"]) is not str or _VERSION.fullmatch(hello["ts"]) is None:
        raise ProtocolViolation("hello_invalid")
    abi = _int(hello["abi"], 0)
    items: list[ItemFrame] = []
    unsupported: list[UnsupportedFrame] = []
    last_end: dict[int, int] = {}
    depths: list[int] = []
    for line in lines[1:-1]:
        value = _frame(line)
        if value["t"] == "n":
            item = _item(value, len(items), items, last_end, input_length)
            depth = 1 if item.parent < 0 else depths[item.parent] + 1
            if depth > MAX_SCOPE_DEPTH:
                raise ProtocolViolation("scope_depth")
            depths.append(depth)
            items.append(item)
        elif value["t"] == "u":
            unsupported.append(_unsupported(value, items, input_length))
        else:
            raise ProtocolViolation("frame_order")
    last = _frame(lines[-1])
    if last["t"] != "end":
        raise ProtocolViolation("frame_order")
    end = _end(last, nonce, len(items), unsupported, items)
    return DecodedParse(tuple(items), tuple(unsupported), end, hello["ts"], abi)
