"""Neutral refresh, publication, and identity authority contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

RequestId = NewType("RequestId", str)
OperationId = NewType("OperationId", str)
JobId = NewType("JobId", str)
AttemptNumber = NewType("AttemptNumber", int)
GraphRunId = NewType("GraphRunId", int)
StageId = NewType("StageId", str)


class RefreshResult(StrEnum):
    """Closed semantic result vocabulary for one graph refresh."""

    SUCCESS = "success"
    FAILURE = "failure"


class PublicationResult(StrEnum):
    """Closed final-publication result independent of stage or job state."""

    NOT_PUBLISHED = "not_published"
    PUBLISHED = "published"
    COMMIT_UNKNOWN = "commit_unknown"


_GENERATION_SUFFIX = r"[A-Za-z0-9][A-Za-z0-9._-]{0,123}"
_GENERATION_PATTERNS = {
    "source_generation": re.compile(rf"sg1:{_GENERATION_SUFFIX}\Z"),
    "config_generation": re.compile(rf"cg1:{_GENERATION_SUFFIX}\Z"),
    "extractor_generation": re.compile(rf"eg1:{_GENERATION_SUFFIX}\Z"),
    "canonicalizer_generation": re.compile(rf"kg1:{_GENERATION_SUFFIX}\Z"),
}


@dataclass(frozen=True)
class PublicationGenerations:
    """Exact source/config/extractor/canonicalizer publication fence."""

    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str

    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        return tuple(_GENERATION_PATTERNS)

    def values(self) -> tuple[str, ...]:
        return tuple(getattr(self, field) for field in self.field_names())

    def validate(self) -> "PublicationGenerations":
        if any(
            not isinstance(value, str)
            or _GENERATION_PATTERNS[field].fullmatch(value) is None
            for field, value in zip(self.field_names(), self.values(), strict=True)
        ):
            raise ValueError("invalid publication generations")
        return self


__all__ = [
    "AttemptNumber",
    "GraphRunId",
    "JobId",
    "OperationId",
    "PublicationGenerations",
    "PublicationResult",
    "RefreshResult",
    "RequestId",
    "StageId",
]
