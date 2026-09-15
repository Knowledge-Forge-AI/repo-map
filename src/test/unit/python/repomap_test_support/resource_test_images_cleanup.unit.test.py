from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import json
import stat
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from repomap_test_support.resource_test_images import (
    DEPLOYMENT_IMAGE_PREFIX,
    EPHEMERAL_IMAGE_PREFIX,
    TestImageError as ImageLifecycleError,
    TestImageManager as ImageManager,
)
from src.test.unit.python.repomap_test_support.resource_test_images_fixtures import (
    FakeImage,
    _uninstall_authorities as _uninstall_authorities,
    _resource_run,
    _manager,
    BASE_REFERENCE,
)


def test_ephemeral_cleanup_removes_only_exact_registered_id(tmp_path):
    manager, client = _manager(tmp_path)
    owned = FakeImage(
        "sha256:" + "3" * 64,
        tags=(f"{EPHEMERAL_IMAGE_PREFIX}run-1-1",),
        labels={
            "org.repomap.test.managed": "true",
            "org.repomap.test.image.class": "ephemeral",
            "org.repomap.test.image.schema": "1",
            "org.repomap.test.run-id": "run-1",
            "org.repomap.test.repository": "repo-map",
        },
    )
    foreign = FakeImage(
        "sha256:" + "0" * 64,
        tags=(f"{EPHEMERAL_IMAGE_PREFIX}foreign-1",),
    )
    client.images.objects.update({owned.id: owned, foreign.id: foreign})

    manager.register_ephemeral_image(owned.id)
    manager.cleanup_ephemeral_run_images()

    assert owned.id not in client.images.objects
    assert foreign.id in client.images.objects
    assert client.images.remove_calls == [(owned.id, False, True)]


def test_ephemeral_cleanup_revalidates_ownership_and_recovers_from_ledger(tmp_path):
    manager, client = _manager(tmp_path)
    owned = FakeImage(
        "sha256:" + "2" * 64,
        tags=(f"{EPHEMERAL_IMAGE_PREFIX}run-1-2",),
        labels={
            "org.repomap.test.managed": "true",
            "org.repomap.test.image.class": "ephemeral",
            "org.repomap.test.image.schema": "1",
            "org.repomap.test.run-id": "run-1",
            "org.repomap.test.repository": "repo-map",
        },
    )
    client.images.objects[owned.id] = owned
    manager.register_ephemeral_image(owned.id)
    manager._ephemeral_ids.clear()
    owned.tags.append(f"{DEPLOYMENT_IMAGE_PREFIX}release-race")

    with pytest.raises(ImageLifecycleError, match="ownership ambiguity"):
        manager.cleanup_ephemeral_run_images()

    assert owned.id in client.images.objects
    assert client.images.remove_calls == []


def test_ephemeral_build_requires_the_authorized_exact_local_base(tmp_path):
    manager, client = _manager(tmp_path)

    with pytest.raises(ImageLifecycleError, match="authorized exact local image"):
        manager.build_ephemeral_image(
            "FROM busybox:latest\n",
            ordinal=1,
            exact_local_base_reference=BASE_REFERENCE,
        )

    assert client.images.build_calls == []
    image_id = manager.build_ephemeral_image(
        f"FROM {BASE_REFERENCE}\n",
        ordinal=1,
        exact_local_base_reference=BASE_REFERENCE,
    )
    assert client.images.objects[image_id].tags == [
        f"{EPHEMERAL_IMAGE_PREFIX}run-1-1"
    ]
    manager.cleanup_ephemeral_run_images()
    assert image_id not in client.images.objects

    runtime = FakeImage("sha256:" + "a" * 64)
    client.images.objects[runtime.id] = runtime
    image_id = manager.build_ephemeral_image(
        f"FROM {runtime.id}\n",
        ordinal=2,
        exact_local_base_reference=runtime.id,
    )
    manager.cleanup_ephemeral_run_images()
    assert image_id not in client.images.objects


def test_ephemeral_cleanup_attempts_every_owned_exact_id(tmp_path):
    manager, client = _manager(tmp_path)
    owned = []
    for ordinal in (1, 2):
        image = FakeImage(
            "sha256:" + str(ordinal + 6) * 64,
            tags=(f"{EPHEMERAL_IMAGE_PREFIX}run-1-{ordinal}",),
            labels=manager._ephemeral_labels("run-1"),
        )
        client.images.objects[image.id] = image
        manager.register_ephemeral_image(image.id)
        owned.append(image)
    original_remove = client.images.remove

    def fail_first(identity, *, force, noprune):
        if identity == owned[0].id:
            raise RuntimeError("busy")
        return original_remove(identity, force=force, noprune=noprune)

    client.images.remove = fail_first
    with pytest.raises(ImageLifecycleError, match="cleanup failed for 1"):
        manager.cleanup_ephemeral_run_images()

    assert owned[0].id in client.images.objects
    assert owned[1].id not in client.images.objects


def test_concurrent_ensure_is_single_flight_and_writes_private_identity_evidence(
    tmp_path,
):
    manager, client = _manager(tmp_path)
    second_root = tmp_path / "second"
    second_root.mkdir()
    second_run = _resource_run(second_root)
    second = ImageManager(
        repo_root=manager.repo_root,
        resource_run=second_run,
        client=client,
        base_reference=BASE_REFERENCE,
        python_base_family="python:3.12-slim-bookworm",
        python_version="3.12.13",
        psycopg_release_version="3.2.12",
        probe=lambda _identity: None,
    )
    original_build = client.images.commit_runtime

    def slow_build(*args, **kwargs):
        time.sleep(0.05)
        return original_build(*args, **kwargs)

    client.images.commit_runtime = slow_build
    with ThreadPoolExecutor(max_workers=2) as pool:
        selected = tuple(pool.map(lambda item: item.ensure_runtime_image(), (manager, second)))

    assert selected[0] == selected[1]
    assert len(client.images.runtime_commit_calls) == 1

    evidence_root = tmp_path / "evidence-run"
    evidence_root.mkdir()
    retained = []
    manager.resource_run.layout = SimpleNamespace(run_root=evidence_root)
    manager.resource_run.retain_evidence = lambda path, *, reason: retained.append(
        (path, reason)
    )
    manager.ensure_runtime_image()
    evidence_path = next(evidence_root.glob("test-runtime-*.evidence.json"))
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["canonical_json"] == manager.runtime_identity().canonical_json
    assert payload["selected_image_id"] == selected[0]
    assert stat.S_IMODE(evidence_path.stat().st_mode) == 0o600
    assert retained == [(evidence_path, "diagnostic_evidence")]


def test_private_evidence_path_rejects_opaque_materialization_failure(
    tmp_path, monkeypatch
):
    manager, _client = _manager(tmp_path)
    evidence_root = tmp_path / "failure-evidence"
    evidence_root.mkdir()
    manager.resource_run.layout = SimpleNamespace(run_root=evidence_root)
    manager.resource_run.retain_evidence = lambda _path, *, reason: None

    def fail_opaquely(*_args, **_kwargs):
        raise ImageLifecycleError("managed runtime image materialization failed")

    monkeypatch.setattr(manager, "_build_runtime_image", fail_opaquely)

    with pytest.raises(
        ImageLifecycleError,
        match="structured materialization failure evidence is unavailable",
    ):
        manager.ensure_runtime_image()

    evidence_path = next(evidence_root.glob("test-runtime-*.evidence.json"))
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["materialization_failure_status"] == "rejected_opaque"
    assert payload["error_type"] == "TestImageError"


def test_no_broad_prune_api_is_reachable(tmp_path):
    manager, _client = _manager(tmp_path)

    assert not hasattr(manager, "prune")
    assert not hasattr(manager, "remove_unattributed_images")
    implementation = Path(manager.__class__.__module__.replace(".", "/"))
    del implementation
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            Path(__file__).parents[3]
            / "support/python/repomap_test_support/resource_test_images.py",
            Path(__file__).parents[3]
            / "support/python/repomap_test_support/resource_docker_engine.py",
        )
    )
    assert ".images.prune(" not in sources
    assert ".system.prune(" not in sources
    assert "image prune" not in sources
    assert "system prune" not in sources


def test_network_pull_call_is_owned_only_by_test_image_manager():
    repository = Path(__file__).resolve().parents[5]
    roots = (
        repository / "src" / "main" / "python",
        repository / "src" / "test" / "support" / "python",
        repository / "tools",
    )
    owners = []
    for root in roots:
        for path in root.rglob("*.py"):
            if ".images.pull(" in path.read_text(encoding="utf-8"):
                owners.append(path.relative_to(repository).as_posix())

    assert owners == [
        "src/test/support/python/repomap_test_support/resource_test_images.py"
    ]
