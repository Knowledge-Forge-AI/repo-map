"""Immutable W4 native-view materialization, identity and manifest checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any

from common_lore_index.retrieval.context_identity import (
    ContextIdentityError,
    normalize_accepted_publication,
)

MAX_NATIVE_SOURCE_FILES = 256
MAX_NATIVE_SOURCE_FILE_BYTES = 1024 * 1024
MAX_NATIVE_SOURCE_BYTES = 8 * 1024 * 1024
PUBLIC_BINDING_POLICY_ALLOWLIST = frozenset({("public-dev", "full-authorized")})
_PRIVATE_BINDING_POLICY = ("private-memory", "metadata-only")

@dataclass(frozen=True)
class ContextNativeView:
    """Explicit native view and immutable source manifest for W4 public bindings."""

    view_root: Path
    selected_relative_paths: tuple[str, ...]
    path_to_binding: Mapping[str, tuple[str, str]]
    source_bytes: Mapping[str, bytes]
    manifest_bytes: bytes
    manifest_sha256: str
    identity: Mapping[str, Any]
    binding_metadata: Mapping[str, Mapping[str, Any]]

    def input_files(self) -> dict[str, bytes]:
        files = {
            "context-v1/native-source-manifest.json": self.manifest_bytes,
        }
        files.update(
            {
                f"context-v1/native-source/{path}": data
                for path, data in self.source_bytes.items()
            }
        )
        return files
def _safe_relative(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("native source path is unsafe")
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in value.split("/")
        )
    ):
        raise ValueError("native source path is unsafe")
    return path.as_posix()
def _binding_attr(binding: Any, name: str, default: Any = None) -> Any:
    return getattr(binding, name, default)
def _manifest_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(identity, Mapping) or identity.get("status") != "ok":
        raise ValueError("native identity must be an accepted readback")
    backend = identity.get("backend")
    graph_id = identity.get("graph_id")
    repository_id = identity.get("repository_id")
    if backend != "sqlite" or not isinstance(graph_id, str) or not graph_id:
        raise ValueError("native identity backend or graph is not trusted")
    if not isinstance(repository_id, str) or not repository_id:
        raise ValueError("native identity repository is not trusted")
    accepted_raw = identity.get("accepted_publication")
    if not isinstance(accepted_raw, Mapping):
        raise ValueError("native identity lacks accepted publication")
    try:
        accepted = normalize_accepted_publication(
            accepted_raw, require_pin=True, require_vector=True
        )
    except (ContextIdentityError, TypeError, ValueError) as error:
        raise ValueError("accepted publication pin is malformed") from error
    vector = [list(entry) for entry in accepted["snapshot_vector"]]
    return {
        "backend": backend,
        "graph_id": graph_id,
        "repository_id": repository_id,
        "accepted_publication": {
            "generation": accepted["generation"],
            "accepted_run_id": accepted["accepted_run_id"],
            "run_id": accepted["run_id"],
            "publication_bundle_id": accepted["publication_bundle_id"],
            "snapshot_manifest_id": accepted["snapshot_manifest_id"],
            "extraction_receipt_id": accepted["extraction_receipt_id"],
            "job_id": accepted["job_id"],
            "publication_job_id": accepted["publication_job_id"],
            "attempt": accepted["attempt"],
            "publication_attempt": accepted["publication_attempt"],
            "snapshot_vector": vector,
        },
    }
def _binding_manifest_record(binding: Any) -> dict[str, Any] | None:
    privacy = _binding_attr(binding, "privacy")
    retention = _binding_attr(binding, "evidence_retention")
    if (privacy, retention) == _PRIVATE_BINDING_POLICY:
        return None
    if (privacy, retention) not in PUBLIC_BINDING_POLICY_ALLOWLIST:
        raise ValueError("native binding privacy or retention is not allowlisted")
    values = {
        "binding_id": _binding_attr(binding, "binding_id"),
        "alias": _binding_attr(binding, "alias"),
        "source_definition_id": _binding_attr(binding, "source_definition_id"),
        "revision": _binding_attr(binding, "revision"),
        "selection_policy_id": _binding_attr(binding, "selection_policy_id"),
        "role": _binding_attr(binding, "role"),
        "privacy": privacy,
        "evidence_retention": retention,
    }
    string_fields = (
        "binding_id", "alias", "source_definition_id", "selection_policy_id",
        "role", "privacy", "evidence_retention",
    )
    if any(not isinstance(values[key], str) or not values[key] for key in string_fields):
        raise ValueError("native binding metadata is incomplete")
    if type(values["revision"]) is not int or values["revision"] < 1:
        raise ValueError("native binding revision is invalid")
    values["alias"] = _safe_relative(values["alias"])
    return values

def _read_regular_bytes(path: Path, *, max_bytes: int) -> bytes:
    try:
        mode = os.lstat(path).st_mode
    except OSError as error:
        raise ValueError("native source is unavailable") from error
    if not stat.S_ISREG(mode):
        raise ValueError("native source is not a regular file")
    try:
        with path.open("rb") as source:
            data = source.read(max_bytes + 1)
    except OSError as error:
        raise ValueError("native source cannot be read") from error
    if len(data) > max_bytes:
        raise ValueError("native source file exceeds the bounded size")
    return data
def validate_context_native_identity(
    view: ContextNativeView,
    *,
    graph_id: str,
    repository_id: str,
    accepted_publication: Mapping[str, Any],
    configured_binding_ids: Sequence[str],
) -> dict[str, Any]:
    """Bind the explicit view to public accepted identity without content claims."""
    expected = _manifest_identity(
        {
            "status": "ok",
            "backend": "sqlite",
            "graph_id": graph_id,
            "repository_id": repository_id,
            "accepted_publication": accepted_publication,
        }
    )
    if view.identity != expected:
        raise ValueError("native view identity does not match accepted readback")
    view_bindings = {binding_id for binding_id, _ in view.path_to_binding.values()}
    configured = set(configured_binding_ids)
    if not view_bindings or not view_bindings <= configured:
        raise ValueError("native view binding is not configured")
    vector_by_binding: dict[str, tuple[int, str]] = {}
    vector = expected["accepted_publication"]["snapshot_vector"]
    for entry in vector:
        if not isinstance(entry, (list, tuple)) or len(entry) != 3:
            raise ValueError("accepted snapshot vector is malformed")
        binding_id, revision, snapshot_id = entry
        if (
            not isinstance(binding_id, str)
            or type(revision) is not int
            or revision < 1
            or not isinstance(snapshot_id, str)
            or not snapshot_id
            or binding_id in vector_by_binding
        ):
            raise ValueError("accepted snapshot vector is malformed")
        vector_by_binding[binding_id] = (revision, snapshot_id)
    if not view_bindings <= set(vector_by_binding):
        raise ValueError("native view binding is absent from accepted snapshot vector")
    return {
        **expected,
        "binding_ids": sorted(view_bindings),
        "source_content_correspondence": "fixture_manifest_only",
    }
def materialize_context_native_view(
    view_root: Path,
    *,
    bindings: Sequence[Any],
    accepted_identity: Mapping[str, Any],
) -> ContextNativeView:
    """Copy only allowlisted public roots into a fresh, bounded native view."""
    identity = _manifest_identity(accepted_identity)
    if view_root.exists() or view_root.is_symlink():
        raise ValueError("native view destination must be absent")

    binding_records: dict[str, dict[str, Any]] = {}
    collected: list[tuple[str, str, str, bytes]] = []
    aliases: set[str] = set()
    total_bytes = 0
    for binding in sorted(bindings, key=lambda item: str(_binding_attr(item, "binding_id", ""))):
        record = _binding_manifest_record(binding)
        if record is None:
            continue
        binding_id = record["binding_id"]
        alias = record["alias"]
        if binding_id in binding_records or alias in aliases:
            raise ValueError("native binding identity is duplicated")
        aliases.add(alias)
        binding_records[binding_id] = record
        root_raw = _binding_attr(binding, "root_path_expanded") or _binding_attr(binding, "root_path")
        if not isinstance(root_raw, str):
            raise ValueError("native binding lacks a public root identity")
        root = Path(root_raw)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError("native binding root is not an explicit regular directory")
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError("native fixture contains a symlink")
            if not path.exists():
                raise ValueError("native fixture changed during materialization")
            try:
                mode = os.lstat(path).st_mode
            except OSError as error:
                raise ValueError("native fixture cannot be inspected") from error
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError("native fixture contains a non-regular file")
            if len(collected) >= MAX_NATIVE_SOURCE_FILES:
                raise ValueError("native fixture exceeds the file-count bound")
            rel = _safe_relative(path.relative_to(root).as_posix())
            data = _read_regular_bytes(path, max_bytes=MAX_NATIVE_SOURCE_FILE_BYTES)
            total_bytes += len(data)
            if total_bytes > MAX_NATIVE_SOURCE_BYTES:
                raise ValueError("native fixture exceeds the total-size bound")
            view_rel = f"{alias}/{rel}"
            collected.append((view_rel, binding_id, rel, data))

    if not binding_records or not collected:
        raise ValueError("native comparator has no public source inputs")
    accepted_vector = {entry[0]: entry[1] for entry in identity["accepted_publication"]["snapshot_vector"]}
    if any(binding_id not in accepted_vector or accepted_vector[binding_id] != record["revision"]
           for binding_id, record in binding_records.items()):
        raise ValueError("native binding revision is absent from accepted publication")
    view_root.mkdir(parents=True, exist_ok=False)
    selected: list[str] = []
    path_to_binding: dict[str, tuple[str, str]] = {}
    source_bytes: dict[str, bytes] = {}
    manifest_entries: list[dict[str, Any]] = []
    for view_rel, binding_id, rel, data in collected:
        if view_rel in path_to_binding:
            raise ValueError("native source path is duplicated")
        dest = view_root / view_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        selected.append(view_rel)
        path_to_binding[view_rel] = (binding_id, rel)
        source_bytes[view_rel] = data
        manifest_entries.append(
            {
                "binding_id": binding_id,
                "source_relative_path": rel,
                "view_relative_path": view_rel,
                "size_bytes": len(data),
                "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "schema_version": "cloe-context-native-source-manifest-v1",
        "identity": identity,
        "bindings": [binding_records[key] for key in sorted(binding_records)],
        "entries": sorted(manifest_entries, key=lambda item: item["view_relative_path"]),
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return ContextNativeView(
        view_root=view_root,
        selected_relative_paths=tuple(sorted(selected)),
        path_to_binding=path_to_binding,
        source_bytes=source_bytes,
        manifest_bytes=manifest_bytes,
        manifest_sha256="sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        identity=identity,
        binding_metadata=binding_records,
    )

def validate_materialized_context_native_view(view: ContextNativeView) -> None:
    """Re-read and verify every native input against the archived manifest."""
    if view.view_root.is_symlink() or not view.view_root.is_dir():
        raise ValueError("native view root is unavailable")
    if "sha256:" + hashlib.sha256(view.manifest_bytes).hexdigest() != view.manifest_sha256:
        raise ValueError("native source manifest digest mismatch")
    try:
        manifest = json.loads(view.manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("native source manifest is malformed") from error
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version", "identity", "bindings", "entries"
    } or manifest.get("schema_version") != "cloe-context-native-source-manifest-v1":
        raise ValueError("native source manifest schema mismatch")
    if manifest["identity"] != dict(view.identity):
        raise ValueError("native source manifest identity mismatch")
    raw_bindings = manifest["bindings"]
    if not isinstance(raw_bindings, list):
        raise ValueError("native source manifest bindings are malformed")
    manifest_bindings: dict[str, dict[str, Any]] = {}
    for raw_binding in raw_bindings:
        if not isinstance(raw_binding, dict):
            raise ValueError("native source manifest binding is malformed")
        binding_id = raw_binding.get("binding_id")
        if not isinstance(binding_id, str) or binding_id in manifest_bindings:
            raise ValueError("native source manifest binding identity is duplicated")
        manifest_bindings[binding_id] = raw_binding
    if manifest_bindings != {key: dict(value) for key, value in view.binding_metadata.items()}:
        raise ValueError("native source manifest binding metadata mismatch")

    raw_entries = manifest["entries"]
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_NATIVE_SOURCE_FILES:
        raise ValueError("native source manifest exceeds the file-count bound")
    entries: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for entry in raw_entries:
        if not isinstance(entry, dict) or set(entry) != {
            "binding_id", "source_relative_path", "view_relative_path", "size_bytes", "sha256"
        }:
            raise ValueError("native source manifest entry is malformed")
        view_rel = _safe_relative(entry["view_relative_path"])
        source_rel = _safe_relative(entry["source_relative_path"])
        binding_id = entry["binding_id"]
        size_bytes = entry["size_bytes"]
        digest = entry["sha256"]
        if (
            view_rel in entries
            or not isinstance(binding_id, str)
            or binding_id not in manifest_bindings
            or type(size_bytes) is not int
            or size_bytes < 0
            or size_bytes > MAX_NATIVE_SOURCE_FILE_BYTES
            or not isinstance(digest, str)
            or len(digest) != 71
            or not digest.startswith("sha256:")
        ):
            raise ValueError("native source manifest entry is invalid")
        entries[view_rel] = {
            **entry,
            "view_relative_path": view_rel,
            "source_relative_path": source_rel,
        }
        total_bytes += size_bytes
        if total_bytes > MAX_NATIVE_SOURCE_BYTES:
            raise ValueError("native source manifest exceeds the total-size bound")

    if set(entries) != set(view.selected_relative_paths):
        raise ValueError("native source manifest path set mismatch")
    if set(entries) != set(view.path_to_binding) or set(entries) != set(view.source_bytes):
        raise ValueError("native source manifest evidence set mismatch")
    actual_files: dict[str, bytes] = {}
    for path in sorted(view.view_root.rglob("*")):
        if path.is_symlink():
            raise ValueError("native view contains a symlink")
        mode = os.lstat(path).st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError("native view contains a non-regular file")
        view_rel = _safe_relative(path.relative_to(view.view_root).as_posix())
        if view_rel not in entries:
            raise ValueError("native view contains extra evidence")
        data = _read_regular_bytes(path, max_bytes=MAX_NATIVE_SOURCE_FILE_BYTES)
        entry = entries[view_rel]
        if (
            len(data) != entry["size_bytes"]
            or "sha256:" + hashlib.sha256(data).hexdigest() != entry["sha256"]
            or data != view.source_bytes[view_rel]
            or view.path_to_binding[view_rel]
            != (entry["binding_id"], entry["source_relative_path"])
        ):
            raise ValueError("native view evidence does not match its manifest")
        actual_files[view_rel] = data
    if set(actual_files) != set(entries):
        raise ValueError("native view is missing manifest evidence")


__all__ = [
    "ContextNativeView",
    "MAX_NATIVE_SOURCE_BYTES",
    "MAX_NATIVE_SOURCE_FILE_BYTES",
    "MAX_NATIVE_SOURCE_FILES",
    "PUBLIC_BINDING_POLICY_ALLOWLIST",
    "materialize_context_native_view",
    "validate_context_native_identity",
    "validate_materialized_context_native_view",
]
