"""Current slim provenance and immutable-pin maintenance, without live network calls."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from ci.debian_base_refresh import BaseRefreshError, Registry, stable_version, verify_observation


def test_current_suite_tracks_stable_and_requires_slim():
    text = "# stable -- Debian 13.7 Released today\n# trixie -- Debian 13.7 Released today\nTags: trixie-slim, 13-slim\n"
    assert stable_version(text) == "13.7"
    with pytest.raises(BaseRefreshError, match="no longer current stable"):
        stable_version(text.replace("stable -- Debian 13.7", "stable -- Debian 14.0"))
    with pytest.raises(BaseRefreshError, match="no slim variant"):
        stable_version(text.replace("Tags: trixie-slim, 13-slim", "Tags: trixie"))


def observation():
    base = {"platforms": {arch: {"rootfs": [arch + "-base"]} for arch in ("amd64", "arm64")}}
    images = {"python:3.12-slim-trixie": {"index": "sha256:" + "a" * 64,
        "platforms": {arch: {"rootfs": [arch + "-base", "python"]} for arch in ("amd64", "arm64")}}}
    return base, images, {"python:3.12-slim-trixie": "sha256:" + "a" * 64}


def test_latest_derivative_and_pin_both_required():
    base, images, pins = observation()
    assert verify_observation(base, images, pins)
    pins["python:3.12-slim-trixie"] = "sha256:" + "b" * 64
    assert not verify_observation(base, images, pins)
    images["python:3.12-slim-trixie"]["platforms"]["amd64"]["rootfs"][0] = "old-base"
    with pytest.raises(BaseRefreshError, match="not incorporated"):
        verify_observation(base, images, pins)


def test_registry_refuses_tampered_metadata_without_printing_token():
    data = b'{"example":1}'
    def fetch(url, headers):
        return b'{"token":"test-secret"}' if "auth.docker.io" in url else data
    registry = Registry(fetch)
    with pytest.raises(BaseRefreshError, match="digest differs") as failure:
        registry.read("python", "blobs", "sha256:" + "0" * 64)
    assert "test-secret" not in str(failure.value)
    assert registry.read("python", "blobs", "sha256:" + hashlib.sha256(data).hexdigest())[0] == {"example": 1}


def test_registry_requires_exact_native_config_platform_and_population():
    config = {"os": "linux", "architecture": "amd64", "rootfs": {"diff_ids": ["base"]}}
    config_raw = json.dumps(config).encode()
    config_digest = "sha256:" + hashlib.sha256(config_raw).hexdigest()
    manifest_raw = json.dumps({"config": {"digest": config_digest}}).encode()
    manifest_digest = "sha256:" + hashlib.sha256(manifest_raw).hexdigest()
    item = {"platform": {"os": "linux", "architecture": "amd64"}, "digest": manifest_digest}
    index: dict[str, Any] = {"manifests": [item]}
    def fetch(url, _headers):
        if "auth.docker.io" in url:
            return b'{"token":"test-secret"}'
        if url.endswith(config_digest):
            return config_raw
        if url.endswith(manifest_digest):
            return manifest_raw
        return json.dumps(index).encode()
    registry = Registry(fetch)
    with pytest.raises(BaseRefreshError, match="missing a required"):
        registry.image("python", "tag")
    index["manifests"].append(copy.deepcopy(item))
    with pytest.raises(BaseRefreshError, match="duplicate native"):
        registry.image("python", "tag")
    index["manifests"][-1]["platform"]["architecture"] = "arm64"
    with pytest.raises(BaseRefreshError, match="platform disagrees"):
        registry.image("python", "tag")
