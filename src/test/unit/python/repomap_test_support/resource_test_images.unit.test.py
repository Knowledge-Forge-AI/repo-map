from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest
from repomap_test_support import resource_test_image_commands as commands
from repomap_test_support import resource_test_images as images_module
from repomap_test_support.resource_test_image_records import read_project_runtime_dependencies
from repomap_test_support.resource_test_images import (
    DEPLOYMENT_IMAGE_PREFIX,
    RUNTIME_MATERIALIZATION_PROOF_RECIPE_SCHEMA,
    TestImageError as ImageLifecycleError,
    TestImageManager as ImageManager,
    canonical_runtime_fingerprint,
)
from src.test.unit.python.repomap_test_support.resource_test_images_fixtures import (
    FakeImage,
    FakeClient,
    _project,
    _uninstall_authorities as _uninstall_authorities,
    _resource_run,
    _manager,
    _runtime_labels,
    BASE_ID,
    BASE_REFERENCE,
    BASE_CANONICAL_REFERENCE,
)

REPO_ROOT = Path(__file__).resolve().parents[5]


def test_runtime_fingerprint_ignores_candidate_source_and_changes_on_inputs():
    fields = {
        "recipe_schema": 1,
        "architecture": "arm64",
        "base_image_id": BASE_ID,
        "dependencies": ["a==1"],
    }
    original = canonical_runtime_fingerprint(fields)
    assert original == canonical_runtime_fingerprint(
        {**fields, "candidate_source_sha256": "ignored-by-contract"}
    )
    for key, value in (
        ("recipe_schema", 2),
        ("architecture", "amd64"),
        ("base_image_id", "sha256:" + "d" * 64),
        ("dependencies", ["a==2"]),
    ):
        assert canonical_runtime_fingerprint({**fields, key: value}) != original

def test_runtime_identity_fingerprints_every_materialization_input(tmp_path, monkeypatch):
    manager, _client = _manager(tmp_path)
    identity = manager.runtime_identity()
    inputs = identity.fields["materialization_inputs"]
    assert inputs == commands.materialization_inputs() and "lock_resolution_input" not in identity.fields
    for key, value in (("build_lock_sha256", "0" * 64), ("project_lock_sha256", "1" * 64),
                       ("install_and_probe_sha256", "2" * 64), ("apt_prerequisites_sha256", "3" * 64),
                       ("native_build_packages", ["gcc"])):
        monkeypatch.setattr(images_module, "materialization_inputs",
                            lambda sources=None, key=key, value=value: {**inputs, key: value})
        assert manager.runtime_identity().fingerprint != identity.fingerprint, f"{key} must invalidate the cache"

def _checkout_copy(tmp_path, monkeypatch):
    for path in (commands.BUILD_LOCK, commands.PROJECT_LOCK, commands.APT_PREREQUISITES):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes((REPO_ROOT / path).read_bytes())
    monkeypatch.setattr(commands, "_CHECKOUT_ROOT", tmp_path)

def test_materialization_inputs_digest_the_checkout_locks_helper_and_install_program(tmp_path, monkeypatch):
    _checkout_copy(tmp_path, monkeypatch)
    original = commands.materialization_inputs()
    helper = (REPO_ROOT / commands.APT_PREREQUISITES).read_bytes()
    assert original["apt_prerequisites_sha256"] == hashlib.sha256(helper).hexdigest()
    tools = commands.build_lock_tools((tmp_path / commands.BUILD_LOCK).read_text())
    assert tools == ("packaging", "setuptools", "wheel")
    for path, key in ((commands.BUILD_LOCK, "build_lock_sha256"),
                      (commands.APT_PREREQUISITES, "apt_prerequisites_sha256")):
        (tmp_path / path).write_bytes((tmp_path / path).read_bytes() + b"# changed\n")
        changed = commands.materialization_inputs()
        assert changed[key] != original[key], key
        assert {k: v for k, v in changed.items() if k != key} == {k: v for k, v in original.items() if k != key}
        (tmp_path / path).write_bytes((REPO_ROOT / path).read_bytes())
    monkeypatch.setattr(commands, "_INSTALL_AND_PROBE", commands._INSTALL_AND_PROBE + "\n")
    assert commands.materialization_inputs()["install_and_probe_sha256"] != original["install_and_probe_sha256"]
    payload = json.loads(commands.install_and_probe_command(("psycopg[c]==3.3.6",), "3.3.6")[2])
    assert payload[4] == ["packaging", "setuptools", "wheel"], "the image removes exactly the build lock's tools"
    assert payload[5].encode() == helper and payload[6] == original["apt_prerequisites_sha256"]

def test_materializer_executes_the_fingerprinted_helper_snapshot_not_later_checkout_bytes(tmp_path, monkeypatch):
    _checkout_copy(tmp_path / "checkout", monkeypatch)
    manager, client = _manager(tmp_path)
    reader, helper = commands.read_materialization_sources, tmp_path / "checkout" / commands.APT_PREREQUISITES
    def snapshot_then_change():
        sources, _ = reader(), helper.write_bytes(helper.read_bytes() + b"# replaced after fingerprinting\n")
        return sources
    monkeypatch.setattr(images_module, "read_materialization_sources", snapshot_then_change)
    manager.ensure_runtime_image()
    payload = json.loads(client.containers.create_calls[0][1][2])
    executed = hashlib.sha256(payload[5].encode()).hexdigest()
    fingerprinted = manager._last_identity.fields["materialization_inputs"]["apt_prerequisites_sha256"]
    assert executed == fingerprinted == payload[6] == hashlib.sha256(
        (REPO_ROOT / commands.APT_PREREQUISITES).read_bytes()).hexdigest()
    assert b"replaced after fingerprinting" in helper.read_bytes()

def test_sources_that_differ_from_the_fingerprint_refuse_before_any_container(tmp_path):
    manager, client = _manager(tmp_path)
    identity = manager.runtime_identity()
    manager._last_sources = manager._last_sources._replace(apt_prerequisites="print('other helper')\n")
    with pytest.raises(ImageLifecycleError, match="differ from the fingerprinted identity"):
        manager._build_runtime_image(identity, "repomap-test-runtime:fixture")
    assert client.containers.create_calls == []

def test_runtime_install_runs_the_bound_helper_and_refuses_changed_packages_or_helper(tmp_path):
    script = commands._INSTALL_AND_PROBE
    helpers = script.split("\nrows = apt_helper")[0] + "\n"
    source = (REPO_ROOT / commands.APT_PREREQUISITES).read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode()).hexdigest()
    exact, other, operator = tmp_path / "exact.pref", tmp_path / "other.pref", tmp_path / "operator.pref"
    operator.write_text("operator\n", encoding="utf-8")
    program = helpers + (
        "row = lambda version, name='n': {'name': name, 'version': version, 'status': 'ii', 'architecture': 'arm64'}\n"
        "print(apt_helper['SCHEMA'], changes({'libc6:arm64': row('2.36-9')},"
        " {'libc6:arm64': row('2.36-9'), 'libpq5:arm64': row('15.19-0')}))\n"
        "for after in ({'libc6:arm64': row('2.36-10')}, {'libpq5:arm64': row('15.19-0')}):\n"
        "    try:\n        changes({'libc6:arm64': row('2.36-9')}, after)\n"
        "    except AssertionError as error:\n        print('refused', error)\n"
        "ssl = lambda *versions: {f'libssl3t64:{n}': row(v, 'libssl3t64') for n, v in enumerate(versions)}\n"
        f"exact, other, operator = {str(exact)!r}, {str(other)!r}, {str(operator)!r}\n"
        "print(header_pin(ssl('3.5.7-1~deb13u3'), 'arm64', exact))\n"
        "for rows in (ssl('3.5.5-1~deb13u1'), ssl('3.5.7-1~deb13u3', '3.5.5-1~deb13u1'),"
        " {'old': row('3.0.20-1~deb12u2', 'libssl3')}):\n"
        "    try:\n        header_pin(rows, 'arm64', other)\n    except RuntimeError as error:\n"
        "        print('refused', 'before any preference or install' in str(error))\n"
        "try:\n    header_pin(ssl('3.5.7-1~deb13u3'), 'arm64', operator)\n"
        "except FileExistsError:\n    print('refused')\n")
    run = lambda sha: subprocess.run([sys.executable, "-I", "-c", program, json.dumps(
        [[], {}, "3.3.6", [], [], source, sha])], capture_output=True, text=True, check=False)
    tampered = run("0" * 64)
    assert tampered.returncode == 1 and "prerequisite helper differs" in tampered.stderr and tampered.stdout == ""
    done = run(digest)
    assert done.returncode == 0 and done.stdout.splitlines() == [
        "repomap-apt-prerequisites-v1 ['libpq5:arm64=15.19-0']",
        "refused existing packages changed {'libc6:arm64': ['2.36-9', '2.36-10']} or were removed",
        "refused existing packages changed {'libc6:arm64': ['2.36-9', None]} or were removed",
        str(exact), *["refused True"] * 3, "refused"], done  # wrong, multiple, legacy Bookworm: no None fallthrough
    assert exact.read_text() == "Package: libssl-dev\nPin: version 3.5.7-1~deb13u3\nPin-Priority: 999\n"
    assert not other.exists() and operator.read_text() == "operator\n", "other states pin nothing; no clobber"
    steps = [script.index(step) for step in (
        "\nrows = apt_helper", "\npinned = header_pin(rows, architecture, HEADER_PIN)",
        'apt_helper["install_prerequisites"]', "\nos.remove(pinned)", "attest_libpq")]
    assert steps == sorted(steps), "the pin exists only around the helper's native install"
    assert '"-m", "pip", "check"' in script, "the build closure is checked before removal"


def test_fixed_materialization_proof_schema_changes_only_recipe_identity(tmp_path):
    canonical, _client = _manager(tmp_path)
    proof_root = tmp_path / "proof"
    proof_root.mkdir()
    proof, _proof_client = _manager(
        proof_root,
        recipe_schema=RUNTIME_MATERIALIZATION_PROOF_RECIPE_SCHEMA,
    )

    canonical_identity = canonical.runtime_identity()
    proof_identity = proof.runtime_identity()

    assert proof_identity.fingerprint != canonical_identity.fingerprint
    differing = {
        key for key in canonical_identity.fields
        if canonical_identity.fields[key] != proof_identity.fields[key]
    }
    assert differing == {"recipe_schema"}
    assert proof_identity.fields["recipe_schema"] == 2


def test_unowned_materialization_recipe_schema_is_refused(tmp_path):
    with pytest.raises(ImageLifecycleError, match="not repository-owned"):
        _manager(tmp_path, recipe_schema=3)


def test_dynamic_project_dependencies_fail_closed(tmp_path):
    manager, _client = _manager(tmp_path)
    manager.repo_root.joinpath("pyproject.toml").write_text(
        """[project]
name = "fixture"
version = "0.1"
dynamic = ["dependencies"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ImageLifecycleError, match="dynamic project dependencies"):
        manager.runtime_identity()


_SPLIT_PROJECT = """[project]
name = "fixture"
version = "0.1"
dependencies = ["typing-extensions==4.16.0"]

[project.optional-dependencies]
postgres = ["psycopg[binary]==3.2.12"]
"""


def test_postgres_extra_layout_keeps_the_runtime_identity(tmp_path):
    legacy, _legacy_client = _manager(tmp_path)
    split_root = tmp_path / "split"
    split_root.mkdir()
    split, _split_client = _manager(split_root)
    split.repo_root.joinpath("pyproject.toml").write_text(_SPLIT_PROJECT, encoding="utf-8")
    expected = ("psycopg[binary]==3.2.12", "typing-extensions==4.16.0")

    assert split.runtime_identity().fingerprint == legacy.runtime_identity().fingerprint
    assert split.runtime_identity().fields["project_runtime_dependencies"] == expected
    assert read_project_runtime_dependencies(REPO_ROOT, "3.3.6") == ("psycopg[c]==3.3.6", "typing-extensions==4.16.0")


def test_psycopg_missing_from_base_and_postgres_extra_fails_closed(tmp_path):
    manager, _client = _manager(tmp_path)
    manager.repo_root.joinpath("pyproject.toml").write_text(
        _SPLIT_PROJECT.replace('postgres = ["psycopg[binary]==3.2.12"]', "test = []"),
        encoding="utf-8",
    )

    with pytest.raises(ImageLifecycleError, match="Psycopg release input"):
        manager.runtime_identity()


def test_deployment_and_legacy_namespaces_are_never_selected_or_deleted(tmp_path):
    deployment = FakeImage("sha256:" + "d" * 64, tags=(f"{DEPLOYMENT_IMAGE_PREFIX}release-1",))
    legacy = FakeImage("sha256:" + "e" * 64, tags=("repomap-runtime-deadbeef:latest",))
    manager, client = _manager(tmp_path, (deployment, legacy))

    selected = manager.ensure_runtime_image()

    assert selected not in {deployment.id, legacy.id}
    assert deployment.id in client.images.objects
    assert legacy.id in client.images.objects
    assert client.images.remove_calls == []
    assert [item.image_id for item in manager.inventory().legacy_unclassified] == [legacy.id]


def test_matching_managed_cache_is_reused_without_build(tmp_path):
    manager, client = _manager(tmp_path)
    identity = manager.runtime_identity()
    cached = FakeImage("sha256:" + "a" * 64, tags=(manager.runtime_tag(identity.fingerprint),),
                       labels=_runtime_labels(identity.fingerprint))
    client.images.objects[cached.id] = cached

    assert manager.ensure_runtime_image() == cached.id
    assert client.images.runtime_commit_calls == []


@pytest.mark.parametrize("unexpected_value", ["dynamic", ""])
def test_runtime_cache_with_unexpected_resource_label_is_never_reused(tmp_path, unexpected_value):
    manager, client = _manager(tmp_path)
    identity = manager.runtime_identity()
    labels = _runtime_labels(identity.fingerprint)
    labels["org.repomap.test.resource.run_id"] = unexpected_value
    cached = FakeImage("sha256:" + "7" * 64, tags=(manager.runtime_tag(identity.fingerprint),), labels=labels)
    client.images.objects[cached.id] = cached

    with pytest.raises(ImageLifecycleError, match="ownership ambiguity"):
        manager.ensure_runtime_image()

    assert client.images.runtime_commit_calls == []
    assert client.images.remove_calls == []


def test_missing_runtime_cache_builds_dependency_only_image_exactly_once(tmp_path):
    manager, client = _manager(tmp_path)

    selected = manager.ensure_runtime_image()
    selected_again = manager.ensure_runtime_image()

    assert selected_again == selected
    assert len(client.images.runtime_commit_calls) == 1
    configuration = client.images.runtime_commit_calls[0][2]
    assert configuration["Cmd"] == ["python3"]
    assert configuration["Entrypoint"] is None
    assert configuration["Labels"] == _runtime_labels(
        manager.runtime_identity().fingerprint
    )
    flag, materialization_script, payload = client.containers.create_calls[0][1]
    materialization_command = "\n".join((flag, materialization_script, payload))
    materialization_options = client.containers.create_calls[0][3]
    assert flag == "-c" and "psycopg[binary]==3.2.12" in payload
    assert "typing-extensions==4.16.0" in materialization_command
    assert "REPOMAP_DEPENDENCY_VERSIONS=" in materialization_command
    assert "COPY src/main/python" not in materialization_command
    # ADR 0089 D5/D6: hash-locked inputs only, no build isolation, compiler purged, system libpq5 kept.
    for token in ('"--require-hashes"', '"--no-build-isolation", "--check-build-dependencies"',
                  'apt_helper["install_prerequisites"](subprocess.run, [*native, "libpq5"]',
                  'apt_helper["attest_libpq"](subprocess.run)',
                  '"purge", "--yes", "--auto-remove"', 'pq.__impl__ == "c"', 'find_spec("psycopg_binary") is None'):
        assert token in materialization_script, token
    assert "apt-get\", \"-qq\", \"install" not in materialization_script, "no unversioned native install"
    c_hash = "--hash=sha256:29c568426ad61c1b702c7d73505c43ca2c9fc5d97a8431d8d9049e731e319ff8"
    assert "psycopg-c==3.3.6" in payload and c_hash in payload
    assert materialization_options == {
        "entrypoint": ["python"],
        "network_mode": "bridge",
    }
    assert client.images.pull_calls == []


def test_mutable_configured_base_cannot_authorize_pull(tmp_path):
    resource_run = _resource_run(tmp_path)
    client = FakeClient(())

    with pytest.raises(ImageLifecycleError, match="exact repository digest"):
        ImageManager(
            repo_root=_project(tmp_path),
            resource_run=resource_run,
            client=client,
            base_reference="python:3.12-slim-bookworm",
            python_base_family="python:3.12-slim-bookworm",
            python_version="3.12.13",
            psycopg_release_version="3.2.12",
            probe=lambda _identity: None,
        )

    assert client.images.pull_calls == []


def test_missing_exact_configured_base_pulls_that_digest_once(tmp_path):
    manager, client = _manager(tmp_path, include_base=False)

    def pull(reference):
        client.images.pull_calls.append(((reference,), {}))
        image = FakeImage(BASE_ID, repo_digests=(BASE_CANONICAL_REFERENCE,))
        client.images.objects[image.id] = image
        return image

    client.images.pull = pull

    selected = manager.ensure_runtime_image()
    selected_again = manager.ensure_runtime_image()

    assert selected_again == selected
    assert client.images.pull_calls == [((BASE_CANONICAL_REFERENCE,), {})]
    assert manager.base_provenance.reference == BASE_REFERENCE
    assert manager.base_provenance.image_id == BASE_ID
    assert manager.base_provenance.pulled is True
    inventory = manager.inventory()
    assert BASE_ID not in {item.image_id for item in inventory.runtime_cache}
    assert len(inventory.runtime_cache) == 1


def test_pulled_base_completes_canonical_boundary_attribution(tmp_path):
    manager, client = _manager(tmp_path, with_boundary=True, include_base=False)

    def pull(reference):
        client.images.pull_calls.append(((reference,), {}))
        image = FakeImage(BASE_ID, repo_digests=(BASE_CANONICAL_REFERENCE,))
        client.images.objects[image.id] = image
        return image

    client.images.pull = pull

    manager.ensure_runtime_image()
    projection = manager.verify_boundary()

    assert client.images.pull_calls == [((BASE_CANONICAL_REFERENCE,), {})]
    assert projection["managed_external_base_pull_count"] == 1
    assert projection["new_managed_external_test_base_images"] == 1
    assert projection["new_unattributed_images"] == 0


def test_pulled_base_repodigest_mismatch_refuses(tmp_path):
    manager, client = _manager(tmp_path, include_base=False)

    def pull(reference):
        client.images.pull_calls.append(((reference,), {}))
        image = FakeImage(
            BASE_ID,
            tags=(reference,),
            repo_digests=("python:3.12-slim-bookworm@sha256:" + "d" * 64,),
        )
        client.images.objects[image.id] = image
        return image

    client.images.pull = pull

    with pytest.raises(ImageLifecycleError, match="RepoDigest"):
        manager.ensure_runtime_image()


def test_configured_base_architecture_mismatch_refuses_without_pull(tmp_path):
    manager, client = _manager(tmp_path)
    client.images.objects[BASE_ID].attrs["Architecture"] = "amd64"

    with pytest.raises(ImageLifecycleError, match="architecture"):
        manager.ensure_runtime_image()

    assert client.images.pull_calls == []
