"""Literal scope admission must never widen a directory selection."""
from __future__ import annotations

import pytest

from retrieval_evaluation_scope import evaluation_path_prefix, source_path_matches_prefix


@pytest.mark.parametrize(("prefix", "path", "expected"), [
    (None, "anything/file.py", True),
    ("shared", "shared", True),
    ("shared", "shared/a.py", True),
    ("shared", "shared2/a.py", False),
    ("shared/", "shared", False),
    ("shared/", "shared/a.py", True),
    ("shared/", "shared2/a.py", False),
    ("shared/", "SHARED/a.py", False),
    ("shared%_", "shared%_/a.py", True),
    ("shared%_", "sharedXY/a.py", False),
    ("café/", "café/a.py", True),
    ("café/", "cafe\u0301/a.py", False),
    ("Δ/", "δ/a.py", False),
])
def test_source_scope_preserves_literal_directory_meaning(
    prefix: str | None, path: str, expected: bool,
) -> None:
    assert source_path_matches_prefix(path, prefix) is expected


@pytest.mark.parametrize("prefix", [
    "", " shared", "shared ", " shared/", "shared//", "shared/./", "shared/../x",
    "../shared", "/shared", "~shared", "shared\\x", "a:b", "a/*", "a/?", "a/[x]",
    "a\x00b", "a//b",
])
def test_malformed_or_lossy_scope_normalization_refuses(prefix: str) -> None:
    with pytest.raises(ValueError):
        evaluation_path_prefix(prefix)


def test_prefix_record_preserves_raw_and_canonical_meanings() -> None:
    prefix = evaluation_path_prefix("shared/")
    assert prefix is not None
    assert (prefix.raw, prefix.canonical, prefix.descendants_only) == ("shared/", "shared", True)
