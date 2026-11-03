"""Shared proposal fixtures for publication and projection validation cases."""

from __future__ import annotations

import hashlib
from pathlib import Path

from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy
from common_lore_index.retrieval.publication_binding import (
    ProjectionInputs,
)
from repomap_test_support.retrieval_evaluation_query_fixture import (
    build_fixture_projection,
)


def build_validation_projection(
    *,
    spool_dir: Path,
) -> tuple[ProjectionInputs, BodyProjectionPolicy]:
    """Reuse the maintained query fixture and its validated public policy."""
    return build_fixture_projection(spool_dir=spool_dir)


def publication_tree(path: Path) -> tuple[tuple[str, int, str], ...]:
    """Capture exact run-owned files for validation-failure cleanup assertions."""
    if not path.exists():
        return ()
    result: list[tuple[str, int, str]] = []
    for item in sorted(path.rglob("*")):
        if item.is_file():
            data = item.read_bytes()
            result.append(
                (
                    item.relative_to(path).as_posix(),
                    len(data),
                    hashlib.sha256(data).hexdigest(),
                )
            )
    return tuple(result)


__all__ = ["build_validation_projection", "publication_tree"]
