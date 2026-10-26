"""Unit tests for the tracked D12 candidate release manifest and recipe wiring."""

from __future__ import annotations

import hashlib
import importlib.util
import json

from repomap_kg.runtime import commands, release
from repomap_test_support import d12_core_image as d12


def test_release_manifest_exports_ci68_amd64_candidate_closure() -> None:
    assert importlib.util.find_spec("repomap_kg.runtime.release_manifest") is not None
    from repomap_kg.runtime import release_manifest

    assert release_manifest.D12_CANDIDATE_LIBPQ_VERSION == 180006
    assert release_manifest.D12_CANDIDATE_LIBPQ_VERSION >= release.PRODUCT_MINIMUM_LIBPQ_VERSION
    assert release_manifest.CI68_MANIFEST_SHA256 == (
        "13f616f876ebc6e2ef6c9772e55e39426184944a15cce61ef2690187b2ef0273"
    )

    manifest = release_manifest.D12_CANDIDATE_PACKAGE_MANIFEST
    assert set(manifest) == {"amd64"}
    amd64_pkg = manifest["amd64"]
    assert isinstance(amd64_pkg, release.PlatformPackages)
    assert not hasattr(amd64_pkg, "python_baseline_imports")
    assert not hasattr(amd64_pkg, "pgdg_signing_key_fingerprints")
    assert amd64_pkg.key_fingerprints == ("B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8",)
    assert amd64_pkg.libpq5_version == "18.6-1.pgdg13+2"
    assert amd64_pkg.libpq_path == "/usr/lib/x86_64-linux-gnu/libpq.so.5.18"
    assert len(amd64_pkg.builder) == 48
    assert amd64_pkg.closure == ()
    assert len(amd64_pkg.lib_dynload) == 77
    release.validate_package_manifest(manifest, release_manifest.D12_CANDIDATE_LIBPQ_VERSION)

    canonical_json = json.dumps(amd64_pkg._asdict(), sort_keys=True, separators=(",", ":"))
    actual_sha = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    assert actual_sha == release_manifest.CI68_MANIFEST_SHA256


def test_release_py_remains_unpromoted_in_candidate_only_mode() -> None:
    assert release.PSYCOPG_LIBPQ_VERSION is None
    assert dict(release.DYNAMIC_PACKAGE_MANIFEST) == {}


def test_d12_recipe_renders_dockerfile_from_candidate_release_manifest() -> None:
    assert importlib.util.find_spec("repomap_kg.runtime.release_manifest") is not None
    assert importlib.util.find_spec("repomap_test_support.d12_recipe") is not None
    from repomap_kg.runtime import release_manifest
    from repomap_test_support import d12_recipe

    rendered = d12_recipe.recipe_text()
    assert d12.recipe_text() == rendered
    expected = commands.render_server_dockerfile(
        manifest=release_manifest.D12_CANDIDATE_PACKAGE_MANIFEST,
        libpq_version=release_manifest.D12_CANDIDATE_LIBPQ_VERSION,
    )
    assert rendered == expected
    assert 'io.repomap.release.libpq="180006"' in rendered
