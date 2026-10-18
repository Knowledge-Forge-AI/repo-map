"""Opt-in navigation query contract, independent of legacy node pagination."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Exactly the producer/subject kinds supported by the direct locator role.
DOC_KINDS = ("doc.page", "doc.section", "doc.adr", "doc.skill")
CODE_KINDS = ("python.module", "python.class", "python.function", "python.method")
NODE_SCAN_LIMIT = 2000
EVIDENCE_SCAN_LIMIT = 10000
# Separate connection-local admission work, never selected-row processing caps.
ADMISSION_CHECK_LIMIT = 100000
ADMISSION_BYTE_LIMIT = 32 * 1024 * 1024
HINT_LIMIT = 3


@dataclass(frozen=True)
class NavigationSearchQuery:
    query: str
    scope: str = "all"
    grouping: str = "none"
    kind: str | None = None
    source_binding_id: str | None = None
    source_path_prefix: str | None = None
    limit: int = 20
    offset: int = 0
    member_limit: int = 5

    def validate(self) -> NavigationSearchQuery:
        if not isinstance(self.query, str) or not self.query.strip() or len(self.query.strip()) > 200:
            raise ValueError("query must contain 1 to 200 characters")
        if not isinstance(self.scope, str) or self.scope not in {"all", "code", "docs"}:
            raise ValueError("scope must be all, code, or docs")
        if not isinstance(self.grouping, str) or self.grouping not in {"none", "source_document"}:
            raise ValueError("grouping must be none or source_document")
        for name, value, maximum in (("limit", self.limit, 50), ("member_limit", self.member_limit, 20)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be between 1 and {maximum}")
        if type(self.offset) is not int or not 0 <= self.offset <= 10000:
            raise ValueError("offset must be between 0 and 10000")
        for name in ("kind", "source_binding_id", "source_path_prefix"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value or len(value) > 500
                                      or any(ord(char) < 32 for char in value)):
                raise ValueError(f"{name} must be a nonempty bounded string")
        if self.source_path_prefix is not None:
            if self.source_binding_id is None:
                raise ValueError("source_path_prefix requires source_binding_id")
            prefix = self.source_path_prefix.rstrip("/")
            if (not prefix or prefix.startswith(("/", "~")) or ":" in prefix
                    or any(part in {"", ".", ".."} for part in prefix.split("/"))):
                raise ValueError("source_path_prefix must be source-relative")
        return self


def unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, "nodes": [],
            "accepted_publication": None, "scan": {"complete": False, "nodes": 0, "evidence": 0}}
