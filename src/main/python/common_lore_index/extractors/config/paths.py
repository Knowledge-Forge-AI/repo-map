"""Shared path and pointer helpers for static configuration extraction."""

from __future__ import annotations


def json_pointer(segments: tuple[str, ...] | list[str]) -> str:
    if not segments:
        return ""
    return "/" + "/".join(_escape_pointer_segment(segment) for segment in segments)


def _pointer_segments(pointer: str) -> tuple[str, ...]:
    if not pointer:
        return ()
    return tuple(
        segment.replace("~1", "/").replace("~0", "~")
        for segment in pointer.removeprefix("/").split("/")
    )


def _escape_pointer_segment(segment: str) -> str:
    return str(segment).replace("~", "~0").replace("/", "~1")
