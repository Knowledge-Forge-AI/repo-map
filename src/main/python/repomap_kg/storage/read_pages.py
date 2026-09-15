"""Bounded versioned read-result pages shared by public presentations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from repomap_kg.storage.errors import StorageSchemaError

__all__ = (
    "DEFAULT_PUBLIC_READ_LIMIT",
    "MAX_PUBLIC_READ_LIMIT",
    "PUBLIC_READ_SCHEMA_VERSION",
    "PublicReadPage",
    "format_public_read_page_footer",
    "public_read_page",
    "public_embedded_read_result_to_jsonable",
    "public_read_page_to_jsonable",
    "validate_public_read_window",
)

DEFAULT_PUBLIC_READ_LIMIT = 50
MAX_PUBLIC_READ_LIMIT = 200
PUBLIC_READ_SCHEMA_VERSION = 1

_RecordT = TypeVar("_RecordT")


@dataclass(frozen=True)
class PublicReadPage(Generic[_RecordT]):
    """One bounded page plus explicit continuation state."""

    items: tuple[_RecordT, ...]
    limit: int
    offset: int
    truncated: bool

    @property
    def next_offset(self) -> int | None:
        if not self.truncated:
            return None
        return self.offset + len(self.items)


def validate_public_read_window(limit: int, offset: int) -> tuple[int, int]:
    """Validate the shared CLI/MCP public-read window."""
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_PUBLIC_READ_LIMIT
    ):
        raise StorageSchemaError(
            f"limit must be between 1 and {MAX_PUBLIC_READ_LIMIT}"
        )
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise StorageSchemaError("offset must be a non-negative integer")
    return limit, offset


def public_read_page(
    records: Sequence[_RecordT],
    *,
    limit: int,
    offset: int,
) -> PublicReadPage[_RecordT]:
    """Build a page from a query result containing at most one lookahead row."""
    safe_limit, safe_offset = validate_public_read_window(limit, offset)
    return PublicReadPage(
        items=tuple(records[:safe_limit]),
        limit=safe_limit,
        offset=safe_offset,
        truncated=len(records) > safe_limit,
    )


def public_read_page_to_jsonable(
    page: PublicReadPage[_RecordT],
    *,
    result_kind: str,
    serialize_items: Callable[[Sequence[_RecordT]], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Project one public-read page into the version 1 JSON contract."""
    diagnostics = []
    if page.truncated:
        diagnostics.append(
            {
                "code": "result_truncated",
                "message": "additional results are available",
            }
        )
    return {
        "schema_version": PUBLIC_READ_SCHEMA_VERSION,
        "result_kind": result_kind,
        "items": serialize_items(page.items),
        "page": _public_read_page_metadata(page),
        "diagnostics": diagnostics,
    }


def public_embedded_read_result_to_jsonable(
    result: dict[str, Any],
    *,
    result_kind: str,
    collection_pages: Mapping[str, PublicReadPage[Any]],
) -> dict[str, Any]:
    """Project bounded embedded collections into the version 1 contract."""
    diagnostics = [
        {
            "code": "result_truncated",
            "collection": name,
            "message": "additional results are available",
        }
        for name, page in collection_pages.items()
        if page.truncated
    ]
    return {
        "schema_version": PUBLIC_READ_SCHEMA_VERSION,
        "result_kind": result_kind,
        "result": result,
        "collections": {
            name: _public_read_page_metadata(page)
            for name, page in collection_pages.items()
        },
        "diagnostics": diagnostics,
    }


def _public_read_page_metadata(page: PublicReadPage[Any]) -> dict[str, Any]:
    return {
        "limit": page.limit,
        "offset": page.offset,
        "returned": len(page.items),
        "truncated": page.truncated,
        "next_offset": page.next_offset,
    }


def format_public_read_page_footer(
    page: PublicReadPage[Any],
    *,
    collection: str | None = None,
) -> str:
    """Render page metadata for table output."""
    next_offset = "none" if page.next_offset is None else str(page.next_offset)
    truncated = str(page.truncated).lower()
    prefix = "page" if collection is None else f"{collection} page"
    return (
        f"{prefix}: offset={page.offset} returned={len(page.items)} "
        f"limit={page.limit} next_offset={next_offset} truncated={truncated}"
    )
