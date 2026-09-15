"""TOML pointer-to-line helpers for structured config extraction."""

from __future__ import annotations

import tomllib
from typing import Any

from repomap_kg.extractors.config.generic_values import (
    _safe_value_summary,
    _stable_member_key,
)
from repomap_kg.extractors.config.paths import _pointer_segments


def _line_for_toml_pointer(content: str, pointer: str) -> int | None:
    pointer_segments = _pointer_segments(pointer)
    if not pointer_segments:
        return None
    sections = _toml_sections(content)
    for section in sections:
        if section.path == pointer_segments:
            return section.header_line
        member_segment = _toml_array_member_segment(section)
        for line_number, line in section.lines:
            key_segments = _toml_key_segments(line)
            if key_segments is None:
                continue
            if section.is_array:
                if member_segment is None:
                    continue
                candidate = (*section.path, member_segment, *key_segments)
            else:
                candidate = (*section.path, *key_segments)
            if candidate == pointer_segments:
                return line_number
    return None


class _TomlSection:
    def __init__(
        self,
        *,
        path: tuple[str, ...],
        header_line: int | None,
        is_array: bool,
        lines: tuple[tuple[int, str], ...],
    ) -> None:
        self.path = path
        self.header_line = header_line
        self.is_array = is_array
        self.lines = lines


def _toml_sections(content: str) -> tuple[_TomlSection, ...]:
    sections: list[_TomlSection] = []
    path: tuple[str, ...] = ()
    header_line: int | None = None
    is_array = False
    lines: list[tuple[int, str]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        header = _toml_table_header(line)
        if header is not None:
            sections.append(
                _TomlSection(
                    path=path,
                    header_line=header_line,
                    is_array=is_array,
                    lines=tuple(lines),
                )
            )
            path, is_array = header
            header_line = line_number
            lines = []
            continue
        lines.append((line_number, line))
    sections.append(
        _TomlSection(
            path=path,
            header_line=header_line,
            is_array=is_array,
            lines=tuple(lines),
        )
    )
    return tuple(sections)


def _toml_table_header(line: str) -> tuple[tuple[str, ...], bool] | None:
    stripped = line.strip()
    if stripped.startswith("[[") and stripped.endswith("]]"):
        return _toml_dotted_segments(stripped[2:-2]), True
    if stripped.startswith("[") and stripped.endswith("]"):
        return _toml_dotted_segments(stripped[1:-1]), False
    return None


def _toml_array_member_segment(section: _TomlSection) -> str | None:
    if not section.is_array:
        return None
    parsed = _parse_toml_section_lines(section.lines)
    if not isinstance(parsed, dict):
        return None
    stable_key = _stable_member_key(parsed)
    if stable_key is None:
        return None
    summary = _safe_value_summary(parsed[stable_key])
    if summary is None or isinstance(summary, bool):
        return None
    return str(summary)


def _parse_toml_section_lines(lines: tuple[tuple[int, str], ...]) -> dict[str, Any] | None:
    body = "\n".join(line for _line_number, line in lines)
    if not body.strip():
        return None
    try:
        parsed = tomllib.loads(body)
    except tomllib.TOMLDecodeError:
        return None
    return parsed


def _toml_key_segments(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key_text = stripped.split("=", 1)[0].strip()
    if not key_text:
        return None
    return _toml_dotted_segments(key_text)


def _toml_dotted_segments(value: str) -> tuple[str, ...]:
    return tuple(
        segment.strip().strip("\"'")
        for segment in value.split(".")
        if segment.strip()
    )
