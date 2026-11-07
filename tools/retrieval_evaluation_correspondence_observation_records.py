"""Bounded current-observation requests, validated rows, and page records."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from common_lore_index.retrieval.query_contracts import OmissionRecord
from common_lore_index.storage.sqlite_local import raw_payload
from retrieval_evaluation_observation_contracts import CurrentObservationReadError
from retrieval_evaluation_scope import evaluation_path_prefix, source_path_matches_prefix

MAX_QUERY_LENGTH = 200


MAX_FILTER_LENGTH = 300


MAX_RESULT_LIMIT = 100


MAX_RESULT_OFFSET = 10000


MAX_SELECTED_BINDINGS = 32


@dataclass(frozen=True, slots=True)
class CurrentObservationQuery:
    query: str
    kind: str | None = None
    path: str | None = None
    limit: int = 10
    offset: int = 0
    selected_binding_ids: Sequence[str] = ()
    source_path_prefix: str | None = None

    def validate(self) -> CurrentObservationQuery:
        if type(self.query) is not str or not self.query or "\x00" in self.query or len(self.query) > MAX_QUERY_LENGTH:
            raise ValueError("current observation query is required and bounded")
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_RESULT_LIMIT:
            raise ValueError("current observation limit is bounded")
        if type(self.offset) is not int or not 0 <= self.offset <= MAX_RESULT_OFFSET:
            raise ValueError("current observation offset is bounded")
        if self.kind is not None and (type(self.kind) is not str or not self.kind or "\x00" in self.kind or len(self.kind) > MAX_FILTER_LENGTH):
            raise ValueError("current observation kind is invalid")
        if self.path is not None and (type(self.path) is not str or not self.path or "\x00" in self.path or len(self.path) > MAX_FILTER_LENGTH):
            raise ValueError("current observation path is invalid")
        if not isinstance(self.selected_binding_ids, Sequence) or isinstance(self.selected_binding_ids, (str, bytes)):
            raise ValueError("selected bindings must be a sequence")
        if len(self.selected_binding_ids) > MAX_SELECTED_BINDINGS:
            raise ValueError("too many selected bindings")
        if any(
            type(binding) is not str or not binding or len(binding) > MAX_FILTER_LENGTH
            for binding in self.selected_binding_ids
        ):
            raise ValueError("selected bindings must be non-empty strings")
        if len(set(self.selected_binding_ids)) != len(self.selected_binding_ids):
            raise ValueError("selected bindings must be unique")
        if self.source_path_prefix is not None and (
            type(self.source_path_prefix) is not str
            or not self.source_path_prefix
            or len(self.source_path_prefix) > MAX_FILTER_LENGTH
        ):
            raise ValueError("source path prefix is bounded")
        if self.source_path_prefix is not None:
            evaluation_path_prefix(self.source_path_prefix)
        return self


@dataclass(frozen=True, slots=True)
class FencedObservationResult:
    backend: str
    graph_id: str
    repository_identity: str
    accepted_run_id: int
    accepted_generation: int
    publication_bundle_id: str
    snapshot_manifest_id: str
    rows: tuple[dict[str, Any], ...]
    omissions: tuple[OmissionRecord, ...] = ()
    scope_complete: bool = True
    has_more: bool = False
    fence_elapsed_ns: int = 0
    query_statement_ns: int | None = None
    known_payload_bytes: int | None = None
    database_wire_bytes: int | None = None


def _validate_relative_path(value: str, label: str) -> None:
    if type(value) is not str or not value or value.startswith("/") or "\\" in value or "\x00" in value:
        raise ValueError(f"{label} must be a relative path")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"{label} has invalid path segments")


def _snapshot_map(vector: Sequence[Sequence[Any]]) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    for item in vector:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise CurrentObservationReadError("malformed_snapshot_vector", "snapshot vector row is invalid")
        binding, revision, snapshot = item
        if (
            type(binding) is not str or not binding
            or type(revision) is not int or isinstance(revision, bool) or revision < 1
            or type(snapshot) is not str or not snapshot or binding in result
        ):
            raise CurrentObservationReadError("malformed_snapshot_vector", "snapshot vector row is invalid")
        result[binding] = (revision, snapshot)
    return result


def _validate_metadata(payload: Any, snapshots: Mapping[str, tuple[int, str]]) -> Mapping[str, Any]:
    metadata = payload.get("metadata") if isinstance(payload, Mapping) else None
    if not isinstance(metadata, Mapping):
        raise CurrentObservationReadError("malformed_observation_metadata", "observation metadata is required")
    binding = metadata.get("binding_id")
    revision = metadata.get("binding_revision")
    snapshot = metadata.get("snapshot_id")
    relative = metadata.get("source_relative_path")
    if type(binding) is not str or not binding or type(revision) is not int or isinstance(revision, bool):
        raise CurrentObservationReadError("malformed_observation_metadata", "binding metadata is invalid")
    if type(snapshot) is not str or not snapshot or type(relative) is not str:
        raise CurrentObservationReadError("malformed_observation_metadata", "snapshot/path metadata is invalid")
    try:
        _validate_relative_path(relative, "source_relative_path")
    except ValueError as error:
        raise CurrentObservationReadError("malformed_observation_metadata", "source path metadata is invalid") from error
    expected = snapshots.get(binding)
    if expected is None:
        raise CurrentObservationReadError("unknown_observation_binding", "observation binding is absent from accepted snapshot vector")
    if (revision, snapshot) != expected:
        raise CurrentObservationReadError("observation_snapshot_mismatch", "observation binding revision or snapshot differs from accepted vector")
    return metadata


def _matches(request: CurrentObservationQuery, row: Mapping[str, Any], payload: Any) -> bool:
    needle = raw_payload.ascii_lower(request.query)
    values = (row["kind"], row["source_id"], row["path"], raw_payload.jsonb_text(payload))
    return any(needle in raw_payload.ascii_lower(str(value)) for value in values)


def _postgres_candidate(raw: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if not isinstance(raw, Mapping):
        raise CurrentObservationReadError("malformed_observation_readback", "PostgreSQL observation row is invalid")
    ordinal, kind, source_id, path, payload = (
        raw.get("ordinal"), raw.get("kind"), raw.get("source_id"), raw.get("path"), raw.get("payload")
    )
    if (
        type(ordinal) is not int or isinstance(ordinal, bool) or ordinal < 0
        or type(kind) is not str or type(source_id) is not str or type(path) is not str
        or not isinstance(payload, Mapping)
    ):
        raise CurrentObservationReadError("malformed_observation_readback", "PostgreSQL observation row fields are invalid")
    return {"ordinal": ordinal, "kind": kind, "source_id": source_id, "path": path}, payload


def _page_rows(
    request: CurrentObservationQuery,
    candidates: Sequence[tuple[Mapping[str, Any], Any]],
    snapshots: Mapping[str, tuple[int, str]],
    *,
    has_more: bool = False,
) -> tuple[tuple[dict[str, Any], ...], tuple[OmissionRecord, ...], bool, bool]:
    selected = set(request.selected_binding_ids)
    scoped: list[dict[str, Any]] = []
    _validate_selected_bindings(request, snapshots)
    for row, payload in candidates:
        if not _matches(request, row, payload):
            continue
        # Validate every matching row before applying caller selection. A
        # malformed or foreign matching row must not be silently dropped.
        metadata = _validate_metadata(payload, snapshots)
        binding = str(metadata["binding_id"])
        relative = str(metadata["source_relative_path"])
        if selected and binding not in selected:
            continue
        if not source_path_matches_prefix(relative, request.source_path_prefix):
            continue
        scoped.append({**dict(row), "metadata": dict(metadata)})
    omissions: list[OmissionRecord] = []
    has_more = has_more or len(scoped) > request.offset + request.limit
    if has_more:
        omissions.append(OmissionRecord("scope", None, "observation_page_limit", "bounded current-observation page omitted additional matching rows").validate())
    return (
        tuple(scoped[request.offset : request.offset + request.limit]),
        tuple(omissions), not omissions, has_more,
    )



def _validate_selected_bindings(
    request: CurrentObservationQuery, snapshots: Mapping[str, tuple[int, str]]
) -> None:
    unknown = set(request.selected_binding_ids).difference(snapshots)
    if unknown:
        raise CurrentObservationReadError(
            "unknown_selected_binding", "selected binding is absent from accepted snapshot vector"
        )
