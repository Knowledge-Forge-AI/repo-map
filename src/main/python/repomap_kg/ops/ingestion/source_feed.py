"""Feed-source acquisition and artifact helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import tomllib
from typing import Any
import urllib.error
import urllib.request

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion.acquisition_contracts import NonPublicationResult
from repomap_kg.ops.ingestion.source_common import (
    SourcePolicyError,
    _artifact_filename,
    _content_type,
    _header_mapping,
    _mapping,
    _optional_bool,
    _optional_text,
    _positive_int_or_default,
    _required_positive_int,
    _required_text,
    _safe_url_summary,
    _secret_key_paths,
    _validate_disallowed_flags,
    _validate_method,
    _validate_policy_status,
    _validate_source_id,
    _validate_source_type,
    _validate_url,
)


EXTRACTOR = "source-ingestion"
EXTRACTOR_VERSION = "0.1.0"


class SourceAcquisitionError(ValueError):
    """Raised when configured source acquisition fails safely."""


@dataclass(frozen=True)
class FeedSourceConfig:
    source_id: str
    source_type: str
    display_name: str | None
    policy_status: str
    preferred_method: str | None
    rate_limit: str | None
    timeout_seconds: int
    max_artifact_bytes: int
    max_items_per_run: int
    robots_policy: str | None
    terms_policy: str | None
    requires_manual_review: bool
    url: str
    method: str
    user_agent: str | None
    redacted_config_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeedFetchResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


@dataclass(frozen=True)
class FeedArtifact:
    source_id: str
    source_type: str
    source_run_id: str
    artifact_id: str
    path: Path
    relative_path: str
    byte_length: int
    sha256: str
    acquired_at: str
    http_status: int
    content_type: str | None
    policy_status: str
    configured_url_summary: str


@dataclass(frozen=True)
class FeedIngestionSummary:
    source_id: str
    source_type: str
    policy_status: str
    source_run_id: str
    artifact_path: str
    artifact_sha256: str
    artifact_bytes: int
    observations: int
    feed_observations: int
    raw_observations: tuple[RawObservation, ...]
    publication: NonPublicationResult

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "policy_status": self.policy_status,
            "source_run_id": self.source_run_id,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "artifact_bytes": self.artifact_bytes,
            "observations": self.observations,
            "feed_observations": self.feed_observations,
            "publication": self.publication.to_jsonable(),
        }


FetchFeed = Callable[[FeedSourceConfig], FeedFetchResponse]
Clock = Callable[[], datetime]


def load_feed_source_config(path: Path | str) -> FeedSourceConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, Mapping):
        raise SourcePolicyError("source config must be a TOML object")
    source = _mapping(payload, "source")
    policy = _mapping(payload, "policy")
    acquisition = _mapping(payload, "acquisition")

    source_id = _required_text(source, "id", "source.id")
    source_type = _required_text(source, "type", "source.type")
    display_name = _optional_text(source, "display_name")
    policy_status = _required_text(policy, "status", "policy.status")
    timeout_seconds = _required_positive_int(
        policy,
        "timeout_seconds",
        "policy.timeout_seconds",
    )
    max_artifact_bytes = _required_positive_int(
        policy,
        "max_artifact_bytes",
        "policy.max_artifact_bytes",
    )
    max_items_per_run = _positive_int_or_default(
        policy.get("max_items_per_run"),
        "policy.max_items_per_run",
        default=100,
    )
    url = _required_text(acquisition, "url", "acquisition.url")
    method = _optional_text(acquisition, "method") or "GET"
    user_agent = _optional_text(acquisition, "user_agent")
    requires_manual_review = _optional_bool(
        policy.get("requires_manual_review"),
        "policy.requires_manual_review",
        default=False,
    )

    _validate_source_id(source_id)
    _validate_source_type(source_type)
    _validate_policy_status(policy_status)
    _validate_url(url)
    _validate_method(method)
    _validate_disallowed_flags(payload)
    if requires_manual_review:
        raise SourcePolicyError("source requires manual review before acquisition")

    return FeedSourceConfig(
        source_id=source_id,
        source_type=source_type,
        display_name=display_name,
        policy_status=policy_status,
        preferred_method=_optional_text(policy, "preferred_method"),
        rate_limit=_optional_text(policy, "rate_limit"),
        timeout_seconds=timeout_seconds,
        max_artifact_bytes=max_artifact_bytes,
        max_items_per_run=max_items_per_run,
        robots_policy=_optional_text(policy, "robots_policy"),
        terms_policy=_optional_text(policy, "terms_policy"),
        requires_manual_review=requires_manual_review,
        url=url,
        method=method.upper(),
        user_agent=user_agent,
        redacted_config_keys=tuple(_secret_key_paths(payload)),
    )


def fetch_feed_source(
    config: FeedSourceConfig,
    *,
    opener: Any | None = None,
) -> FeedFetchResponse:
    opener = opener or urllib.request.build_opener(_NoRedirectHandler())
    headers = {}
    if config.user_agent:
        headers["User-Agent"] = config.user_agent
    request = urllib.request.Request(
        config.url,
        headers=headers,
        method=config.method,
    )
    try:
        response = opener.open(request, timeout=config.timeout_seconds)
    except urllib.error.HTTPError as error:
        body = error.read(config.max_artifact_bytes + 1)
        return FeedFetchResponse(
            status=error.code,
            headers=_header_mapping(error.headers),
            body=body,
        )
    except urllib.error.URLError as error:
        raise SourceAcquisitionError(
            f"feed acquisition failed: {error.reason}"
        ) from error
    body = response.read(config.max_artifact_bytes + 1)
    return FeedFetchResponse(
        status=int(getattr(response, "status", response.getcode())),
        headers=_header_mapping(getattr(response, "headers", {})),
        body=body,
    )


def retain_feed_artifact(
    config: FeedSourceConfig,
    response: FeedFetchResponse,
    *,
    root_path: Path,
    artifact_dir: Path | None,
    clock: Clock,
) -> FeedArtifact:
    root = root_path.resolve()
    base_dir = (
        artifact_dir.resolve()
        if artifact_dir is not None
        else root / ".repomap" / "source-artifacts"
    )
    try:
        base_dir.relative_to(root)
    except ValueError as error:
        raise SourcePolicyError("artifact_dir must be inside root_path") from error
    now = clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    source_run_id = now.strftime("%Y%m%dT%H%M%SZ")
    acquired_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    sha256 = hashlib.sha256(response.body).hexdigest()
    artifact_id = sha256[:16]
    target_dir = base_dir / config.source_id / source_run_id
    target_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = target_dir / _artifact_filename(config.source_type)
    artifact_path.write_bytes(response.body)
    return FeedArtifact(
        source_id=config.source_id,
        source_type=config.source_type,
        source_run_id=source_run_id,
        artifact_id=artifact_id,
        path=artifact_path,
        relative_path=artifact_path.relative_to(root).as_posix(),
        byte_length=len(response.body),
        sha256=sha256,
        acquired_at=acquired_at,
        http_status=response.status,
        content_type=_content_type(response.headers),
        policy_status=config.policy_status,
        configured_url_summary=_safe_url_summary(config.url),
    )


def _validate_fetch_response(
    config: FeedSourceConfig,
    response: FeedFetchResponse,
) -> None:
    if 300 <= response.status < 400:
        raise SourceAcquisitionError("feed acquisition redirect responses are not followed")
    if response.status < 200 or response.status >= 300:
        raise SourceAcquisitionError(
            f"feed acquisition failed with HTTP status {response.status}"
        )
    if len(response.body) > config.max_artifact_bytes:
        raise SourceAcquisitionError("feed artifact exceeds max_artifact_bytes")


def _validate_item_limit(
    config: FeedSourceConfig,
    observations: Sequence[RawObservation],
) -> None:
    item_count = sum(1 for observation in observations if observation.kind == "feed.item")
    if item_count > config.max_items_per_run:
        raise SourcePolicyError("feed item count exceeds max_items_per_run")


def _artifact_file_observation(artifact: FeedArtifact) -> RawObservation:
    language = "json" if artifact.source_type == "feed.json" else "xml"
    return RawObservation(
        kind="file",
        source_id=artifact.relative_path,
        path=artifact.relative_path,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=EXTRACTOR_VERSION,
        metadata={
            "language": language,
            "role": "source",
            "source_artifact_role": "source-artifact",
            "content_hash": artifact.sha256,
            "generated": False,
            "executable": False,
            **_artifact_metadata(artifact),
        },
    )


def _annotate_observations(
    observations: Sequence[RawObservation],
    config: FeedSourceConfig,
    artifact: FeedArtifact,
) -> tuple[RawObservation, ...]:
    metadata = _artifact_metadata(artifact)
    metadata.update(
        {
            "source_display_name": config.display_name,
            "source_rate_limit": config.rate_limit,
            "source_preferred_method": config.preferred_method,
            "source_max_items_per_run": config.max_items_per_run,
            "config_redacted_keys": list(config.redacted_config_keys),
        }
    )
    return tuple(
        replace(
            observation,
            metadata={**dict(observation.metadata), **metadata},
        )
        for observation in observations
    )


def _artifact_metadata(artifact: FeedArtifact) -> dict[str, Any]:
    return {
        "source_id_configured": artifact.source_id,
        "source_type": artifact.source_type,
        "source_policy_status": artifact.policy_status,
        "source_run_id": artifact.source_run_id,
        "source_artifact_id": artifact.artifact_id,
        "source_artifact_path": artifact.relative_path,
        "source_artifact_sha256": artifact.sha256,
        "source_artifact_bytes": artifact.byte_length,
        "source_acquired_at": artifact.acquired_at,
        "acquisition_method": "GET",
        "acquisition_http_status": artifact.http_status,
        "acquisition_content_type": artifact.content_type,
        "acquisition_url_summary": artifact.configured_url_summary,
        "artifact_retention_policy": "local-artifact",
    }


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None
