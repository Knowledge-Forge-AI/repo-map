"""Unit owners for the additive, bounded Rust graph-key domains."""

from __future__ import annotations

import pytest

from common_lore_index.graph._key_namespaces import _SEGMENT_COUNTS
from common_lore_index.graph.keys import GraphKeyError, file_key, parse_key
from common_lore_index.graph.rust_keys import (
    MAX_POINTER_BYTES,
    MAX_POINTER_STEPS,
    rust_item_key,
    rust_source_file_key,
)


def test_source_and_item_keys_are_separate_domains_and_parseable() -> None:
    source = rust_source_file_key("src/lib.rs")
    assert parse_key(source).namespace == "rust.source_file"
    function = rust_item_key("rust.function", "src/lib.rs", "/fn:run")
    nested = rust_item_key("rust.function", "src/lib.rs", "/mod:api/fn:run")
    assert function != nested and parse_key(function).namespace == "rust.function"
    assert rust_source_file_key(file_key("src/lib.rs")) == source


def test_rust_namespace_catalog_is_additive_and_closed() -> None:
    names = {
        "rust.source_file", "rust.module", "rust.function", "rust.type",
        "rust.trait", "rust.impl", "rust.macro",
    }
    assert names <= set(_SEGMENT_COUNTS)
    assert _SEGMENT_COUNTS["rust.source_file"] == 1
    assert all(
        _SEGMENT_COUNTS[name] == 2 for name in names - {"rust.source_file"}
    )


@pytest.mark.parametrize("namespace", ("rust.source_file", "rust.item", "rust.function.extra"))
def test_unknown_or_non_item_namespace_is_refused(namespace: str) -> None:
    with pytest.raises(GraphKeyError):
        rust_item_key(namespace, "src/lib.rs", "/fn:run")


def test_pointer_limits_and_ambiguity_suffixes_are_closed() -> None:
    first = rust_item_key("rust.impl", "src/lib.rs", "/impl:1")
    second = rust_item_key("rust.impl", "src/lib.rs", "/impl:2")
    assert first != second
    with pytest.raises(GraphKeyError):
        rust_item_key("rust.function", "src/lib.rs", "/" + "fn:" + "x" * MAX_POINTER_BYTES)
    deep = "/" + "/".join(f"fn:f{index}" for index in range(MAX_POINTER_STEPS + 1))
    with pytest.raises(GraphKeyError):
        rust_item_key("rust.function", "src/lib.rs", deep)


def test_key_byte_bound_is_independent_of_file_path_acceptance() -> None:
    with pytest.raises(GraphKeyError, match="byte bound"):
        rust_source_file_key("a" * 33_000 + ".rs")
