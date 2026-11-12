"""Unchanged global captured-text projection with exact delegated-read accounting and raw capture.

The maintained ``build_captured_text_projection`` owns membership, order,
budgets and its own reads. This module only wraps the store in a closed
read-observation delegate, so projection behavior is unchanged. There is no
raw cache: excerpt bytes come from an explicit second complete-object read.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, field, replace
import hashlib
from typing import Any

from common_lore_index.artifacts._manifest_records import ManifestArtifact
from common_lore_index.artifacts._store_common import ArtifactErrorCode, ArtifactIntegrityError
from common_lore_index.retrieval.projection_build import CapturedTextProjection, build_captured_text_projection
from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy, evaluate_artifact_pre_open
from common_lore_index.retrieval.publication_binding import CorrespondenceRefusal, ProjectionInputs
from retrieval_public_text_admission import supplemental_body_reason
from retrieval_public_text_contracts import (
    PROJECTION_POLICY_INCOMPATIBLE, PROJECTION_SETUP_REFUSED, PublicTextRefusal,
)

MEASUREMENT_UNKNOWNS = (
    "verify_internal_reads", "open_stream_consumption_bytes", "failed_read_bytes", "internal_device_io",
)


@dataclass
class _PayloadCounter:
    attempts: int = 0
    returned: int = 0
    failed: int = 0
    metadata_payload_bytes: int = 0
    source_payload_bytes: int = 0
    non_bytes_returns: int = 0

    def to_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class _OpaqueCounter:
    attempts: int = 0
    returned: int = 0
    failed: int = 0
    true_results: int = 0
    false_results: int = 0

    def to_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


def _reference_digest(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    reference = args[0] if args else kwargs.get("reference")
    digest = getattr(reference, "content_digest", None)
    return digest if type(digest) is str else None


class ReadObservationStore:
    """Closed delegate: identical arguments, return values and exceptions; observation only."""

    def __init__(self, inner: Any, *, metadata_digests: Collection[str], scope: str) -> None:
        self._inner = inner
        self._metadata = frozenset(metadata_digests)
        self.scope = scope
        self._payload = {"read": _PayloadCounter(), "get": _PayloadCounter()}
        self._verify = _OpaqueCounter()
        self._open_stream = _OpaqueCounter()

    def __repr__(self) -> str:
        return f"ReadObservationStore(scope={self.scope!r})"

    def _payload_call(self, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        counter = self._payload[method]
        counter.attempts += 1
        call: Callable[..., Any] = getattr(self._inner, method)
        try:
            result = call(*args, **kwargs)
        except BaseException:
            counter.failed += 1
            raise
        counter.returned += 1
        if type(result) is bytes:
            if _reference_digest(args, kwargs) in self._metadata:
                counter.metadata_payload_bytes += len(result)
            else:
                counter.source_payload_bytes += len(result)
        else:
            counter.non_bytes_returns += 1
        return result

    def read(self, *args: Any, **kwargs: Any) -> Any:
        return self._payload_call("read", args, kwargs)

    def get(self, *args: Any, **kwargs: Any) -> Any:
        return self._payload_call("get", args, kwargs)

    def verify(self, *args: Any, **kwargs: Any) -> Any:
        self._verify.attempts += 1
        try:
            result = self._inner.verify(*args, **kwargs)
        except BaseException:
            self._verify.failed += 1
            raise
        self._verify.returned += 1
        if result is True:
            self._verify.true_results += 1
        elif result is False:
            self._verify.false_results += 1
        return result

    def open_stream(self, *args: Any, **kwargs: Any) -> Any:
        self._open_stream.attempts += 1
        try:
            stream = self._inner.open_stream(*args, **kwargs)
        except BaseException:
            self._open_stream.failed += 1
            raise
        self._open_stream.returned += 1
        return stream

    def put(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ArtifactIntegrityError("read observation store is read-only", code=ArtifactErrorCode.PERMISSION_DENIED)

    def delete(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ArtifactIntegrityError("read observation store is read-only", code=ArtifactErrorCode.PERMISSION_DENIED)

    def counters(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "read": self._payload["read"].to_dict(),
            "get": self._payload["get"].to_dict(),
            "verify": self._verify.to_dict(),
            "open_stream": self._open_stream.to_dict(),
            "unknown": list(MEASUREMENT_UNKNOWNS),
        }


def metadata_digests(inputs: ProjectionInputs) -> frozenset[str]:
    """The three metadata-reference digests; every other digest is source content."""
    refs = (inputs.manifest_reference, inputs.bundle_reference, inputs.receipt_reference)
    return frozenset(ref.content_digest for ref in refs if ref is not None)


def observed_inputs(inputs: ProjectionInputs, scope: str) -> tuple[ProjectionInputs, ReadObservationStore]:
    observer = ReadObservationStore(inputs.store, metadata_digests=metadata_digests(inputs), scope=scope)
    return replace(inputs, store=observer), observer


def preflight_projection_policy(inputs: ProjectionInputs, policy: BodyProjectionPolicy) -> int:
    """Refuse the whole pass if the maintained pre-open would open a supplementally denied body.

    Returns the number of manifest entries the maintained policy would open.
    """
    bindings = {binding.binding_id: binding for binding in inputs.manifest.bindings}
    openable = 0
    for entry in inputs.manifest.entries:
        binding = bindings.get(entry.binding_id)
        if binding is None:
            raise PublicTextRefusal(PROJECTION_SETUP_REFUSED)
        reason, source_format = evaluate_artifact_pre_open(policy, binding, entry)
        if reason is None and source_format is not None:
            if supplemental_body_reason(policy, entry.binding_id) is not None:
                raise PublicTextRefusal(PROJECTION_POLICY_INCOMPATIBLE)
            openable += 1
    return openable


@dataclass(frozen=True)
class ProjectionCapture:
    projection: CapturedTextProjection
    counters: dict[str, Any]
    authorized_openable_entries: int


def capture_projection(inputs: ProjectionInputs, policy: BodyProjectionPolicy) -> ProjectionCapture:
    """Run the unchanged global projection once through the observation delegate."""
    openable = preflight_projection_policy(inputs, policy)
    wrapped, observer = observed_inputs(inputs, "projection_pass")
    try:
        projection = build_captured_text_projection(wrapped, policy)
    except (ValueError, CorrespondenceRefusal, ArtifactIntegrityError) as error:
        raise PublicTextRefusal(PROJECTION_SETUP_REFUSED) from error
    return ProjectionCapture(projection, observer.counters(), openable)


@dataclass(frozen=True)
class VerifiedRawObject:
    """Independently verified complete artifact bytes; private and never in repr."""

    content_digest: str
    size_bytes: int
    _raw: bytes = field(repr=False, compare=False)

    @property
    def raw(self) -> bytes:
        return self._raw


@dataclass
class ExcerptReadLedger:
    attempts: int = 0
    integrity_refused: int = 0
    verified_objects: int = 0
    verified_object_bytes: int = 0
    selected_excerpt_bytes: int = 0

    def to_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


def read_verified_object(
    observer: ReadObservationStore, entry: ManifestArtifact, policy: BodyProjectionPolicy, ledger: ExcerptReadLedger,
) -> VerifiedRawObject | None:
    """Second complete-object read; type, length and SHA-256 are rechecked independently of the store."""
    ledger.attempts += 1
    reference = entry.reference
    try:
        raw = observer.read(reference.with_store_version(None), max_bytes=policy.max_input_artifact_bytes)
    except (ArtifactIntegrityError, OSError):
        ledger.integrity_refused += 1
        return None
    if (
        type(raw) is not bytes or len(raw) != reference.size_bytes
        or "sha256:" + hashlib.sha256(raw).hexdigest() != reference.content_digest
    ):
        ledger.integrity_refused += 1
        return None
    ledger.verified_objects += 1
    ledger.verified_object_bytes += len(raw)
    return VerifiedRawObject(reference.content_digest, len(raw), raw)
