"""Materialize policy-authorized body and extracted-metadata views from retained ArtifactStore (S3)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

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


@dataclass(frozen=True)
class MaterializedNativeView:
    """Materialized filesystem view for native git-grep search without projection size caps."""

    view_root: Path
    selected_relative_paths: tuple[str, ...]
    path_to_binding: Mapping[str, tuple[str, str]]
    path_to_surface: Mapping[str, MatchSurface]
    excluded_bindings: Mapping[str, str]


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
        if str(row.get("source_binding_id") or "") != binding_id:
            continue
        if str(row.get("path") or "") != source_relative_path:
            continue
        kind = str(row.get("kind") or "")
        source_id = str(row.get("source_id") or "")
        meta = row.get("metadata")
        meta_json = (
            json.dumps(meta, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            if isinstance(meta, Mapping)
            else "{}"
        )
        lines.append(f"{kind} {source_id} {meta_json}")
    return lines


def materialize_native_search_view(
    view_root: Path,
    *,
    manifest: PortableSnapshotManifest,
    bundle: PublicationBundle,
    store: ArtifactStore,
    policy: BodyProjectionPolicy,
    selected_aliases: Sequence[str],
    include_extracted_metadata_for_non_body: bool = True,
) -> MaterializedNativeView:
    """Materialize full-size authorized body files and approved extracted metadata into view_root."""
    if view_root.exists():
        shutil.rmtree(view_root)
    view_root.mkdir(parents=True, exist_ok=True)

    selected_alias_set = set(selected_aliases)
    bindings_by_id = {b.binding_id: b for b in manifest.bindings}
    selected_rel_paths: list[str] = []
    path_to_binding: dict[str, tuple[str, str]] = {}
    path_to_surface: dict[str, MatchSurface] = {}
    excluded_bindings: dict[str, str] = {}

    for binding in sorted(manifest.bindings, key=lambda item: item.binding_id):
        if binding.alias not in selected_alias_set:
            excluded_bindings[binding.binding_id] = ExclusionReason.BINDING_NOT_SELECTED.value
            continue
        b_reason = evaluate_binding_exclusion(policy, binding)
        if b_reason is not None:
            excluded_bindings[binding.binding_id] = b_reason.value

    sorted_entries = sorted(
        manifest.entries,
        key=lambda item: (item.binding_id, item.source_relative_path),
    )
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
            dest = view_root / rel_in_view
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw_bytes)
            selected_rel_paths.append(rel_in_view)
            path_to_binding[rel_in_view] = (entry.binding_id, entry.source_relative_path)
            path_to_surface[rel_in_view] = MatchSurface.CAPTURED_TEXT
        elif include_extracted_metadata_for_non_body and binding.alias in {"feeds", "mailbox"}:
            meta_lines = _render_extracted_metadata_lines(
                bundle,
                entry.binding_id,
                entry.source_relative_path,
            )
            if meta_lines:
                rel_in_view = (
                    f"{binding.alias}/.extracted-metadata/{entry.source_relative_path}.meta.txt"
                )
                dest = view_root / rel_in_view
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(("\n".join(meta_lines) + "\n").encode("utf-8"))
                selected_rel_paths.append(rel_in_view)
                path_to_binding[rel_in_view] = (entry.binding_id, entry.source_relative_path)
                path_to_surface[rel_in_view] = MatchSurface.STORED_METADATA

    return MaterializedNativeView(
        view_root=view_root,
        selected_relative_paths=tuple(selected_rel_paths),
        path_to_binding=path_to_binding,
        path_to_surface=path_to_surface,
        excluded_bindings=excluded_bindings,
    )


__all__ = [
    "MaterializedNativeView",
    "materialize_native_search_view",
]
