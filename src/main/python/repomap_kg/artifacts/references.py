"""Portable, content-addressed artifact references.

The reference deliberately keeps semantic identity separate from physical
placement.  A locator is an execution detail and is therefore not included in
``semantic_mapping`` or the public projection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Mapping, cast

from repomap_kg.storage.staging_family_contracts import PrivacyClassification


MAX_ARTIFACT_SIZE = (2**63) - 1
MAX_LOCATOR_LENGTH = 512
MAX_STORE_VERSION_LENGTH = 128
MAX_MEDIA_TYPE_LENGTH = 256
MAX_RECORD_FORMAT_LENGTH = 128

_DIGEST_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_TOKEN_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._+/-]*\Z")
_VERSION_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_WINDOWS_ABSOLUTE_RE = re.compile(r"\A[A-Za-z]:")
_LOCATOR_KINDS = frozenset({"filesystem", "object"})


def _require_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"invalid {field}")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError(f"invalid {field}")
    return value


def _validate_locator_value(kind: str, value: str) -> str:
    value = _require_text(value, "locator", MAX_LOCATOR_LENGTH)
    # Locators are store-relative POSIX names, never URI/URL or host paths.
    if (
        "\\" in value
        or value.startswith(("/", "~"))
        or _WINDOWS_ABSOLUTE_RE.match(value)
        or "://" in value
        or any(marker in value for marker in (":", "?", "#", "@", "%"))
    ):
        raise ValueError("invalid locator")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("invalid locator")
    # A bucket name is a physical object-store authority, not a portable key.
    # Namespaces such as ``tenant-neutral`` remain valid store-relative keys.
    if kind == "object" and parts[0].casefold() == "bucket":
        raise ValueError("invalid locator")
    if any(character.isspace() for character in value):
        raise ValueError("invalid locator")
    return value


def _validate_store_version(value: str | None) -> str | None:
    if value is None:
        return None
    value = _require_text(value, "store version", MAX_STORE_VERSION_LENGTH)
    if not _VERSION_RE.fullmatch(value):
        raise ValueError("invalid store version")
    return value


@dataclass(frozen=True, slots=True)
class ArtifactLocator:
    """A closed-kind, store-relative physical locator.

    ``value`` is deliberately not a URL and cannot contain an authority,
    credentials, query, fragment, or path traversal.  The optional version is
    an immutable store version used for stale-read detection; it is not a
    content identity.
    """

    kind: str
    value: str
    store_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in _LOCATOR_KINDS:
            raise ValueError("invalid locator kind")
        object.__setattr__(self, "value", _validate_locator_value(self.kind, self.value))
        object.__setattr__(self, "store_version", _validate_store_version(self.store_version))

    @property
    def path(self) -> str:
        """Compatibility alias for callers that call a locator a path/key."""

        return self.value

    @property
    def store_generation(self) -> str | None:
        """Alias used by callers that call immutable versions generations."""

        return self.store_version

    def to_mapping(self) -> dict[str, str]:
        result = {"kind": self.kind, "value": self.value}
        if self.store_version is not None:
            result["store_version"] = self.store_version
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ArtifactLocator":
        if not isinstance(value, Mapping):
            raise ValueError("invalid locator")
        allowed = {"kind", "value", "store_version"}
        if set(value) - allowed:
            raise ValueError("invalid locator")
        kind = value.get("kind")
        locator_value = value.get("value")
        store_version = value.get("store_version")
        if not isinstance(kind, str) or not isinstance(locator_value, str):
            raise ValueError("invalid locator")
        if store_version is not None and not isinstance(store_version, str):
            raise ValueError("invalid locator")
        return cls(
            kind,
            locator_value,
            store_version,
        )


def _privacy(value: object) -> PrivacyClassification:
    if isinstance(value, PrivacyClassification):
        return value
    if isinstance(value, str):
        try:
            return PrivacyClassification(value)
        except ValueError:
            pass
    raise ValueError("invalid privacy classification")


@dataclass(frozen=True, slots=True, eq=False)
class ArtifactReference:
    """Immutable bytes plus the metadata needed to retrieve those bytes."""

    content_digest: str
    size_bytes: int
    media_type: str
    record_format: str
    privacy: PrivacyClassification
    locator: ArtifactLocator

    def __post_init__(self) -> None:
        if not isinstance(self.content_digest, str) or not _DIGEST_RE.fullmatch(
            self.content_digest
        ):
            raise ValueError("invalid content digest")
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes < 0
            or self.size_bytes > MAX_ARTIFACT_SIZE
        ):
            raise ValueError("invalid artifact size")
        for value, field, maximum in (
            (self.media_type, "media type", MAX_MEDIA_TYPE_LENGTH),
            (self.record_format, "record format", MAX_RECORD_FORMAT_LENGTH),
        ):
            _require_text(value, field, maximum)
            if not _TOKEN_RE.fullmatch(value):
                raise ValueError(f"invalid {field}")
        object.__setattr__(self, "privacy", _privacy(self.privacy))
        if not isinstance(self.locator, ArtifactLocator):
            raise ValueError("invalid locator")

    @property
    def store_version(self) -> str | None:
        """The physical immutable-version token, when the store supplies one."""

        return self.locator.store_version

    @property
    def store_generation(self) -> str | None:
        """Alias for the optional physical store version."""

        return self.store_version

    def semantic_mapping(self) -> dict[str, object]:
        """Return the locator-independent semantic identity fields."""

        return {
            "content_digest": self.content_digest,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "record_format": self.record_format,
            "privacy": self.privacy.value,
        }

    def __eq__(self, other: object) -> bool:
        """Compare content semantics, never physical placement."""

        return isinstance(other, ArtifactReference) and self.semantic_mapping() == other.semantic_mapping()

    def __hash__(self) -> int:
        return hash(
            (
                self.content_digest,
                self.size_bytes,
                self.media_type,
                self.record_format,
                self.privacy,
            )
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ArtifactReference):
            return NotImplemented
        return (
            self.content_digest,
            self.size_bytes,
            self.media_type,
            self.record_format,
            self.privacy.value,
        ) < (
            other.content_digest,
            other.size_bytes,
            other.media_type,
            other.record_format,
            other.privacy.value,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return the private execution representation, including placement."""

        result = self.semantic_mapping()
        result["locator"] = self.locator.to_mapping()
        return result

    def to_public_mapping(self) -> dict[str, object]:
        """Return a public-safe representation with placement fully redacted."""

        return self.semantic_mapping()

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ArtifactReference":
        if not isinstance(value, Mapping):
            raise ValueError("invalid artifact reference")
        allowed = {
            "content_digest",
            "size_bytes",
            "media_type",
            "record_format",
            "privacy",
            "locator",
        }
        if set(value) - allowed or "locator" not in value:
            raise ValueError("invalid artifact reference")
        return cls(
            cast(str, value.get("content_digest")),
            cast(int, value.get("size_bytes")),
            cast(str, value.get("media_type")),
            cast(str, value.get("record_format")),
            _privacy(value.get("privacy")),
            ArtifactLocator.from_mapping(cast(Mapping[str, object], value["locator"])),
        )

    @classmethod
    def from_semantic_mapping(cls, value: Mapping[str, object]) -> "ArtifactReference":
        """Decode a locator-free reference from a portable manifest.

        A manifest intentionally carries no physical placement.  The neutral
        object locator is a deterministic placeholder that a concrete store
        may resolve by content digest; it is never included in semantic or
        public identity.
        """

        if not isinstance(value, Mapping):
            raise ValueError("invalid artifact reference")
        allowed = {"content_digest", "size_bytes", "media_type", "record_format", "privacy"}
        if set(value) != allowed:
            raise ValueError("invalid semantic artifact reference")
        digest = value.get("content_digest")
        if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
            raise ValueError("invalid content digest")
        return cls(
            digest,
            cast(int, value.get("size_bytes")),
            cast(str, value.get("media_type")),
            cast(str, value.get("record_format")),
            _privacy(value.get("privacy")),
            ArtifactLocator("object", f"tenant-neutral/{digest[7:]}", None),
        )

    def with_store_version(self, store_version: str | None) -> "ArtifactReference":
        """Return a copy carrying a different physical version token."""

        return replace(self, locator=replace(self.locator, store_version=store_version))

    def with_locator(self, locator: ArtifactLocator) -> "ArtifactReference":
        """Return a copy relocated to another authorized store."""

        return replace(self, locator=locator)


__all__ = [
    "ArtifactLocator",
    "ArtifactReference",
    "MAX_ARTIFACT_SIZE",
    "MAX_LOCATOR_LENGTH",
    "MAX_STORE_VERSION_LENGTH",
]
