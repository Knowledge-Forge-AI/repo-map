"""Unit tests for the tracked D12 candidate release manifest and recipe wiring."""

from __future__ import annotations

import hashlib
import importlib.util
import json

from common_lore_index.runtime import commands, release
from repomap_test_support import d12_core_image as d12


def test_release_manifest_exports_ci68_amd64_candidate_closure() -> None:
    assert importlib.util.find_spec("common_lore_index.runtime.release_manifest") is not None
    from common_lore_index.runtime import release_manifest

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
    assert actual_sha == release_manifest.D12_CANDIDATE_MANIFEST_SHA256
    assert actual_sha != release_manifest.CI68_MANIFEST_SHA256


def test_release_py_remains_unpromoted_in_candidate_only_mode() -> None:
    assert release.PSYCOPG_LIBPQ_VERSION is None
    assert dict(release.DYNAMIC_PACKAGE_MANIFEST) == {}


def test_d12_recipe_renders_dockerfile_from_candidate_release_manifest() -> None:
    assert importlib.util.find_spec("common_lore_index.runtime.release_manifest") is not None
    assert importlib.util.find_spec("repomap_test_support.d12_recipe") is not None
    from common_lore_index.runtime import release_manifest
    from repomap_test_support import d12_recipe

    rendered = d12_recipe.recipe_text()
    assert d12.recipe_text() == rendered
    expected = commands.render_server_dockerfile(
        manifest=release_manifest.D12_CANDIDATE_PACKAGE_MANIFEST,
        libpq_version=release_manifest.D12_CANDIDATE_LIBPQ_VERSION,
    )
    assert rendered == expected
    assert 'io.repomap.release.libpq="180006"' in rendered


def test_runtime_stage_orders_closure_ldconfig_and_fail_closed_include_rmdir() -> None:
    from common_lore_index.runtime import release_manifest

    amd64_pkg = release_manifest.D12_CANDIDATE_PACKAGE_MANIFEST["amd64"]
    assert amd64_pkg.closure == ()
    nonempty_pkg = amd64_pkg._replace(closure=amd64_pkg.builder[:2])
    assert len(nonempty_pkg.closure) == 2
    release.validate_package_manifest(
        {"amd64": nonempty_pkg}, release_manifest.D12_CANDIDATE_LIBPQ_VERSION
    )

    default_df = commands.render_server_dockerfile()
    amd_df = commands.render_server_dockerfile(
        release_manifest.D12_CANDIDATE_PACKAGE_MANIFEST,
        release_manifest.D12_CANDIDATE_LIBPQ_VERSION,
    )
    nonempty_df = commands.render_server_dockerfile(
        {"amd64": nonempty_pkg},
        release_manifest.D12_CANDIDATE_LIBPQ_VERSION,
    )

    assert "apt-get" not in default_df
    assert (
        'ADR 0089 D3 package manifest unresolved for ${TARGETARCH}; '
        "refusing before package or backend execution" in default_df
    )
    assert 'io.repomap.release.libpq="unresolved"' in default_df
    assert (
        "    amd64) true ;; \\\n    *) exit 1 ;; \\\n    esac\n"
        "RUN ldconfig\nRUN rmdir /usr/local/include\n" in amd_df
    )
    assert (
        "rm -rf /var/lib/apt/lists/* ;; \\\n    *) exit 1 ;; \\\n    esac\n"
        "RUN ldconfig\nRUN rmdir /usr/local/include\n" in nonempty_df
    )
    for pkg in nonempty_pkg.closure:
        assert f"{pkg.name}={pkg.version}" in nonempty_df

    for rendered in (default_df, amd_df, nonempty_df):
        before_runtime, runtime_stage = rendered.split(
            f"FROM {release.POSTGRES_RELEASE_IMAGE} AS runtime\n", 1
        )
        assert "ldconfig" not in before_runtime
        assert "rmdir" not in before_runtime
        assert rendered.count("ldconfig") == 1
        assert rendered.count("rmdir") == 1
        assert runtime_stage.splitlines().count("RUN ldconfig") == 1
        assert runtime_stage.splitlines().count("RUN rmdir /usr/local/include") == 1
        assert [line for line in runtime_stage.splitlines() if "rmdir" in line] == [
            "RUN rmdir /usr/local/include"
        ]
        copy_idx = runtime_stage.index("COPY --from=python-runtime /usr/local /usr/local\n")
        closure_idx = runtime_stage.index('RUN case "${TARGETARCH}" in \\\n', copy_idx)
        closure_end = runtime_stage.index("    esac\n", closure_idx) + len("    esac\n")
        ldconfig_idx = runtime_stage.index("RUN ldconfig\n")
        rmdir_idx = runtime_stage.index("RUN rmdir /usr/local/include\n")
        license_copy_idx = runtime_stage.index(
            "COPY --from=python-runtime /build/src/main/python/common_lore_index/third_party_licenses/ "
            "/usr/share/doc/repomap-kg/psycopg/\n"
        )
        first_python_idx = runtime_stage.index('RUN package_root="$(python -c ')
        probe_idx = runtime_stage.index("python -I /tmp/repomap-release-probe.py")
        assert (
            copy_idx
            < closure_idx
            < closure_end
            == ldconfig_idx
            < ldconfig_idx + len("RUN ldconfig\n")
            == rmdir_idx
            < rmdir_idx + len("RUN rmdir /usr/local/include\n")
            == license_copy_idx
            < first_python_idx
            < probe_idx
        )
        assert not [
            line
            for line in runtime_stage[:first_python_idx].splitlines()
            if "python" in line and not line.startswith("COPY --from=python-runtime")
        ]
        assert (
            f"COPY <<'REPOMAP_PY' /tmp/repomap-release-probe.py\n"
            f"{release.RELEASE_FINAL_PROBE_PY}REPOMAP_PY\n" in runtime_stage
        )
        assert (
            'assert not [m for m in build_only if iu.find_spec(m)] '
            'and not os.path.exists("/usr/local/include")\n'
            in release.RELEASE_FINAL_PROBE_PY
        )
