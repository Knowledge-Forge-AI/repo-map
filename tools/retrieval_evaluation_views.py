"""Materialize policy-authorized body and extracted-metadata views from retained ArtifactStore (S3)."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from common_lore_index.artifacts.bundle import PublicationBundle
from common_lore_index.artifacts.manifest import (
    ManifestArtifact,
    ManifestBinding,
    PortableSnapshotManifest,
)
from common_lore_index.artifacts.store import ArtifactStore
from common_lore_index.retrieval.projection_policy import (
    BodyProjectionPolicy,
    ExclusionReason,
    SUPPORTED_TEXT_FORMATS,
    evaluate_artifact_pre_open,
    evaluate_binding_exclusion,
)
from common_lore_index.retrieval.query_contracts import MatchSurface

NATIVE_MATERIALIZATION_WITNESS_SCHEMA_V1 = "cloe-w5-native-materialization-witness-v1"


@dataclass(frozen=True)
class NativeMaterializedFileWitness:
    """Cryptographic witness for one materialized public body or rendered metadata file."""

    binding_id: str
    alias: str
    snapshot_id: str
    source_relative_path: str
    view_relative_path: str
    match_surface: str
    byte_length: int
    content_sha256: str

    @property
    def surface_kind(self) -> str:
        return "raw_body" if self.match_surface == MatchSurface.CAPTURED_TEXT.value else "rendered_extracted_metadata"

    def validate(self) -> NativeMaterializedFileWitness:
        if (
            not self.binding_id or not self.alias or not self.snapshot_id
            or not self.source_relative_path or not self.view_relative_path
            or "/" in self.alias or "\\" in self.alias
            or any(PurePosixPath(value).is_absolute() or "\\" in value or "\x00" in value
                   or any(part in {"", ".", ".."} for part in value.split("/"))
                   for value in (self.alias, self.source_relative_path, self.view_relative_path))
            or self.match_surface not in {MatchSurface.CAPTURED_TEXT.value, MatchSurface.STORED_METADATA.value}
            or isinstance(self.byte_length, bool) or not isinstance(self.byte_length, int) or self.byte_length < 0
            or not self.content_sha256.startswith("sha256:") or len(self.content_sha256) != 71
        ):
            raise ValueError("native_witness_invalid")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "binding_id": self.binding_id, "alias": self.alias, "snapshot_id": self.snapshot_id,
            "source_relative_path": self.source_relative_path, "view_relative_path": self.view_relative_path,
            "match_surface": self.match_surface, "byte_length": self.byte_length, "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class NativeMaterializationWitness:
    """Versioned witness binding a MaterializedNativeView to accepted publication artifacts."""

    schema_version: str
    graph_id: str
    publication_bundle_id: str
    snapshot_manifest_id: str
    graph_candidate_id: str
    policy_digest: str
    snapshot_vector: tuple[tuple[str, int, str], ...]
    selected_aliases: tuple[str, ...]
    include_extracted_metadata_for_non_body: bool
    excluded_bindings: Mapping[str, str]
    files: tuple[NativeMaterializedFileWitness, ...]
    total_bytes: int
    witness_digest: str

    @property
    def schema(self) -> str:
        return self.schema_version

    @property
    def total_bytes_verified(self) -> int:
        return self.total_bytes

    def validate(self) -> NativeMaterializationWitness:
        if (
            self.schema_version != NATIVE_MATERIALIZATION_WITNESS_SCHEMA_V1
            or not self.graph_id or not self.publication_bundle_id
            or not self.snapshot_manifest_id or not self.graph_candidate_id
            or not self.policy_digest or not self.snapshot_vector
            or isinstance(self.total_bytes, bool) or not isinstance(self.total_bytes, int) or self.total_bytes < 0
            or not self.witness_digest.startswith("sha256:") or len(self.witness_digest) != 71
        ):
            raise ValueError("native_witness_invalid")
        for f in self.files:
            f.validate()
        if sum(f.byte_length for f in self.files) != self.total_bytes:
            raise ValueError("native_witness_invalid")
        if self.witness_digest != _compute_witness_digest(self._payload_without_digest()):
            raise ValueError("native_witness_mismatch")
        return self

    def _payload_without_digest(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "graph_id": self.graph_id,
            "publication_bundle_id": self.publication_bundle_id, "snapshot_manifest_id": self.snapshot_manifest_id,
            "graph_candidate_id": self.graph_candidate_id, "policy_digest": self.policy_digest,
            "snapshot_vector": [[b, int(r), s] for b, r, s in self.snapshot_vector],
            "selected_aliases": list(self.selected_aliases),
            "include_extracted_metadata_for_non_body": bool(self.include_extracted_metadata_for_non_body),
            "excluded_bindings": dict(sorted(self.excluded_bindings.items())),
            "files": [f.to_dict() for f in self.files], "total_bytes": self.total_bytes,
        }

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {**self._payload_without_digest(), "witness_digest": self.witness_digest}


def _compute_witness_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class MaterializedNativeView:
    """Materialized filesystem view for native git-grep search without projection size caps."""

    view_root: Path
    selected_relative_paths: tuple[str, ...]
    path_to_binding: Mapping[str, tuple[str, str]]
    path_to_surface: Mapping[str, MatchSurface]
    excluded_bindings: Mapping[str, str]
    materialization_witness: NativeMaterializationWitness | None = None


def _can_materialize_raw_body(
    policy: BodyProjectionPolicy,
    binding: ManifestBinding,
    artifact: ManifestArtifact,
) -> tuple[bool, str | None]:
    pre_reason, _fmt = evaluate_artifact_pre_open(policy, binding, artifact)
    if pre_reason is not None and pre_reason != ExclusionReason.ARTIFACT_OVERSIZED:
        return False, pre_reason.value
    suffix = PurePosixPath(artifact.source_relative_path).suffix.lower()
    if suffix not in SUPPORTED_TEXT_FORMATS:
        return False, ExclusionReason.UNSUPPORTED_SOURCE_FORMAT.value
    return True, None


def _render_extracted_metadata_lines(
    bundle: PublicationBundle,
    binding_id: str,
    source_relative_path: str,
) -> list[str]:
    raw_obs = bundle.families.get("raw_observations", ())
    lines: list[str] = []
    for row in raw_obs:
        payload = row.get("payload_json")
        meta = payload.get("metadata") if isinstance(payload, Mapping) else None
        if not isinstance(meta, Mapping):
            raise ValueError("native_metadata_observation_missing")
        if meta.get("binding_id") != binding_id:
            continue
        if meta.get("source_relative_path") != source_relative_path:
            continue
        kind = str(row.get("kind") or "")
        source_id = str(row.get("source_id") or "")
        meta_json = json.dumps(meta, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        lines.append(f"{kind} {source_id} {meta_json}")
    return lines


def _expected_native_view_entries(
    *,
    manifest: PortableSnapshotManifest,
    bundle: PublicationBundle,
    store: ArtifactStore,
    policy: BodyProjectionPolicy,
    selected_aliases: Sequence[str],
    include_extracted_metadata_for_non_body: bool = True,
) -> tuple[dict[str, str], list[tuple[NativeMaterializedFileWitness, bytes, MatchSurface]]]:
    if manifest.graph_id != bundle.graph_id or manifest.graph_id != policy.graph_id:
        raise ValueError("native_witness_graph_id_mismatch")
    if bundle.snapshot_manifest_id != manifest.manifest_id or tuple(bundle.snapshot_vector) != tuple(
        manifest.snapshot_vector
    ):
        raise ValueError("native_witness_manifest_mismatch")
    selected_alias_set = set(selected_aliases)
    bindings_by_id = {b.binding_id: b for b in manifest.bindings}
    excluded_bindings: dict[str, str] = {}
    for binding in sorted(manifest.bindings, key=lambda item: item.binding_id):
        if binding.alias not in selected_alias_set:
            excluded_bindings[binding.binding_id] = ExclusionReason.BINDING_NOT_SELECTED.value
            continue
        b_reason = evaluate_binding_exclusion(policy, binding)
        if b_reason is not None:
            excluded_bindings[binding.binding_id] = b_reason.value

    sorted_entries = sorted(manifest.entries, key=lambda item: (item.binding_id, item.source_relative_path))
    items: list[tuple[NativeMaterializedFileWitness, bytes, MatchSurface]] = []
    for entry in sorted_entries:
        binding = bindings_by_id[entry.binding_id]
        if binding.alias not in selected_alias_set:
            continue
        ok_body, _reason = _can_materialize_raw_body(policy, binding, entry)
        if ok_body:
            raw_bytes = store.read(
                entry.reference.with_store_version(None),
                max_bytes=max(entry.reference.size_bytes + 1024, 16 * 1024 * 1024),
            )
            rel_in_view = f"{binding.alias}/{entry.source_relative_path}"
            surface = MatchSurface.CAPTURED_TEXT
            items.append((
                NativeMaterializedFileWitness(
                    binding_id=entry.binding_id, alias=binding.alias, snapshot_id=binding.snapshot_id,
                    source_relative_path=entry.source_relative_path, view_relative_path=rel_in_view,
                    match_surface=surface.value, byte_length=len(raw_bytes),
                    content_sha256="sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
                ).validate(),
                raw_bytes,
                surface,
            ))
        elif include_extracted_metadata_for_non_body and binding.alias in {"feeds", "mailbox"}:
            resolved = policy.bindings.get(binding.binding_id)
            if resolved is None or resolved.resolved_graph_privacy != "public-dev" or resolved.resolved_binding_privacy != "public-dev":
                continue
            meta_lines = _render_extracted_metadata_lines(bundle, entry.binding_id, entry.source_relative_path)
            if meta_lines:
                rel_in_view = f"{binding.alias}/.extracted-metadata/{entry.source_relative_path}.meta.txt"
                raw_bytes = ("\n".join(meta_lines) + "\n").encode("utf-8")
                surface = MatchSurface.STORED_METADATA
                items.append((
                    NativeMaterializedFileWitness(
                        binding_id=entry.binding_id, alias=binding.alias, snapshot_id=binding.snapshot_id,
                        source_relative_path=entry.source_relative_path, view_relative_path=rel_in_view,
                        match_surface=surface.value, byte_length=len(raw_bytes),
                        content_sha256="sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
                    ).validate(),
                    raw_bytes,
                    surface,
                ))
    return excluded_bindings, items


def build_native_materialization_witness(
    *,
    manifest: PortableSnapshotManifest,
    bundle: PublicationBundle,
    store: ArtifactStore,
    policy: BodyProjectionPolicy,
    selected_aliases: Sequence[str],
    include_extracted_metadata_for_non_body: bool = True,
) -> NativeMaterializationWitness:
    """Recompute the deterministic NativeMaterializationWitness from manifest, bundle, store, and policy."""
    excluded_bindings, items = _expected_native_view_entries(
        manifest=manifest, bundle=bundle, store=store, policy=policy,
        selected_aliases=selected_aliases,
        include_extracted_metadata_for_non_body=include_extracted_metadata_for_non_body,
    )
    files = tuple(f for f, _raw, _surf in items)
    total_bytes = sum(f.byte_length for f in files)
    temp = NativeMaterializationWitness(
        schema_version=NATIVE_MATERIALIZATION_WITNESS_SCHEMA_V1, graph_id=manifest.graph_id,
        publication_bundle_id=bundle.bundle_id, snapshot_manifest_id=manifest.manifest_id,
        graph_candidate_id=bundle.candidate_id, policy_digest=policy.policy_digest(),
        snapshot_vector=tuple((b, int(r), s) for b, r, s in manifest.snapshot_vector),
        selected_aliases=tuple(str(a) for a in selected_aliases),
        include_extracted_metadata_for_non_body=bool(include_extracted_metadata_for_non_body),
        excluded_bindings=excluded_bindings, files=files, total_bytes=total_bytes,
        witness_digest="sha256:" + ("0" * 64),
    )
    digest = _compute_witness_digest(temp._payload_without_digest())
    return NativeMaterializationWitness(**{**temp.__dict__, "witness_digest": digest}).validate()


def verify_native_materialization_witness(
    view: MaterializedNativeView,
    witness: NativeMaterializationWitness | None = None,
    *,
    manifest: PortableSnapshotManifest | None = None,
    bundle: PublicationBundle | None = None,
    store: ArtifactStore | None = None,
    policy: BodyProjectionPolicy | None = None,
    selected_aliases: Sequence[str] | None = None,
    include_extracted_metadata_for_non_body: bool = True,
) -> tuple[NativeMaterializationWitness, int, int]:
    """Verify a MaterializedNativeView and its witness against manifest, bundle, store, policy, and disk bytes."""
    t0 = time.perf_counter_ns()
    eff_witness = witness if witness is not None else view.materialization_witness
    if eff_witness is None:
        raise ValueError("native_witness_missing")
    eff_witness.validate()
    if manifest is None or bundle is None or store is None or policy is None:
        raise ValueError("native_witness_incomplete_inputs")
    if selected_aliases is None:
        raise ValueError("native_witness_aliases_required")
    expected = build_native_materialization_witness(
        manifest=manifest, bundle=bundle, store=store, policy=policy,
        selected_aliases=tuple(selected_aliases),
        include_extracted_metadata_for_non_body=include_extracted_metadata_for_non_body,
    )
    if eff_witness.to_dict() != expected.to_dict():
        raise ValueError("native_witness_mismatch")
    if not view.view_root.exists() or not view.view_root.is_dir() or view.view_root.is_symlink():
        raise ValueError("native_view_root_invalid")
    if (
        tuple(view.selected_relative_paths) != tuple(f.view_relative_path for f in expected.files)
        or dict(view.excluded_bindings) != dict(expected.excluded_bindings)
        or dict(view.path_to_binding)
        != {f.view_relative_path: (f.binding_id, f.source_relative_path) for f in expected.files}
        or dict(view.path_to_surface)
        != {f.view_relative_path: MatchSurface(f.match_surface) for f in expected.files}
    ):
        raise ValueError("native_materialization_drift")
    disk_files: list[str] = []
    for path in sorted(view.view_root.rglob("*")):
        if path.is_symlink():
            raise ValueError("native_view_symlink_forbidden")
        if path.is_file():
            disk_files.append(path.relative_to(view.view_root).as_posix())
    if tuple(disk_files) != tuple(sorted(f.view_relative_path for f in expected.files)):
        raise ValueError("native_materialization_drift: unexpected unrecorded files")
    bytes_verified = 0
    for f in expected.files:
        raw_disk = (view.view_root / f.view_relative_path).read_bytes()
        bytes_verified += len(raw_disk)
        actual_sha = "sha256:" + hashlib.sha256(raw_disk).hexdigest()
        if len(raw_disk) != f.byte_length or actual_sha != f.content_sha256:
            raise ValueError("native_materialization_drift: digest drift")
    return expected, bytes_verified, time.perf_counter_ns() - t0


def materialize_native_search_view(
    view_root: Path,
    *,
    manifest: PortableSnapshotManifest,
    bundle: PublicationBundle,
    store: ArtifactStore,
    policy: BodyProjectionPolicy,
    selected_aliases: Sequence[str] = ("core", "companion", "feeds", "mailbox"),
    include_extracted_metadata_for_non_body: bool = True,
) -> MaterializedNativeView:
    """Materialize full-size authorized body files and approved extracted metadata into view_root."""
    if view_root.exists():
        shutil.rmtree(view_root)
    view_root.mkdir(parents=True, exist_ok=True)
    excluded_bindings, items = _expected_native_view_entries(
        manifest=manifest, bundle=bundle, store=store, policy=policy,
        selected_aliases=selected_aliases,
        include_extracted_metadata_for_non_body=include_extracted_metadata_for_non_body,
    )
    selected_rel_paths: list[str] = []
    path_to_binding: dict[str, tuple[str, str]] = {}
    path_to_surface: dict[str, MatchSurface] = {}
    for f, raw_bytes, surface in items:
        dest = view_root / f.view_relative_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw_bytes)
        selected_rel_paths.append(f.view_relative_path)
        path_to_binding[f.view_relative_path] = (f.binding_id, f.source_relative_path)
        path_to_surface[f.view_relative_path] = surface
    witness = build_native_materialization_witness(
        manifest=manifest, bundle=bundle, store=store, policy=policy,
        selected_aliases=selected_aliases,
        include_extracted_metadata_for_non_body=include_extracted_metadata_for_non_body,
    )
    return MaterializedNativeView(
        view_root=view_root, selected_relative_paths=tuple(selected_rel_paths),
        path_to_binding=path_to_binding, path_to_surface=path_to_surface,
        excluded_bindings=excluded_bindings, materialization_witness=witness,
    )


__all__ = [
    "MaterializedNativeView",
    "NATIVE_MATERIALIZATION_WITNESS_SCHEMA_V1",
    "NativeMaterializationWitness",
    "NativeMaterializedFileWitness",
    "build_native_materialization_witness",
    "materialize_native_search_view",
    "verify_native_materialization_witness",
]
