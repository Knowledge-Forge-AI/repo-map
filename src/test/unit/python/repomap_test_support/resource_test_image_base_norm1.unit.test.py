from __future__ import annotations

from types import SimpleNamespace

import pytest

from repomap_test_support.resource_test_image_base import (
    TestImageError as ImageLifecycleError,
    normalize_architecture_pair,
    parse_immutable_image_authority,
    read_configured_base,
)


_DIGEST = "sha256:" + "c" * 64
_CONFIGURED = f"python:3.12-slim-bookworm@{_DIGEST}"
_CANONICAL = f"python@{_DIGEST}"
_IMAGE_ID = "sha256:" + "b" * 64


class _Images:
    def __init__(self, image) -> None:
        self.image = image

    def get(self, _reference: str):
        return self.image


class _Client:
    def __init__(self, *, repo_digests: tuple[str, ...], server_arch: str) -> None:
        image = SimpleNamespace(
            id=_IMAGE_ID,
            attrs={"RepoDigests": list(repo_digests), "Architecture": "arm64"},
        )
        self.images = _Images(image)
        self._server_arch = server_arch

    def info(self):
        return {"Architecture": self._server_arch}


def test_tag_bearing_configured_authority_accepts_tagless_engine_repodigest():
    _image, provenance = read_configured_base(
        _Client(repo_digests=(_CANONICAL,), server_arch="arm64"),
        _CONFIGURED,
        allow_missing=False,
    )

    assert provenance is not None
    assert provenance.reference == _CONFIGURED
    assert provenance.repository == "python"


def test_arm64_image_accepts_aarch64_docker_server_alias():
    _image, provenance = read_configured_base(
        _Client(repo_digests=(_CONFIGURED,), server_arch="aarch64"),
        _CONFIGURED,
        allow_missing=False,
    )

    assert provenance is not None
    assert provenance.architecture == "arm64"
    assert provenance.image_architecture == "arm64"
    assert provenance.server_architecture == "aarch64"
    assert provenance.canonical_image_architecture == "arm64"
    assert provenance.canonical_server_architecture == "arm64"


@pytest.mark.parametrize(
    ("reference", "repository", "optional_tag"),
    [
        (_CONFIGURED, "python", "3.12-slim-bookworm"),
        (f"docker.io/library/python:3.12-slim-bookworm@{_DIGEST}", "docker.io/library/python", "3.12-slim-bookworm"),
        (f"registry.example:5000/team/python:3.12@{_DIGEST}", "registry.example:5000/team/python", "3.12"),
        (f"registry.example:5000/team/python@{_DIGEST}", "registry.example:5000/team/python", None),
    ],
)
def test_immutable_authority_preserves_repository_ports_and_paths(
    reference: str,
    repository: str,
    optional_tag: str | None,
):
    authority = parse_immutable_image_authority(reference)

    assert authority.repository == repository
    assert authority.optional_tag == optional_tag
    assert authority.digest == _DIGEST
    assert authority.canonical_reference == f"{repository}@{_DIGEST}"


@pytest.mark.parametrize(
    "reference",
    [
        "python:3.12-slim-bookworm",
        "python@sha256:" + "C" * 64,
        "python@sha256:" + "c" * 63,
        "python@@sha256:" + "c" * 64,
        "python @sha256:" + "c" * 64,
        "python:@sha256:" + "c" * 64,
    ],
)
def test_immutable_authority_rejects_mutable_or_malformed_references(reference: str):
    with pytest.raises(ImageLifecycleError, match="configured base"):
        parse_immutable_image_authority(reference)


@pytest.mark.parametrize(
    "repo_digest",
    [
        f"otherrepo@{_DIGEST}",
        "python@sha256:" + "d" * 64,
    ],
)
def test_engine_repodigest_requires_same_repository_and_digest(repo_digest: str):
    with pytest.raises(ImageLifecycleError, match="RepoDigest"):
        read_configured_base(
            _Client(repo_digests=(repo_digest,), server_arch="arm64"),
            _CONFIGURED,
            allow_missing=False,
        )


@pytest.mark.parametrize(
    ("image", "server", "canonical"),
    [
        ("arm64", "aarch64", "arm64"),
        ("amd64", "x86_64", "amd64"),
        ("future_arch", "future_arch", "future_arch"),
    ],
)
def test_architecture_pair_accepts_only_closed_aliases_or_identical_lowercase(
    image: str,
    server: str,
    canonical: str,
):
    assert normalize_architecture_pair(image, server) == (canonical, canonical)


@pytest.mark.parametrize(
    ("image", "server"),
    [
        ("arm64", "amd64"),
        ("future_arch", "other_arch"),
        ("ARM64", "aarch64"),
    ],
)
def test_architecture_pair_refuses_cross_family_fuzzy_or_uppercase_values(
    image: str,
    server: str,
):
    with pytest.raises(ImageLifecycleError, match="architecture"):
        normalize_architecture_pair(image, server)


@pytest.mark.parametrize(
    "bad_image_id",
    [
        "not-an-exact-sha",
        "sha256:" + "b" * 63,
        "sha256:" + "B" * 64,
        "sha512:" + "b" * 128,
        "",
    ],
)
def test_read_configured_base_aborts_when_base_engine_image_id_is_not_exact(bad_image_id: str):
    image = SimpleNamespace(
        id=bad_image_id,
        attrs={"RepoDigests": [_CONFIGURED], "Architecture": "arm64"},
    )
    client = SimpleNamespace(
        images=SimpleNamespace(get=lambda _ref: image),
        info=lambda: {"Architecture": "arm64"},
    )
    with pytest.raises(ImageLifecycleError, match="configured base Engine image ID is not exact"):
        read_configured_base(client, _CONFIGURED, allow_missing=False)
