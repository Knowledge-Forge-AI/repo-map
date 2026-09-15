"""Markdown heading, anchor, and frontmatter parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SECRET_PRONE_FRONTMATTER_KEYS = frozenset(
    ("token", "secret", "password", "api_key", "credential")
)
HEADING_PATTERN = re.compile(r"^(?P<indent> {0,3})(?P<marks>#{1,6})(?:\s+|$)(?P<text>.*)$")
FENCE_PATTERN = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)$")


@dataclass(frozen=True)
class HeadingInfo:
    line_number: int
    level: int
    text: str
    anchor: str
    base_anchor: str
    duplicate_index: int
    parent_anchor: str | None


@dataclass(frozen=True)
class FrontmatterInfo:
    start_line: int
    end_line: int
    keys: tuple[str, ...]
    values: dict[str, Any]
    parse_status: str
    redacted_keys: tuple[str, ...]
    malformed_reason: str | None = None

def markdown_anchors_for_content(content: str) -> set[str]:
    return {heading.anchor for heading in parse_markdown_headings(content)}


def markdown_anchor(text: str) -> str:
    cleaned = text.strip()
    for marker in ("`", "*", "_", "[", "]", "(", ")"):
        cleaned = cleaned.replace(marker, "")
    cleaned = cleaned.lower()
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"[^a-z0-9_-]", "", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or "section"


def parse_markdown_headings(content: str) -> tuple[HeadingInfo, ...]:
    frontmatter = parse_frontmatter(content)
    skip_until = frontmatter.end_line if frontmatter is not None else 0
    headings: list[HeadingInfo] = []
    anchor_counts: dict[str, int] = {}
    section_stack: dict[int, str] = {}
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
        match = HEADING_PATTERN.match(line)
        if match is None:
            continue
        raw_text = _strip_closing_heading_marks(match.group("text"))
        level = len(match.group("marks"))
        base_anchor = markdown_anchor(raw_text)
        duplicate_index = anchor_counts.get(base_anchor, 0)
        anchor_counts[base_anchor] = duplicate_index + 1
        anchor = base_anchor if duplicate_index == 0 else f"{base_anchor}-{duplicate_index}"
        parent_anchor = _nearest_parent_anchor(section_stack, level)
        section_stack[level] = anchor
        for stale_level in [item for item in section_stack if item > level]:
            del section_stack[stale_level]
        headings.append(
            HeadingInfo(
                line_number=line_number,
                level=level,
                text=raw_text,
                anchor=anchor,
                base_anchor=base_anchor,
                duplicate_index=duplicate_index,
                parent_anchor=parent_anchor,
            )
        )
    return tuple(headings)


def parse_frontmatter(content: str) -> FrontmatterInfo | None:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end_line = None
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            end_line = index
            break
    if end_line is None:
        return FrontmatterInfo(
            start_line=1,
            end_line=len(lines),
            keys=(),
            values={},
            parse_status="malformed",
            redacted_keys=(),
            malformed_reason="missing-closing-delimiter",
        )
    values: dict[str, Any] = {}
    redacted: list[str] = []
    parse_status = "parsed"
    current_list_key: str | None = None
    for line in lines[1 : end_line - 1]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list_key is not None:
            existing = values.setdefault(current_list_key, [])
            if isinstance(existing, list):
                existing.append(stripped[2:].strip())
            continue
        if ":" not in stripped:
            parse_status = "partial"
            current_list_key = None
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        current_list_key = key if raw_value == "" else None
        if _is_secret_prone_frontmatter_key(key):
            values[key] = "<redacted>"
            redacted.append(key)
            continue
        if raw_value == "":
            values[key] = []
        else:
            values[key] = _parse_frontmatter_scalar(raw_value)
    return FrontmatterInfo(
        start_line=1,
        end_line=end_line,
        keys=tuple(sorted(values)),
        values=values,
        parse_status=parse_status,
        redacted_keys=tuple(sorted(redacted)),
    )


def _strip_closing_heading_marks(text: str) -> str:
    return re.sub(r"\s+#+\s*$", "", text).strip()


def _nearest_parent_anchor(section_stack: dict[int, str], level: int) -> str | None:
    lower_levels = [item for item in section_stack if item < level]
    if not lower_levels:
        return None
    return section_stack[max(lower_levels)]


def _parse_frontmatter_scalar(raw_value: str) -> Any:
    stripped = raw_value.strip()
    if (
        len(stripped) >= 2
        and stripped[0] == stripped[-1]
        and stripped[0] in ("'", '"')
    ):
        return stripped[1:-1]
    if stripped.lower() == "true":
        return True
    if stripped.lower() == "false":
        return False
    return stripped


def _is_secret_prone_frontmatter_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SECRET_PRONE_FRONTMATTER_KEYS)
