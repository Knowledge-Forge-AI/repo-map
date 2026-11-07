"""Original journal anchors for offline raw-worker correspondence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re

from retrieval_semantic_pair_artifacts import JournalArtifact, refuse


COMPONENT_ROLES = (
    "admission", "declaration", "report", "request", "source_manifest",
    "sources_archive", "terminal",
)
COUNT_FIELDS = ("record_count", "embedding_count", "document_count", "query_count")
MEMBER_ROLES = {
    "declaration.json": "declaration", "report.json": "report",
    "source-manifest.json": "source_manifest", "sources.zip": "sources_archive",
    "terminal.json": "terminal",
}
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def object_map(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value


def digest_map(value: object, keys: Iterable[str] | None = None) -> dict[str, str]:
    source = object_map(value, "component_digest_map")
    if keys is not None and set(source) != set(keys):
        raise refuse("component_digest_fields")
    output = {}
    for key, digest in source.items():
        if type(digest) is not str or DIGEST_PATTERN.fullmatch(digest) is None:
            raise refuse("component_digest")
        output[key] = digest
    return output


@dataclass(frozen=True)
class ComponentAnchors:
    admission: str
    closure: tuple[tuple[str, str], ...]
    digests: tuple[tuple[str, str], ...]


def canonical_anchors(journal: JournalArtifact) -> ComponentAnchors:
    """Use recorded closure members, allowing a larger canonical source census."""
    component = digest_map(journal.report.get("component"), COMPONENT_ROLES)
    admission = journal.declaration.get("controller_admission_sha256")
    if admission != component["admission"]:
        raise refuse("component_admission_anchor")
    closure = digest_map(journal.declaration.get("component_source_closure"))
    if not closure or closure != digest_map(journal.declaration.get("source_closure")):
        raise refuse("component_source_anchor")
    sources = digest_map(journal.source_manifest.get("source_files"))
    for name, digest in closure.items():
        if "\\" in name or any(part in {"", ".", ".."} for part in name.split("/")):
            raise refuse("component_source_anchor")
        if sources.get("tools/" + name) != digest:
            raise refuse("component_source_anchor")
    inputs = digest_map(journal.source_manifest.get("input_files"))
    if inputs.get("admission.json") != admission or inputs.get("request.json") != component["request"]:
        raise refuse("component_input_anchor")
    return ComponentAnchors(component["admission"], tuple(sorted(closure.items())), tuple(sorted(component.items())))


def safe_subcode(error: Exception) -> str:
    value = getattr(error, "code", None)
    if type(value) is str and re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", value):
        return value
    return "component_validation"


__all__ = [
    "COMPONENT_ROLES", "COUNT_FIELDS", "MEMBER_ROLES", "ComponentAnchors",
    "canonical_anchors", "digest_map", "object_map", "safe_subcode",
]
