"""Bounded keys for the witnessed Rust syntax family (graph key version 1)."""

from __future__ import annotations

from common_lore_index.graph.keys import GraphKeyError, _coerce_file_key, _key

RUST_ITEM_NAMESPACES = frozenset({
    "rust.module", "rust.function", "rust.type", "rust.trait", "rust.impl", "rust.macro",
})
RUST_NAMESPACES = RUST_ITEM_NAMESPACES | {"rust.source_file"}
_POINTER_TAGS = frozenset({"mod", "fn", "struct", "enum", "union", "type", "trait", "impl", "macro"})
MAX_POINTER_BYTES = 4096
MAX_POINTER_STEPS = 256
MAX_RUST_KEY_BYTES = 32_768


def _key_bounded(namespace: str, *segments: str) -> str:
    try:
        key = _key(namespace, *segments)
        if len(key.encode("utf-8")) > MAX_RUST_KEY_BYTES:
            raise GraphKeyError("Rust key exceeds its byte bound")
        return key
    except UnicodeEncodeError as error:
        raise GraphKeyError("Rust key contains invalid Unicode") from error


def _pointer(pointer: str) -> str:
    if type(pointer) is not str or not pointer.startswith("/") or pointer.endswith("/"):
        raise GraphKeyError("invalid Rust syntax pointer")
    try:
        size = len(pointer.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise GraphKeyError("invalid Rust syntax pointer") from error
    if size > MAX_POINTER_BYTES:
        raise GraphKeyError("Rust syntax pointer exceeds its byte bound")
    steps = pointer[1:].split("/")
    if not steps or len(steps) > MAX_POINTER_STEPS:
        raise GraphKeyError("Rust syntax pointer depth exceeds its bound")
    for step in steps:
        if not step or any(ord(c) < 0x20 or ord(c) == 0x7F for c in step):
            raise GraphKeyError("invalid Rust syntax pointer")
        tag, separator, value = step.partition(":")
        if not separator or tag not in _POINTER_TAGS or not value:
            raise GraphKeyError("invalid Rust syntax pointer")
        if tag == "impl" and (not value.isascii() or not value.isdigit() or int(value) < 1):
            raise GraphKeyError("invalid Rust impl pointer")
        if tag != "impl" and "@" in value:
            base, suffix = value.rsplit("@", 1)
            if not base or not suffix.isascii() or not suffix.isdigit() or int(suffix) < 1:
                raise GraphKeyError("invalid Rust pointer ambiguity suffix")
    return pointer


def rust_source_file_key(path_or_file_key: str) -> str:
    return _key_bounded("rust.source_file", _coerce_file_key(path_or_file_key))


def rust_item_key(namespace: str, path_or_file_key: str, pointer: str) -> str:
    if namespace not in RUST_ITEM_NAMESPACES:
        raise GraphKeyError("unsupported Rust item namespace")
    return _key_bounded(namespace, _coerce_file_key(path_or_file_key), _pointer(pointer))
