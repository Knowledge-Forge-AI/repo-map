"""Pure owner for the exact Trixie server pin, its mirrors and the D9 helpers' optional image (ADR 0091).

No Docker, PostgreSQL or network: fakes replace the cluster and the template observation. This proves selection,
refusal and cache identity only; the real Trixie round trip and collation refusals are the integration node's.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from repomap_kg.runtime import release
from repomap_test_support import d12_core_image as d12
from repomap_test_support import d9_extension_restore as d9
from repomap_test_support.postgres_container import PostgresContainerHarness, TEST_POSTGRES_IMAGE
import test_sandbox
import test_sandbox_contract as contract

REPO_ROOT = Path(__file__).resolve().parents[5]
TRIXIE = "postgres:16.15-trixie@sha256:1beaa3084eee2676f20a9cd9928f0bf2c5bf674f8e49f81017912183d377c61c"
BOOKWORM = "postgres:16.15-bookworm@sha256:d81f7b51697014367236d07ec58b54153fc28f828b72bf247fe5c7487520bcb0"
PYTHON = "python:3.12-slim-trixie@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159"


def test_release_pins_and_every_mirror_are_the_exact_trixie_indexes():
    assert release.POSTGRES_RELEASE_IMAGE == contract.PRODUCTION_POSTGRES_IMAGE == TRIXIE
    assert release.PYTHON_RELEASE_IMAGE == contract.PYTHON_RELEASE_IMAGE == PYTHON
    assert (release.PYTHON_RELEASE_VERSION, release.POSTGRES_RELEASE_VERSION) == ("3.12.16", "16.15")
    assert release.GO_RELEASE_IMAGE == contract.GO_RELEASE_IMAGE and release.GO_RELEASE_VERSION == "1.26.10"
    assert release.PSYCOPG_LIBPQ_VERSION is None and dict(release.DYNAMIC_PACKAGE_MANIFEST) == {}, "unresolved"
    source = json.loads((REPO_ROOT / "tools/pgvector_test_source.json").read_text(encoding="utf-8"))
    assert source.pop("production_postgres_base_image") == TRIXIE, "the one release-pin mirror"
    assert source["test_postgres_base_image"] == contract.TEST_POSTGRES_IMAGE == TEST_POSTGRES_IMAGE
    assert hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest() == (
        "e457433a873011dfbdeddd77a5a37f9a0864c7c1e93f92bcf990d89d3af9c91b"), "no other pgvector or D15 field moved"
    assert d12.BASE_CONFIG_DIGESTS == {TRIXIE.split("@", 1)[1]: {
        "linux/arm64": "sha256:6162f3765f7563b273a879894c5751d41285f922dd75ba0ba508a89e024e43ca",
        "linux/amd64": "sha256:74d436cb49d3398cf7b5d7b33635d43623d9e4da4b93c22db453f7d5d81181b1"}}


def _no_command(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    raise AssertionError("the preload list is captured before any command runs")


def test_outer_sandbox_already_preloads_the_release_server_pin(monkeypatch):
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(test_sandbox._inner, "prepare_inner_images",
                        lambda runner, container_id, *, captured, images: seen.append(tuple(images)))
    test_sandbox._prepare_inner_images(_no_command, "c" * 64)
    assert len(seen) == 1 and {TRIXIE, TEST_POSTGRES_IMAGE, PYTHON} <= set(seen[0]), seen


@pytest.fixture
def clusters(monkeypatch, tmp_path):
    """Replace only the home writer and harness; the real selection and configuration code runs."""
    started: list[Any] = []

    class Harness:
        def __init__(self, config, identity):
            self.config, self.container_name = config, "owned-d9"
            started.append(PostgresContainerHarness(config))  # the real core image resolution

        def start(self):
            return self

        def teardown(self):
            pass

    monkeypatch.setattr(d9, "OwnedD9PostgresHarness", Harness)
    monkeypatch.setattr(d9, "setup_d9_backup_home", lambda home, stub, graph_db: home.mkdir(parents=True) or "id")
    monkeypatch.delenv("REPOMAP_TEST_PG_PROFILE", raising=False)
    return started


def test_default_selection_is_unchanged_and_the_release_pin_selects_only_the_core_image(clusters, tmp_path):
    with d9.owned_d9_postgres_cluster(tmp_path / "default") as (_identity, postgres, _runner):
        assert postgres.user and postgres.psql_command.endswith("psql")
    with d9.owned_d9_postgres_cluster(tmp_path / "release", image=TRIXIE):
        pass
    assert [(h.profile, h.image) for h in clusters] == [("core", TEST_POSTGRES_IMAGE), ("core", TRIXIE)]
    assert "--pull=never" in clusters[1].start_command() and clusters[1].start_command()[-1] == TRIXIE


@pytest.mark.parametrize("image, profile, message", [
    (TEST_POSTGRES_IMAGE, None, "unsupported D9 image"),
    (BOOKWORM, None, "unsupported D9 image"),
    ("postgres:16.15-trixie", None, "unsupported D9 image"),
    (TRIXIE.replace("trixie", "bookworm"), None, "unsupported D9 image"),
    (TRIXIE, "pgvector", "pgvector profile keeps its own image"),
])
def test_unsupported_explicit_images_refuse_before_any_home_cluster_or_reference(clusters, tmp_path, monkeypatch,
                                                                                  image, profile, message):
    with pytest.raises(ValueError, match=message):
        with d9.owned_d9_postgres_cluster(tmp_path / "home", image=image, profile=profile):
            pass
    monkeypatch.setattr(d9, "_CLEAN_TEMPLATE_REFERENCES", {})
    with pytest.raises(ValueError, match=message):
        d9.clean_template_reference(tmp_path, image=image, profile=profile)
    assert clusters == [] and d9._CLEAN_TEMPLATE_REFERENCES == {} and list(tmp_path.iterdir()) == []


def test_clean_reference_cache_is_keyed_by_image_and_profile(monkeypatch, tmp_path):
    started: list[tuple[str, str | None, str | None]] = []

    @contextmanager
    def cluster(home, *, runtime, profile, image):
        started.append((home.name, profile, image))
        yield SimpleNamespace(postgres_container=f"server-{len(started)}"), SimpleNamespace(user="u"), None

    monkeypatch.setattr(d9, "_CLEAN_TEMPLATE_REFERENCES", {})
    monkeypatch.setattr(d9, "owned_d9_postgres_cluster", cluster)
    monkeypatch.setattr(d9, "observe_template_baseline_in_container", lambda name, *, user, runtime: f"baseline-{name}")
    monkeypatch.delenv("REPOMAP_TEST_PG_PROFILE", raising=False)
    alpine, trixie = d9.clean_template_reference(tmp_path), d9.clean_template_reference(tmp_path, image=TRIXIE)
    vector = d9.clean_template_reference(tmp_path, profile="pgvector")
    assert len({alpine, trixie, vector}) == 3, "Trixie never reuses the Alpine or pgvector reference"
    assert (d9.clean_template_reference(tmp_path, profile="core"), d9.clean_template_reference(tmp_path, image=TRIXIE),
            d9.clean_template_reference(tmp_path, profile="pgvector")) == (alpine, trixie, vector), "session cache"
    assert started == [("reference-home-core", "core", None), ("reference-home-core-release", "core", TRIXIE),
                       ("reference-home-pgvector", "pgvector", None)]
    assert set(d9._CLEAN_TEMPLATE_REFERENCES) == {(None, "core"), (TRIXIE, "core"), (None, "pgvector")}
