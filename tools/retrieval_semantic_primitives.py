"""Shared validation primitives, path checks, and representation records for W5 (ADR 0137)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from types import MappingProxyType
from typing import Any, TypeVar

from common_lore_index.ops.config_helpers import redact_text
from common_lore_index.retrieval.context_identity import ContextIdentityError

W5_FOUNDATION_SCHEMA_VERSION = "cloe-w5-foundation-v1"
CANONICAL_NODE_REPRESENTATION_VERSION = "canonical-node-v1"
REPRESENTATION_POLICY_VERSION = "cloe-w5-representation-provenance-v1"
MAX_REPRESENTATION_RECORDS = 500
MAX_PUBLIC_STRING_LENGTH = 500
MAX_JSON_DEPTH = 16
MAX_JSON_COLLECTION_ITEMS = 2000
_T = TypeVar("_T")


class RepresentationValidationError(ValueError):
    """Structured refusal raised when representation or provenance validation fails."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise RepresentationValidationError(code, detail)


def _guard(fn: Callable[[], _T], code: str) -> _T:
    try:
        return fn()
    except (ValueError, ContextIdentityError, UnicodeEncodeError) as exc:
        raise RepresentationValidationError(code, str(exc)) from exc


def validate_relative_path(path: str, field_name: str = "source_relative_path") -> str:
    """Validate that path is a clean POSIX relative path without traversal or drive/scheme prefixes."""
    if (
        type(path) is not str
        or not path
        or path != path.strip()
        or "\x00" in path
        or "\\" in path
        or ":" in path
    ):
        raise ValueError(f"{field_name} must be a non-empty POSIX relative path")
    if path.startswith(("/", "./", "~")) or any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError(f"{field_name} contains invalid relative path segment")
    return path


def is_sanitized_public_string(value: str, *, private_markers: Sequence[str] = ()) -> bool:
    """Return True if value survives text redaction and contains no private marker."""
    if redact_text(value) != value:
        return False
    return not any(marker and marker in value for marker in private_markers)


def freeze_jsonable(value: Any, *, _depth: int = 0) -> Any:
    """Deep-copy and freeze JSON-compatible structures without key coercion or non-finite numbers."""
    _require(_depth <= MAX_JSON_DEPTH, "invalid_field_bounds", "JSON nesting depth exceeded")
    if isinstance(value, Mapping):
        _require(len(value) <= MAX_JSON_COLLECTION_ITEMS, "invalid_field_bounds", "mapping size exceeded")
        frozen_map: dict[str, Any] = {}
        for k, v in value.items():
            _require(type(k) is str, "invalid_input_type", "mapping keys must be exact str")
            assert isinstance(k, str)
            _require(
                bool(k) and len(k) <= MAX_PUBLIC_STRING_LENGTH and not any(ord(c) < 32 or ord(c) == 127 for c in k),
                "invalid_field_bounds",
                "mapping key out of bounds or contains control characters",
            )
            key: str = k
            _guard(lambda: key.encode("utf-8", errors="strict"), "invalid_unicode_surrogate")
            frozen_map[key] = freeze_jsonable(v, _depth=_depth + 1)
        return MappingProxyType(frozen_map)
    if type(value) in {list, tuple}:
        _require(len(value) <= MAX_JSON_COLLECTION_ITEMS, "invalid_field_bounds", "sequence size exceeded")
        return tuple(freeze_jsonable(item, _depth=_depth + 1) for item in value)
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        _require(math.isfinite(value), "invalid_input_type", "non-finite float is forbidden")
        return value
    if type(value) is str:
        _require(
            len(value) <= MAX_PUBLIC_STRING_LENGTH * 4 and "\x00" not in value,
            "invalid_field_bounds",
            "string value out of bounds or contains NUL",
        )
        _guard(lambda: value.encode("utf-8", errors="strict"), "invalid_unicode_surrogate")
        return value
    raise RepresentationValidationError("invalid_input_type", f"unsupported {type(value).__name__}")


def _validate_representation_string(
    value: Any, field_name: str, *, private_markers: Sequence[str] = ()
) -> str:
    _require(type(value) is str, "invalid_field_type", f"{field_name} must be an exact str")
    assert isinstance(value, str)
    _require(
        bool(value and value.strip()) and len(value) <= MAX_PUBLIC_STRING_LENGTH,
        "invalid_field_bounds",
        f"{field_name} out of bounds",
    )
    _require(
        not any(ord(ch) < 32 or ord(ch) == 127 for ch in value),
        "invalid_control_character",
        f"{field_name} has control/NUL char",
    )
    _guard(lambda: value.encode("utf-8", errors="strict"), "invalid_unicode_surrogate")
    _require(
        is_sanitized_public_string(value, private_markers=private_markers),
        "privacy_refused",
        f"{field_name} failed sanitization",
    )
    return value


def encode_canonical_node_v1_bytes(
    canonical_key: Any, kind: Any, display_name: Any, *, private_markers: Sequence[str] = ()
) -> bytes:
    """Encode canonical-node-v1 compact sorted UTF-8 JSON bytes with unescaped Unicode."""
    markers = tuple(str(x) for x in private_markers if x)
    payload = {
        "canonical_key": _validate_representation_string(canonical_key, "canonical_key", private_markers=markers),
        "kind": _validate_representation_string(kind, "kind", private_markers=markers),
        "display_name": _validate_representation_string(display_name, "display_name", private_markers=markers),
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8", errors="strict")


def canonical_node_v1_digest(
    canonical_key: Any, kind: Any, display_name: Any, *, private_markers: Sequence[str] = ()
) -> str:
    """Compute sha256:<hex> over exact canonical-node-v1 UTF-8 bytes."""
    raw = encode_canonical_node_v1_bytes(canonical_key, kind, display_name, private_markers=private_markers)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class AcceptedNodeRecord:
    canonical_key: str
    kind: Any
    display_name: Any
    graph_key_version: int = 1
    last_seen_run_id: int = 1


@dataclass(frozen=True)
class AcceptedEvidenceRecord:
    canonical_key: str
    evidence_key: str
    run_id: int
    graph_key_version: int
    path: str | None
    metadata_json: Mapping[str, Any] | str | None
    link_kind: str = "observed"


@dataclass(frozen=True)
class ClaimedNodeRepresentation:
    canonical_key: str
    source_binding_id: str
    input_digest: str
    snapshot_id: str | None = None
    claimed_kind: str | None = None
    claimed_display_name: str | None = None
    vector: tuple[float, ...] | None = None
    dimensions: int | None = None


@dataclass(frozen=True)
class VerifiedNodeRepresentation:
    canonical_key: str
    kind: str
    display_name: str
    source_binding_id: str
    snapshot_id: str
    binding_revision: int
    source_relative_paths: tuple[str, ...]
    evidence_keys: tuple[str, ...]
    representation_bytes_len: int
    input_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "source_relative_paths": list(self.source_relative_paths),
            "evidence_keys": list(self.evidence_keys),
            "representation_version": CANONICAL_NODE_REPRESENTATION_VERSION,
        }


@dataclass(frozen=True)
class ExcludedNodeRepresentation:
    canonical_key: str
    source_binding_id: str | None
    reason_code: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
