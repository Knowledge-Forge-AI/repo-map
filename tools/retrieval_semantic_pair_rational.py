"""Preserve stored exact-rational fusion contributions without recomputation."""

from __future__ import annotations

from collections.abc import Mapping

from retrieval_semantic_pair_artifacts import refuse


MAX_RATIONAL_DEPTH = 256
MAX_RATIONAL_NODES = 100_000


def rational_records(value: object, path: str = "") -> list[dict[str, object]]:
    """Extract only recorded numerator/denominator pairs from an observation."""

    records: list[dict[str, object]] = []
    pending: list[tuple[object, str, int]] = [(value, path, 0)]
    visited = 0
    while pending:
        current, current_path, depth = pending.pop()
        visited += 1
        if visited > MAX_RATIONAL_NODES:
            raise refuse("pair_rational_traversal")
        if depth > MAX_RATIONAL_DEPTH:
            raise refuse("pair_rational_depth")
        if isinstance(current, Mapping):
            for kind, numerator_name, denominator_name in (
                ("score", "score_numerator", "score_denominator"),
                ("rrf", "rrf_numerator", "rrf_denominator"),
            ):
                if numerator_name in current or denominator_name in current:
                    numerator = current.get(numerator_name)
                    denominator = current.get(denominator_name)
                    if (
                        type(numerator) is not int
                        or type(denominator) is not int
                        or numerator < 0
                        or denominator < 1
                    ):
                        raise refuse("pair_rational_measurement")
                    compact: dict[str, object] = {
                        "kind": kind,
                        "numerator": numerator,
                        "denominator": denominator,
                        "path": current_path,
                    }
                    for field in ("arm_id", "fused_rank", "ordinal_rank"):
                        if field in current:
                            compact[field] = current[field]
                    file_identity = current.get("file_identity")
                    if isinstance(file_identity, Mapping):
                        compact["file_identity"] = {
                            key: file_identity[key]
                            for key in ("binding_id", "snapshot_id", "source_relative_path")
                            if key in file_identity
                        }
                    records.append(compact)
            keys = sorted(current, key=str)
            for key in reversed(keys):
                next_path = f"{current_path}.{key}" if current_path else str(key)
                pending.append((current[key], next_path, depth + 1))
        elif type(current) is list:
            for index in range(len(current) - 1, -1, -1):
                pending.append((current[index], f"{current_path}[{index}]", depth + 1))
    return records


__all__ = ["rational_records"]
