"""Strict publication and snapshot-vector identity parsing for context reads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any


SnapshotVector = tuple[tuple[str, int, str], ...]


class ContextIdentityError(ValueError):
    """Raised when accepted-publication identity is absent or malformed."""


def _invalid(field: str, detail: str = "invalid value") -> ContextIdentityError:
    return ContextIdentityError(f"{field}: {detail}")


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise _invalid(field, "must be int >= 1")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(field, "must be a non-empty string")
    return value


def _required_alias(
    value: Mapping[str, Any], primary: str, alias: str, validator: Any
) -> Any:
    has_primary = primary in value
    has_alias = alias in value
    if not has_primary and not has_alias:
        raise _invalid(primary, "is required")
    first = validator(value[primary], primary) if has_primary else None
    second = validator(value[alias], alias) if has_alias else None
    if has_primary and has_alias and first != second:
        raise _invalid(primary, f"disagrees with {alias}")
    return first if has_primary else second


def _optional_alias(
    value: Mapping[str, Any], primary: str, alias: str, validator: Any
) -> Any | None:
    has_primary = primary in value
    has_alias = alias in value
    if not has_primary and not has_alias:
        return None

    def checked(key: str) -> Any | None:
        raw = value[key]
        if raw is None:
            return None
        return validator(raw, key)

    first = checked(primary) if has_primary else None
    second = checked(alias) if has_alias else None
    if has_primary and has_alias:
        if (first is None) != (second is None) or first != second:
            raise _invalid(primary, f"disagrees with {alias}")
        return first
    return first if has_primary else second


def _vector_entry(item: Any, index: int) -> tuple[str, int, str]:
    if isinstance(item, Mapping):
        allowed = {
            "binding_id", "source_binding_id", "revision", "binding_revision", "snapshot_id",
        }
        if set(item) - allowed:
            raise _invalid(f"snapshot_vector[{index}]", "unknown fields")
        binding_id = _required_alias(item, "binding_id", "source_binding_id", _nonempty_string)
        revision = _required_alias(item, "revision", "binding_revision", _positive_int)
        snapshot_id = _nonempty_string(item.get("snapshot_id"), f"snapshot_vector[{index}].snapshot_id")
        return binding_id, revision, snapshot_id

    if not isinstance(item, (list, tuple)) or len(item) != 3:
        raise _invalid(f"snapshot_vector[{index}]", "must be a 3-field sequence or mapping")
    binding_id = _nonempty_string(item[0], f"snapshot_vector[{index}].binding_id")
    revision = _positive_int(item[1], f"snapshot_vector[{index}].revision")
    snapshot_id = _nonempty_string(item[2], f"snapshot_vector[{index}].snapshot_id")
    return binding_id, revision, snapshot_id


def parse_snapshot_vector(raw_vector: Any) -> SnapshotVector:
    """Parse a vector without coercion, skipping, or duplicate-ID overwrite."""
    if not isinstance(raw_vector, (list, tuple)):
        raise _invalid("snapshot_vector", "must be a list or tuple")
    if not raw_vector:
        raise _invalid("snapshot_vector", "must be non-empty")
    parsed: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_vector):
        binding_id, revision, snapshot_id = _vector_entry(item, index)
        if binding_id in seen:
            raise _invalid(f"snapshot_vector[{index}].binding_id", "duplicate binding_id")
        seen.add(binding_id)
        parsed.append((binding_id, revision, snapshot_id))
    return tuple(parsed)


def _parse_vector_value(raw_vector: Any) -> SnapshotVector:
    if isinstance(raw_vector, str):
        try:
            raw_vector = json.loads(raw_vector)
        except (TypeError, ValueError) as exc:
            raise _invalid("snapshot_vector", "must contain valid JSON") from exc
    return parse_snapshot_vector(raw_vector)


def normalize_accepted_publication(
    accepted: Mapping[str, Any],
    *,
    require_pin: bool = False,
    require_vector: bool = True,
) -> dict[str, Any]:
    """Validate and normalize a context accepted-publication mapping.

    ``accepted_run_id``/``run_id``, ``job_id``/``publication_job_id`` and
    ``attempt``/``publication_attempt`` are compatibility aliases.  If both
    spellings are present, both must be valid and equal.  Optional job/attempt
    provenance remains nullable for unpinned context reads; strong pin callers
    set ``require_pin=True``.
    """
    if not isinstance(accepted, Mapping):
        raise _invalid("accepted_publication", "must be a mapping")

    normalized = dict(accepted)
    generation = _positive_int(accepted.get("generation"), "generation")
    run_id = _required_alias(accepted, "accepted_run_id", "run_id", _positive_int)
    bundle_id = _nonempty_string(accepted.get("publication_bundle_id"), "publication_bundle_id")
    manifest_id = _nonempty_string(accepted.get("snapshot_manifest_id"), "snapshot_manifest_id")
    receipt_id = _nonempty_string(accepted.get("extraction_receipt_id"), "extraction_receipt_id")
    job_id = _optional_alias(accepted, "job_id", "publication_job_id", _nonempty_string)
    attempt = _optional_alias(accepted, "attempt", "publication_attempt", _positive_int)
    if require_pin and (job_id is None or attempt is None):
        raise _invalid("accepted_publication", "job/attempt provenance is required")

    has_vector = "snapshot_vector" in accepted
    has_vector_json = "snapshot_vector_json" in accepted
    if not has_vector and not has_vector_json and require_vector:
        raise _invalid("snapshot_vector", "is required")
    vector = _parse_vector_value(accepted["snapshot_vector"]) if has_vector else None
    vector_json = (
        _parse_vector_value(accepted["snapshot_vector_json"])
        if has_vector_json
        else None
    )
    if vector is not None and vector_json is not None and vector != vector_json:
        raise _invalid("snapshot_vector", "disagrees with snapshot_vector_json")
    normalized_vector = vector if vector is not None else vector_json

    normalized.update(
        {
            "generation": generation,
            "accepted_run_id": run_id,
            "run_id": run_id,
            "publication_bundle_id": bundle_id,
            "snapshot_manifest_id": manifest_id,
            "extraction_receipt_id": receipt_id,
            "job_id": job_id,
            "publication_job_id": job_id,
            "attempt": attempt,
            "publication_attempt": attempt,
            "snapshot_vector": normalized_vector or (),
        }
    )
    return normalized


def attach_vector_status(
    loc: dict[str, Any], snapshot_vector: Sequence[Any]
) -> dict[str, Any]:
    if "source_identity_status" in loc:
        return loc
    try:
        normalized_vector = parse_snapshot_vector(snapshot_vector)
    except (ContextIdentityError, TypeError):
        return {**loc, "source_identity_status": "unbound_or_conflicting_vector"}
    raw_source = loc.get("source")
    src = raw_source if isinstance(raw_source, Mapping) else {}
    bid = src.get("binding_id")
    matches = [item for item in normalized_vector if item[0] == bid]
    if len(matches) == 1 and src.get("snapshot_id") == matches[0][2]:
        if "binding_revision" not in src and isinstance(loc.get("source"), dict):
            loc["source"]["binding_revision"] = int(matches[0][1])
    status = "verified_vector" if (
        len(matches) == 1
        and type(src.get("binding_revision")) is int
        and matches[0][1] == src.get("binding_revision")
        and matches[0][2] == src.get("snapshot_id")
    ) else "unbound_or_conflicting_vector"
    return {**loc, "source_identity_status": status}



def validate_accepted_pin_mapping(accepted: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only full pin fields, retaining vector validation for callers."""
    return normalize_accepted_publication(accepted, require_pin=True, require_vector=False)


__all__ = [
    "ContextIdentityError",
    "attach_vector_status",
    "SnapshotVector",
    "normalize_accepted_publication",
    "parse_snapshot_vector",
    "validate_accepted_pin_mapping",
]
