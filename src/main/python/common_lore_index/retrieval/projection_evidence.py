"""Optional canonical evidence and node-evidence link joining for projected files (S1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from common_lore_index.artifacts.bundle import PublicationBundle


@dataclass(frozen=True)
class ProjectedEvidenceLink:
    """Optional evidence link joined from canonical_evidence and canonical_node_evidence."""

    evidence_key: str
    canonical_node_key: str | None
    link_kind: str | None
    evidence_kind: str
    binding_id: str
    source_relative_path: str
    start_line: int | None
    end_line: int | None
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_key": self.evidence_key,
            "canonical_node_key": self.canonical_node_key,
            "link_kind": self.link_kind,
            "evidence_kind": self.evidence_kind,
            "binding_id": self.binding_id,
            "source_relative_path": self.source_relative_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "confidence": self.confidence,
        }


def index_bundle_evidence(
    bundle: PublicationBundle,
) -> dict[tuple[str, str], tuple[ProjectedEvidenceLink, ...]]:
    """Index same-bundle evidence records by (binding_id, source_relative_path).

    Joins ``canonical_node_evidence`` (`canonical_key`, `evidence_key`,
    `link_kind`) with ``canonical_evidence`` (`evidence_key`, `evidence_kind`,
    `start_line`, `end_line`, `confidence`, `metadata_json`). Never manufactures
    links when `binding_id` or `source_relative_path` is absent or ambiguous.
    """
    node_links_by_evidence: dict[str, list[tuple[str, str]]] = {}
    for row in bundle.families.get("canonical_node_evidence", ()):
        ev_key = row.get("evidence_key")
        node_key = row.get("canonical_key")
        link_kind = row.get("link_kind")
        if (
            isinstance(ev_key, str)
            and ev_key
            and isinstance(node_key, str)
            and node_key
            and isinstance(link_kind, str)
            and link_kind
        ):
            node_links_by_evidence.setdefault(ev_key, []).append((node_key, link_kind))

    by_file: dict[tuple[str, str], list[ProjectedEvidenceLink]] = {}
    for row in bundle.families.get("canonical_evidence", ()):
        ev_key = row.get("evidence_key")
        ev_kind = row.get("raw_kind")
        confidence = row.get("confidence", "extracted")
        metadata = row.get("metadata_json")
        if not isinstance(ev_key, str) or not ev_key or not isinstance(ev_kind, str) or not ev_kind:
            continue
        if not isinstance(metadata, Mapping):
            continue
        binding_id = metadata.get("binding_id")
        rel_path = metadata.get("source_relative_path")
        if not isinstance(binding_id, str) or not binding_id or not isinstance(rel_path, str) or not rel_path:
            continue

        raw_start = row.get("start_line")
        raw_end = row.get("end_line")
        start_line = int(raw_start) if isinstance(raw_start, int) and not isinstance(raw_start, bool) else None
        end_line = int(raw_end) if isinstance(raw_end, int) and not isinstance(raw_end, bool) else None

        joined = node_links_by_evidence.get(ev_key)
        target_list = by_file.setdefault((binding_id, rel_path), [])
        if not joined:
            target_list.append(
                ProjectedEvidenceLink(
                    evidence_key=ev_key,
                    canonical_node_key=None,
                    link_kind=None,
                    evidence_kind=ev_kind,
                    binding_id=binding_id,
                    source_relative_path=rel_path,
                    start_line=start_line,
                    end_line=end_line,
                    confidence=str(confidence),
                )
            )
        else:
            for node_key, link_kind in sorted(joined):
                target_list.append(
                    ProjectedEvidenceLink(
                        evidence_key=ev_key,
                        canonical_node_key=node_key,
                        link_kind=link_kind,
                        evidence_kind=ev_kind,
                        binding_id=binding_id,
                        source_relative_path=rel_path,
                        start_line=start_line,
                        end_line=end_line,
                        confidence=str(confidence),
                    )
                )

    return {
        key: tuple(
            sorted(
                links,
                key=lambda item: (
                    item.start_line or 0,
                    item.end_line or 0,
                    item.evidence_key,
                    item.canonical_node_key or "",
                    item.link_kind or "",
                ),
            )
        )
        for key, links in sorted(by_file.items())
    }


def links_for_line_span(
    file_links: Sequence[ProjectedEvidenceLink],
    start_line: int,
    end_line: int,
) -> tuple[ProjectedEvidenceLink, ...]:
    """Return evidence links whose line span overlaps [start_line, end_line]."""
    matched: list[ProjectedEvidenceLink] = []
    for link in file_links:
        if link.start_line is None:
            continue
        link_end = link.end_line if link.end_line is not None else link.start_line
        if link.start_line <= end_line and link_end >= start_line:
            matched.append(link)
    return tuple(matched)
