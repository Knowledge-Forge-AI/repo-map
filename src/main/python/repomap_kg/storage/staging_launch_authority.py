"""Private direct-launch publication-attempt event contract."""

from __future__ import annotations

from dataclasses import dataclass

from repomap_kg.storage.authority import AttemptNumber, JobId
from repomap_kg.storage.publication import RunPublicationAttempt

_SCHEMA_VERSION = 1
_AUTHORITY_KIND = "direct_publication_attempt"
_EVENT_CATEGORY = "bound"
_EXECUTION_MODE = "direct"
_MAX_OFFSET_NS = 9_223_372_036_854_775_807
_PAYLOAD_FIELDS = {
    "schema_version",
    "authority_kind",
    "event_category",
    "execution_mode",
    "publication_identity",
    "publication_attempt",
    "monotonic_offset_ns",
}


@dataclass(frozen=True)
class DirectLaunchAuthorityEvent:
    """One acknowledged child-created direct publication attempt."""

    schema_version: int
    authority_kind: str
    event_category: str
    execution_mode: str
    publication_attempt: RunPublicationAttempt
    monotonic_offset_ns: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or not isinstance(self.authority_kind, str)
            or not isinstance(self.event_category, str)
            or not isinstance(self.execution_mode, str)
            or not isinstance(self.publication_attempt, RunPublicationAttempt)
        ):
            raise ValueError("direct launch authority event is invalid")
        try:
            self.publication_attempt.validate()
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("direct launch authority event is invalid") from error
        if (
            self.schema_version != _SCHEMA_VERSION
            or self.authority_kind != _AUTHORITY_KIND
            or self.event_category != _EVENT_CATEGORY
            or self.execution_mode != _EXECUTION_MODE
            or isinstance(self.monotonic_offset_ns, bool)
            or not isinstance(self.monotonic_offset_ns, int)
            or not 0 <= self.monotonic_offset_ns <= _MAX_OFFSET_NS
        ):
            raise ValueError("direct launch authority event is invalid")

    @classmethod
    def from_attempt(
        cls,
        attempt: RunPublicationAttempt,
        monotonic_offset_ns: int,
    ) -> "DirectLaunchAuthorityEvent":
        """Build the private event from the exact receipt attempt."""

        return cls(
            _SCHEMA_VERSION,
            _AUTHORITY_KIND,
            _EVENT_CATEGORY,
            _EXECUTION_MODE,
            attempt,
            monotonic_offset_ns,
        )

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "DirectLaunchAuthorityEvent":
        """Decode one strict private-channel payload."""

        try:
            if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
                raise ValueError
            schema_version = payload["schema_version"]
            authority_kind = payload["authority_kind"]
            event_category = payload["event_category"]
            execution_mode = payload["execution_mode"]
            publication_identity = payload["publication_identity"]
            publication_attempt = payload["publication_attempt"]
            monotonic_offset_ns = payload["monotonic_offset_ns"]
            if (
                isinstance(schema_version, bool)
                or not isinstance(schema_version, int)
                or not isinstance(authority_kind, str)
                or not isinstance(event_category, str)
                or not isinstance(execution_mode, str)
                or not isinstance(publication_identity, str)
                or isinstance(publication_attempt, bool)
                or not isinstance(publication_attempt, int)
                or isinstance(monotonic_offset_ns, bool)
                or not isinstance(monotonic_offset_ns, int)
            ):
                raise ValueError
            attempt = RunPublicationAttempt(
                JobId(publication_identity),
                AttemptNumber(publication_attempt),
            ).validate()
            return cls(
                schema_version,
                authority_kind,
                event_category,
                execution_mode,
                attempt,
                monotonic_offset_ns,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("direct launch authority event is invalid") from error

    def to_payload(self) -> dict[str, object]:
        """Return the strict private-channel field family."""

        return {
            "schema_version": self.schema_version,
            "authority_kind": self.authority_kind,
            "event_category": self.event_category,
            "execution_mode": self.execution_mode,
            "publication_identity": self.publication_attempt.job_id,
            "publication_attempt": self.publication_attempt.attempt,
            "monotonic_offset_ns": self.monotonic_offset_ns,
        }


__all__ = ["DirectLaunchAuthorityEvent"]
