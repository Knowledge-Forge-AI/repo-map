"""Exact immutable external base validation for managed test images."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import stat
from pathlib import Path
from typing import Any, Iterable


SCRATCH_DIRECTORY_NAME = ".scratch"

_EXACT_IMMUTABLE_REFERENCE = re.compile(
    r"(?P<name>[^@\s]+)@(?P<digest>sha256:[0-9a-f]{64})\Z"
)
_EXACT_ENGINE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ARCHITECTURE_ALIASES = {
    "aarch64": "arm64",
    "amd64": "amd64",
    "arm64": "arm64",
    "x86_64": "amd64",
}


class TestImageError(RuntimeError):
    """A managed test-image authority or provenance check failed."""


def require_private_scratch_directory(path: Path) -> Path:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode):
        raise TestImageError("test-image lifecycle scratch is a symlink")
    if not stat.S_ISDIR(metadata.st_mode):
        raise TestImageError("test-image lifecycle scratch is not a directory")
    if metadata.st_uid != os.getuid():
        raise TestImageError("test-image lifecycle scratch ownership is unsafe")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise TestImageError("test-image lifecycle scratch mode is unsafe")
    return path


def repository_scratch_directory(repo_root: Path) -> Path:
    """Resolve repository-owned ignored scratch shared by every runner process.

    Host-stable lifecycle state must survive the runner's per-run temporary
    directory remapping without depending on a system-wide temporary directory.
    """
    root = Path(repo_root)
    if not root.is_dir():
        raise TestImageError("project root for repository scratch is unavailable")
    return require_private_scratch_directory(root / SCRATCH_DIRECTORY_NAME)


@dataclass(frozen=True)
class ImmutableImageAuthority:
    configured_reference: str
    repository: str
    digest: str
    canonical_reference: str
    optional_tag: str | None


@dataclass(frozen=True)
class BaseImageProvenance:
    reference: str
    repository: str
    digest: str
    canonical_reference: str
    optional_tag: str | None
    image_id: str
    repo_digests: tuple[str, ...]
    architecture: str
    image_architecture: str
    server_architecture: str
    canonical_image_architecture: str
    canonical_server_architecture: str
    pulled: bool


def parse_immutable_image_authority(reference: str) -> ImmutableImageAuthority:
    """Parse one exact repository digest without confusing a port for a tag."""

    match = _EXACT_IMMUTABLE_REFERENCE.fullmatch(str(reference))
    if match is None:
        raise TestImageError("configured base must be an exact repository digest")
    name = match.group("name")
    tag_separator = name.rfind(":")
    final_slash = name.rfind("/")
    optional_tag = None
    repository = name
    if tag_separator > final_slash:
        repository = name[:tag_separator]
        optional_tag = name[tag_separator + 1 :]
        if not repository or not optional_tag:
            raise TestImageError("configured base repository or tag is empty")
    if not repository:
        raise TestImageError("configured base repository is empty")
    digest = match.group("digest")
    return ImmutableImageAuthority(
        configured_reference=str(reference),
        repository=repository,
        digest=digest,
        canonical_reference=f"{repository}@{digest}",
        optional_tag=optional_tag,
    )


def configured_base_repository(reference: str) -> str:
    return parse_immutable_image_authority(reference).repository


def repo_digests_match_authority(
    authority: ImmutableImageAuthority,
    repo_digests: Iterable[str],
) -> bool:
    """Require one exact repository-and-digest match from valid Engine values."""

    parsed = tuple(
        parse_immutable_image_authority(str(item)) for item in repo_digests
    )
    return any(
        item.repository == authority.repository and item.digest == authority.digest
        for item in parsed
    )


def normalize_architecture_pair(
    image_architecture: str,
    server_architecture: str,
) -> tuple[str, str]:
    """Return closed canonical aliases or an identical lowercase exact token."""

    image = str(image_architecture)
    server = str(server_architecture)
    if (
        not image
        or not server
        or image != image.strip().lower()
        or server != server.strip().lower()
        or any(character.isspace() for character in image + server)
    ):
        raise TestImageError("configured base architecture is unsupported")
    if image == server:
        canonical = _ARCHITECTURE_ALIASES.get(image, image)
        return canonical, canonical
    if image in _ARCHITECTURE_ALIASES and server in _ARCHITECTURE_ALIASES:
        canonical_image = _ARCHITECTURE_ALIASES[image]
        canonical_server = _ARCHITECTURE_ALIASES[server]
        if canonical_image == canonical_server:
            return canonical_image, canonical_server
    raise TestImageError("configured base architecture does not match Docker server")


def read_exact_local_image(client: Any, reference: str) -> Any:
    """Read one exact Engine ID or immutable repository authority locally."""

    is_image_id = bool(_EXACT_ENGINE_ID.fullmatch(str(reference)))
    authority = None
    lookup_reference = str(reference)
    if not is_image_id:
        authority = parse_immutable_image_authority(reference)
        lookup_reference = authority.canonical_reference
    try:
        image = client.images.get(lookup_reference)
    except Exception as error:
        if error.__class__.__name__ in {"NotFound", "ImageNotFound"}:
            raise TestImageError(
                "configured exact base image is absent; pull-on-miss is disabled"
            ) from error
        raise
    image_id = str(image.id)
    if _EXACT_ENGINE_ID.fullmatch(image_id) is None:
        raise TestImageError("configured base Engine image ID is not exact")
    if is_image_id and image_id != reference:
        raise TestImageError("configured exact image ID failed local readback")
    if authority is not None and not repo_digests_match_authority(
        authority, tuple(image.attrs.get("RepoDigests") or ())
    ):
        raise TestImageError("configured base RepoDigest failed local readback")
    return image


def read_configured_base(
    client: Any,
    reference: str,
    *,
    allow_missing: bool,
) -> tuple[Any | None, BaseImageProvenance | None]:
    authority = parse_immutable_image_authority(reference)
    try:
        image = client.images.get(authority.canonical_reference)
    except Exception as error:
        if error.__class__.__name__ not in {"NotFound", "ImageNotFound"}:
            raise
        if allow_missing:
            return None, None
        raise TestImageError(
            "configured exact base image is absent after acquisition"
        ) from error
    image_id = str(image.id)
    if _EXACT_ENGINE_ID.fullmatch(image_id) is None:
        raise TestImageError("configured base Engine image ID is not exact")
    repo_digests = tuple(
        sorted(str(item) for item in image.attrs.get("RepoDigests") or ())
    )
    if not repo_digests_match_authority(authority, repo_digests):
        raise TestImageError("configured base RepoDigest failed Engine readback")
    server_architecture = str(client.info().get("Architecture") or "")
    image_architecture = str(image.attrs.get("Architecture") or "")
    canonical_image, canonical_server = normalize_architecture_pair(
        image_architecture,
        server_architecture,
    )
    return image, BaseImageProvenance(
        reference=authority.configured_reference,
        repository=authority.repository,
        digest=authority.digest,
        canonical_reference=authority.canonical_reference,
        optional_tag=authority.optional_tag,
        image_id=image_id,
        repo_digests=repo_digests,
        architecture=canonical_server,
        image_architecture=image_architecture,
        server_architecture=server_architecture,
        canonical_image_architecture=canonical_image,
        canonical_server_architecture=canonical_server,
        pulled=False,
    )


__all__ = [
    "BaseImageProvenance",
    "ImmutableImageAuthority",
    "SCRATCH_DIRECTORY_NAME",
    "TestImageError",
    "configured_base_repository",
    "normalize_architecture_pair",
    "parse_immutable_image_authority",
    "read_configured_base",
    "read_exact_local_image",
    "repo_digests_match_authority",
    "repository_scratch_directory",
    "require_private_scratch_directory",
]
