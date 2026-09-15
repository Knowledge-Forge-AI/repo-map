"""Static Markdown documentation raw observation extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from repomap_kg import __version__
from repomap_kg.graph.keys import (
    doc_adr_key,
    doc_page_key,
    doc_section_key,
    doc_skill_key,
    external_url_key,
    file_key,
    dynamic_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.documents.markdown_structure import (
    FENCE_PATTERN,
    FrontmatterInfo,
    HEADING_PATTERN,
    HeadingInfo,
    _nearest_parent_anchor,
    _strip_closing_heading_marks,
    markdown_anchor,
    markdown_anchors_for_content,
    parse_frontmatter,
    parse_markdown_headings,
)


EXTRACTOR_NAME = "repo-markdown"
INLINE_LINK_PATTERN = re.compile(r"(?P<image>!?)\[(?P<text>[^\]\n]+)\]\((?P<target>[^)\n]+)\)")
REFERENCE_LINK_PATTERN = re.compile(r"(?<!!)\[(?P<text>[^\]\n]+)\]\[(?P<id>[^\]\n]*)\]")
LINK_DEFINITION_PATTERN = re.compile(r"^ {0,3}\[(?P<id>[^\]]+)\]:\s*(?P<target>\S+)")
AUTOLINK_PATTERN = re.compile(r"<(?P<target>(?:https?://|mailto:)[^>\s]+)>")
ADR_FILENAME_PATTERN = re.compile(r"(?P<number>\d{4})-(?P<slug>.+)\.md$")


@dataclass(frozen=True)
class LinkResolution:
    target: str
    resolved_target_kind: str
    resolved_path: str | None = None
    resolved_anchor: str | None = None
    resolution_reason: str | None = None



def extract_markdown_file_observations(
    relative_path: str,
    content: str,
    *,
    repository_paths: set[str] | frozenset[str] | None = None,
    markdown_anchors: dict[str, set[str] | frozenset[str]] | None = None,
    content_hash: str | None = None,
    generated: bool | None = None,
) -> tuple[RawObservation, ...]:
    repository_paths = set(repository_paths or {relative_path})
    markdown_anchors = {
        path: set(anchors)
        for path, anchors in (markdown_anchors or {}).items()
    }
    frontmatter = parse_frontmatter(content)
    headings = parse_markdown_headings(content)
    title = next((heading.text for heading in headings if heading.level == 1), None)
    observations: list[RawObservation] = [
        _document_observation(
            relative_path,
            title=title,
            frontmatter_present=frontmatter is not None,
            content_hash=content_hash,
            generated=generated,
        )
    ]

    if frontmatter is not None:
        observations.append(_frontmatter_observation(relative_path, frontmatter))

    observations.extend(
        _line_structural_observations(
            relative_path,
            content,
            repository_paths=repository_paths,
            markdown_anchors=markdown_anchors,
        )
    )

    adr = _adr_metadata_observation(relative_path, content, frontmatter)
    if adr is not None:
        observations.append(adr)
    skill = _skill_metadata_observation(relative_path, frontmatter)
    if skill is not None:
        observations.append(skill)
    return tuple(observations)

def resolve_markdown_link_target(
    source_path: str,
    raw_target: str,
    *,
    repository_paths: set[str] | frozenset[str],
    markdown_anchors: dict[str, set[str] | frozenset[str]],
) -> LinkResolution:
    target = _strip_link_title(raw_target.strip())
    if not target:
        return LinkResolution(
            target=unknown_key("external.url", "malformed-markdown-link"),
            resolved_target_kind="unknown",
            resolution_reason="empty-target",
        )
    if "{{" in target or "}}" in target or "${" in target:
        return LinkResolution(
            target=dynamic_key("external.url", "markdown-link-template"),
            resolved_target_kind="dynamic",
            resolution_reason="markdown-link-template",
        )
    if _has_malformed_percent_escape(target):
        return LinkResolution(
            target=unknown_key("external.url", "malformed-markdown-link"),
            resolved_target_kind="unknown",
            resolution_reason="malformed-percent-escape",
        )
    if target.startswith(("http://", "https://", "mailto:")):
        normalized = _normalize_external_url(target)
        return LinkResolution(
            target=external_url_key(normalized),
            resolved_target_kind="external.url",
        )

    path_part, anchor_part = _split_link_fragment(target)
    if path_part == "":
        resolved_path = source_path
    else:
        decoded_path = unquote(path_part)
        resolved_path = _resolve_repo_relative_path(source_path, decoded_path)
    if resolved_path is None:
        return LinkResolution(
            target=unknown_key("file", "repo-escaping-markdown-link"),
            resolved_target_kind="unknown",
            resolution_reason="repo-escaping-markdown-link",
        )

    if anchor_part is not None:
        anchor = markdown_anchor(unquote(anchor_part))
        if resolved_path in repository_paths and anchor in set(
            markdown_anchors.get(resolved_path, ())
        ):
            return LinkResolution(
                target=doc_section_key(resolved_path, anchor),
                resolved_target_kind="doc.section",
                resolved_path=resolved_path,
                resolved_anchor=anchor,
            )
        return LinkResolution(
            target=unknown_key("doc.section", "missing-anchor"),
            resolved_target_kind="unknown",
            resolved_path=resolved_path,
            resolved_anchor=anchor,
            resolution_reason="missing-anchor",
        )

    if resolved_path.endswith(".md"):
        if resolved_path in repository_paths:
            return LinkResolution(
                target=doc_page_key(resolved_path),
                resolved_target_kind="doc.page",
                resolved_path=resolved_path,
            )
        return LinkResolution(
            target=unknown_key("doc.page", "missing-markdown-link-target"),
            resolved_target_kind="unknown",
            resolved_path=resolved_path,
            resolution_reason="missing-markdown-link-target",
        )
    if resolved_path in repository_paths:
        return LinkResolution(
            target=file_key(resolved_path),
            resolved_target_kind="file",
            resolved_path=resolved_path,
        )
    return LinkResolution(
        target=unknown_key("file", "missing-markdown-link-target"),
        resolved_target_kind="unknown",
        resolved_path=resolved_path,
        resolution_reason="missing-markdown-link-target",
    )


def _line_structural_observations(
    relative_path: str,
    content: str,
    *,
    repository_paths: set[str],
    markdown_anchors: dict[str, set[str]],
) -> tuple[RawObservation, ...]:
    frontmatter = parse_frontmatter(content)
    skip_until = frontmatter.end_line if frontmatter is not None else 0
    definitions = _link_definitions(content, skip_until=skip_until)
    observations: list[RawObservation] = []
    anchor_counts: dict[str, int] = {}
    section_stack: dict[int, str] = {}
    current_anchor: str | None = None
    in_fence: tuple[str, int, int, str, str | None] | None = None
    link_ordinal = 0
    fence_ordinal = 0

    for line_number, line in enumerate(content.splitlines(), start=1):
        if line_number <= skip_until:
            continue
        fence_match = FENCE_PATTERN.match(line)
        if fence_match is not None:
            marker = fence_match.group("fence")
            info_string = fence_match.group("info").strip()
            if in_fence is None:
                in_fence = (
                    marker[0],
                    len(marker),
                    line_number,
                    info_string,
                    current_anchor,
                )
            elif marker[0] == in_fence[0] and len(marker) >= in_fence[1]:
                observations.append(
                    _code_fence_observation(
                        relative_path,
                        start_line=in_fence[2],
                        end_line=line_number,
                        marker=marker[0] * in_fence[1],
                        info_string=in_fence[3],
                        section_anchor=in_fence[4],
                        closed=True,
                        ordinal=fence_ordinal,
                    )
                )
                fence_ordinal += 1
                in_fence = None
            continue
        if in_fence is not None:
            continue

        heading_match = HEADING_PATTERN.match(line)
        if heading_match is not None:
            text = _strip_closing_heading_marks(heading_match.group("text"))
            level = len(heading_match.group("marks"))
            base_anchor = markdown_anchor(text)
            duplicate_index = anchor_counts.get(base_anchor, 0)
            anchor_counts[base_anchor] = duplicate_index + 1
            anchor = base_anchor if duplicate_index == 0 else f"{base_anchor}-{duplicate_index}"
            parent_anchor = _nearest_parent_anchor(section_stack, level)
            section_stack[level] = anchor
            for stale_level in [item for item in section_stack if item > level]:
                del section_stack[stale_level]
            current_anchor = anchor
            observations.append(
                _heading_observation(
                    relative_path,
                    line_number=line_number,
                    level=level,
                    text=text,
                    anchor=anchor,
                    base_anchor=base_anchor,
                    duplicate_index=duplicate_index,
                    parent_anchor=parent_anchor,
                )
            )
            continue

        links, link_ordinal = _link_observations_from_line(
            relative_path,
            line,
            line_number=line_number,
            current_anchor=current_anchor,
            repository_paths=repository_paths,
            markdown_anchors=markdown_anchors,
            definitions=definitions,
            starting_ordinal=link_ordinal,
        )
        observations.extend(links)

    if in_fence is not None:
        observations.append(
            _code_fence_observation(
                relative_path,
                start_line=in_fence[2],
                end_line=len(content.splitlines()) or in_fence[2],
                marker=in_fence[0] * in_fence[1],
                info_string=in_fence[3],
                section_anchor=in_fence[4],
                closed=False,
                ordinal=fence_ordinal,
            )
        )
    return tuple(observations)


def _document_observation(
    relative_path: str,
    *,
    title: str | None,
    frontmatter_present: bool,
    content_hash: str | None,
    generated: bool | None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "doc_path": relative_path,
        "doc_role": _document_role(relative_path),
        "frontmatter_present": frontmatter_present,
    }
    if title is not None:
        metadata["title"] = title
    if content_hash is not None:
        metadata["content_hash"] = content_hash
    if generated is not None:
        metadata["generated"] = generated
    return RawObservation(
        kind="markdown.document",
        source_id=f"{relative_path}#markdown-document",
        path=relative_path,
        target=doc_page_key(relative_path),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _frontmatter_observation(
    relative_path: str,
    frontmatter: FrontmatterInfo,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "keys": list(frontmatter.keys),
        "values": frontmatter.values,
        "parse_status": frontmatter.parse_status,
        "redacted_keys": list(frontmatter.redacted_keys),
    }
    if frontmatter.malformed_reason is not None:
        metadata["malformed_reason"] = frontmatter.malformed_reason
    return RawObservation(
        kind="markdown.frontmatter",
        source_id=f"{relative_path}#frontmatter",
        path=relative_path,
        start_line=frontmatter.start_line,
        end_line=frontmatter.end_line,
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _heading_observation(
    relative_path: str,
    *,
    line_number: int,
    level: int,
    text: str,
    anchor: str,
    base_anchor: str,
    duplicate_index: int,
    parent_anchor: str | None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "level": level,
        "text": text,
        "anchor": anchor,
        "base_anchor": base_anchor,
        "duplicate_index": duplicate_index,
        "page_key": doc_page_key(relative_path),
    }
    if parent_anchor is not None:
        metadata["parent_anchor"] = parent_anchor
    return RawObservation(
        kind="markdown.heading",
        source_id=f"{relative_path}#heading:{anchor}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=text,
        target=doc_section_key(relative_path, anchor),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _code_fence_observation(
    relative_path: str,
    *,
    start_line: int,
    end_line: int,
    marker: str,
    info_string: str,
    section_anchor: str | None,
    closed: bool,
    ordinal: int,
) -> RawObservation:
    language = info_string.split()[0] if info_string.split() else None
    metadata: dict[str, Any] = {
        "fence": marker,
        "fence_length": len(marker),
        "info_string": info_string,
        "closed": closed,
    }
    if language is not None:
        metadata["language"] = language
    if section_anchor is not None:
        metadata["section_anchor"] = section_anchor
    return RawObservation(
        kind="markdown.code_fence",
        source_id=f"{relative_path}#code-fence:{start_line}:{ordinal}",
        path=relative_path,
        start_line=start_line,
        end_line=end_line,
        name=language,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _link_observations_from_line(
    relative_path: str,
    line: str,
    *,
    line_number: int,
    current_anchor: str | None,
    repository_paths: set[str],
    markdown_anchors: dict[str, set[str]],
    definitions: dict[str, str],
    starting_ordinal: int,
) -> tuple[tuple[RawObservation, ...], int]:
    observations: list[RawObservation] = []
    consumed_spans: list[tuple[int, int]] = []
    ordinal = starting_ordinal

    for match in INLINE_LINK_PATTERN.finditer(line):
        observations.append(
            _link_observation(
                relative_path,
                line_number=line_number,
                ordinal=ordinal,
                text=match.group("text"),
                raw_target=match.group("target"),
                syntax="inline",
                current_anchor=current_anchor,
                repository_paths=repository_paths,
                markdown_anchors=markdown_anchors,
                is_image=bool(match.group("image")),
            )
        )
        consumed_spans.append(match.span())
        ordinal += 1

    for match in AUTOLINK_PATTERN.finditer(line):
        if _span_consumed(match.span(), consumed_spans):
            continue
        raw_target = match.group("target")
        observations.append(
            _link_observation(
                relative_path,
                line_number=line_number,
                ordinal=ordinal,
                text=raw_target,
                raw_target=raw_target,
                syntax="autolink",
                current_anchor=current_anchor,
                repository_paths=repository_paths,
                markdown_anchors=markdown_anchors,
                is_image=False,
            )
        )
        consumed_spans.append(match.span())
        ordinal += 1

    for match in REFERENCE_LINK_PATTERN.finditer(line):
        if _span_consumed(match.span(), consumed_spans):
            continue
        text = match.group("text")
        reference_id = match.group("id") or text
        target = definitions.get(_normalize_reference_id(reference_id))
        if target is None:
            continue
        observations.append(
            _link_observation(
                relative_path,
                line_number=line_number,
                ordinal=ordinal,
                text=text,
                raw_target=target,
                syntax="reference",
                current_anchor=current_anchor,
                repository_paths=repository_paths,
                markdown_anchors=markdown_anchors,
                is_image=False,
                definition_id=reference_id,
            )
        )
        ordinal += 1

    return tuple(observations), ordinal


def _link_observation(
    relative_path: str,
    *,
    line_number: int,
    ordinal: int,
    text: str,
    raw_target: str,
    syntax: str,
    current_anchor: str | None,
    repository_paths: set[str],
    markdown_anchors: dict[str, set[str]],
    is_image: bool,
    definition_id: str | None = None,
) -> RawObservation:
    resolution = resolve_markdown_link_target(
        relative_path,
        raw_target,
        repository_paths=repository_paths,
        markdown_anchors=markdown_anchors,
    )
    metadata: dict[str, Any] = {
        "link_text": text,
        "raw_target": raw_target,
        "link_syntax": syntax,
        "resolved_target_kind": resolution.resolved_target_kind,
        "is_image": is_image,
    }
    if definition_id is not None:
        metadata["definition_id"] = definition_id
    if current_anchor is not None:
        metadata["source_anchor"] = current_anchor
        metadata["source_key"] = doc_section_key(relative_path, current_anchor)
    if resolution.resolved_path is not None:
        metadata["resolved_path"] = resolution.resolved_path
    if resolution.resolved_anchor is not None:
        metadata["resolved_anchor"] = resolution.resolved_anchor
    if resolution.resolution_reason is not None:
        metadata["resolution_reason"] = resolution.resolution_reason
    return RawObservation(
        kind="markdown.link",
        source_id=f"{relative_path}#link:{line_number}:{ordinal}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=text,
        target=resolution.target,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _adr_metadata_observation(
    relative_path: str,
    content: str,
    frontmatter: FrontmatterInfo | None,
) -> RawObservation | None:
    path = PurePosixPath(relative_path)
    if len(path.parts) < 3 or path.parts[0] != "docs" or path.parts[1] != "adr":
        return None
    match = ADR_FILENAME_PATTERN.match(path.name)
    if match is None:
        return None
    number = match.group("number")
    first_heading = next(
        (heading.text for heading in parse_markdown_headings(content) if heading.level == 1),
        None,
    )
    title = _adr_title_from_heading(first_heading) or match.group("slug").replace("-", " ")
    metadata: dict[str, Any] = {
        "adr_number": number,
        "title": title,
        "filename_slug": match.group("slug"),
        "metadata_source": "heading" if first_heading is not None else "filename",
    }
    frontmatter_values = frontmatter.values if frontmatter is not None else {}
    status = _frontmatter_text(frontmatter_values, "status") or _section_value(
        content, "Status"
    )
    date = _frontmatter_text(frontmatter_values, "date") or _section_value(content, "Date")
    if status is not None:
        metadata["status"] = status
    if date is not None:
        metadata["date"] = date
    return RawObservation(
        kind="markdown.adr_metadata",
        source_id=f"{relative_path}#adr-metadata",
        path=relative_path,
        name=number,
        target=doc_adr_key(number),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _skill_metadata_observation(
    relative_path: str,
    frontmatter: FrontmatterInfo | None,
) -> RawObservation | None:
    path = PurePosixPath(relative_path)
    if path.name != "SKILL.md" or "skills" not in path.parts:
        return None
    values = frontmatter.values if frontmatter is not None else {}
    skill_name = _frontmatter_text(values, "name") or path.parent.name
    metadata: dict[str, Any] = {
        "skill_name": skill_name,
        "skill_path": relative_path,
        "frontmatter_keys": list(frontmatter.keys if frontmatter is not None else ()),
        "metadata_source": "frontmatter" if frontmatter is not None else "path",
        "parse_status": frontmatter.parse_status if frontmatter is not None else "missing",
    }
    description = _frontmatter_text(values, "description")
    if description is not None:
        metadata["description"] = description
    return RawObservation(
        kind="markdown.skill_metadata",
        source_id=f"{relative_path}#skill-metadata",
        path=relative_path,
        name=skill_name,
        target=doc_skill_key(skill_name),
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _link_definitions(content: str, *, skip_until: int) -> dict[str, str]:
    definitions: dict[str, str] = {}
    in_fence: tuple[str, int] | None = None
    for line_number, line in enumerate(content.splitlines(), start=1):
        if line_number <= skip_until:
            continue
        fence_match = FENCE_PATTERN.match(line)
        if fence_match is not None:
            marker = fence_match.group("fence")
            if in_fence is None:
                in_fence = (marker[0], len(marker))
            elif marker[0] == in_fence[0] and len(marker) >= in_fence[1]:
                in_fence = None
            continue
        if in_fence is not None:
            continue
        match = LINK_DEFINITION_PATTERN.match(line)
        if match is not None:
            definitions[_normalize_reference_id(match.group("id"))] = match.group(
                "target"
            )
    return definitions


def _document_role(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    if path.name == "README.md":
        return "readme"
    if path.name == "AGENTS.md":
        return "agents"
    if len(path.parts) >= 2 and path.parts[0] == "docs" and path.parts[1] == "adr":
        return "adr"
    if len(path.parts) >= 2 and path.parts[0] == "docs" and path.parts[1] == "status":
        return "status"
    if path.name == "SKILL.md" and "skills" in path.parts:
        return "skill"
    return "markdown"


def _normalize_reference_id(reference_id: str) -> str:
    return " ".join(reference_id.strip().lower().split())


def _span_consumed(span: tuple[int, int], consumed_spans: list[tuple[int, int]]) -> bool:
    return any(span[0] < existing[1] and existing[0] < span[1] for existing in consumed_spans)


def _strip_link_title(target: str) -> str:
    if " " not in target:
        return target
    if target.startswith(("http://", "https://", "mailto:")):
        return target
    return target.split()[0]


def _has_malformed_percent_escape(text: str) -> bool:
    for match in re.finditer("%", text):
        escape = text[match.start() : match.start() + 3]
        if len(escape) != 3 or not re.fullmatch(r"%[0-9A-Fa-f]{2}", escape):
            return True
    return False


def _normalize_external_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme in ("http", "https"):
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                quote(unquote(parsed.path or ""), safe="/:@"),
                parsed.query,
                parsed.fragment,
            )
        )
    return url


def _split_link_fragment(target: str) -> tuple[str, str | None]:
    if "#" not in target:
        return target, None
    path_part, anchor = target.split("#", 1)
    return path_part, anchor


def _resolve_repo_relative_path(source_path: str, raw_path: str) -> str | None:
    base = PurePosixPath(source_path).parent
    path = PurePosixPath(raw_path)
    combined = path if not raw_path else base / path
    parts: list[str] = []
    for part in combined.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts) if parts else "."


def _adr_title_from_heading(heading: str | None) -> str | None:
    if heading is None:
        return None
    match = re.match(r"ADR\s+\d{4}:\s*(?P<title>.+)$", heading)
    if match is not None:
        return match.group("title")
    return heading


def _section_value(content: str, heading_text: str) -> str | None:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        match = HEADING_PATTERN.match(line)
        if match is None:
            continue
        if _strip_closing_heading_marks(match.group("text")).lower() != heading_text.lower():
            continue
        for following in lines[index + 1 :]:
            if HEADING_PATTERN.match(following):
                return None
            stripped = following.strip()
            if stripped:
                return stripped
    return None


def _frontmatter_text(values: dict[str, Any], key: str) -> str | None:
    value = values.get(key)
    if isinstance(value, str) and value.strip() and value != "<redacted>":
        return value
    return None
