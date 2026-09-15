"""TEST-RUNNER-SAFETY1 current-run Docker container producer contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_ledger import ResourceKind, ResourceLedger, RunIdentity


class NotFound(Exception):
    pass


class Container:
    def __init__(self, identity, labels, collection):
        self.id = identity
        self.attrs = {"Config": {"Labels": labels}, "Image": "sha256:image", "Mounts": []}
        self.collection = collection

    def remove(self, **kwargs):
        del kwargs
        if self.collection.remove_error is not None:
            raise self.collection.remove_error
        self.collection.objects.pop(self.id, None)


class Containers:
    def __init__(self, preexisting=()):
        self.objects = {item.id: item for item in preexisting}
        self.created = []
        self.remove_error = None
        self.create_id: str | None = None
        self.create_labels: dict[str, str] | None = None

    def list(self, all=False):
        del all
        return list(self.objects.values())

    def get(self, identity):
        try:
            return self.objects[identity]
        except KeyError as error:
            raise NotFound(identity) from error

    def create(self, image, command, **kwargs):
        del image, command
        cid = getattr(self, "create_id", None) or "returned-exact-id"
        labels = getattr(self, "create_labels", None) or kwargs["labels"]
        container = Container(cid, labels, self)
        self.objects[container.id] = container
        self.created.append(container.id)
        return container


class Client:
    def __init__(self, preexisting=()):
        self.containers = Containers(preexisting)


def _run(tmp_path):
    identity = RunIdentity("repo-map_dev", "TEST-RUNNER-SAFETY1", "run-1")
    return SimpleNamespace(ledger=ResourceLedger.create(tmp_path / "ledger.json", identity))


def test_exact_returned_container_id_is_labelled_and_ledgered(tmp_path):
    run = _run(tmp_path)
    client = Client()
    owner = CurrentRunDockerContainers(run, client)

    identity = owner.create("sha256:image", ["python", "-V"], role="smoke")

    assert identity == "returned-exact-id"
    record = run.ledger.get(ResourceKind.DOCKER_CONTAINER, identity)
    assert record.creation_observed is True
    assert record.created_before_run is False
    assert client.containers.get(identity).attrs["Config"]["Labels"][
        "org.repomap.test.resource.run_id"
    ] == "run-1"


def test_registration_failure_rolls_back_only_exact_just_created_id(tmp_path, monkeypatch):
    run = _run(tmp_path)
    preexisting_collection = Containers()
    old = Container("old", {}, preexisting_collection)
    client = Client((old,))
    client.containers.objects["old"] = old
    owner = CurrentRunDockerContainers(run, client)

    def fail(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(run.ledger, "register", fail)

    with pytest.raises(RuntimeError, match="registration"):
        owner.create("sha256:image", ["python", "-V"], role="smoke")

    assert set(client.containers.objects) == {"old"}


def test_registration_and_exact_rollback_failure_is_terminal(tmp_path, monkeypatch):
    run = _run(tmp_path)
    client = Client()
    client.containers.remove_error = RuntimeError("Engine remove failed")
    owner = CurrentRunDockerContainers(run, client)

    def fail(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(run.ledger, "register", fail)

    with pytest.raises(RuntimeError, match="exact rollback failed"):
        owner.create("sha256:image", ["python", "-V"], role="smoke")

    assert set(client.containers.objects) == {"returned-exact-id"}


def test_cleanup_is_ledger_authorized_exact_and_baseline_preserving(tmp_path):
    run = _run(tmp_path)
    preexisting_collection = Containers()
    old = Container("old", {}, preexisting_collection)
    client = Client((old,))
    client.containers.objects["old"] = old
    owner = CurrentRunDockerContainers(run, client)
    identity = owner.create("sha256:image", ["python", "-V"], role="smoke")

    owner.cleanup(identity)
    owner.verify_baseline()

    assert set(client.containers.objects) == {"old"}
    assert run.ledger.public_projection()["phase_containers_remaining"] == 0
    assert run.ledger.public_projection()["pre_existing_objects_mutated"] is False


def test_preexisting_baseline_mutation_fails_closed(tmp_path):
    run = _run(tmp_path)
    preexisting_collection = Containers()
    old = Container("old", {}, preexisting_collection)
    client = Client((old,))
    actual = CurrentRunDockerContainers(run, client)
    # Simulate an unattributed actor changing a pre-existing object mid-run.
    client.containers.objects.pop("old")

    with pytest.raises(RuntimeError, match="baseline"):
        actual.verify_baseline()

    assert run.ledger.public_projection()["pre_existing_objects_mutated"] is True


def test_create_refuses_direct_removal_on_baseline_collision_and_ownership_refusal(tmp_path):
    run = _run(tmp_path)
    preexisting_collection = Containers()
    old = Container("old", {}, preexisting_collection)
    client = Client((old,))
    client.containers.objects["old"] = old
    owner = CurrentRunDockerContainers(run, client)

    # 1. Baseline collision
    client.containers.create_id = "old"
    with pytest.raises(RuntimeError, match="baseline collision; direct removal refused"):
        owner.create("sha256:image", ["python", "-V"], role="smoke")
    assert "old" in client.containers.objects, "Baseline container must not be removed"

    # 2. Ownership labels mismatch
    foreign = Container("foreign", {"org.repomap.test.resource.run_id": "other-run"}, preexisting_collection)
    client.containers.objects["foreign"] = foreign
    client.containers.create_id = "foreign"
    client.containers.create_labels = {"org.repomap.test.resource.run_id": "other-run"}
    with pytest.raises(RuntimeError, match="ownership refusal; direct removal refused"):
        owner.create("sha256:image", ["python", "-V"], role="smoke")
    assert "foreign" in client.containers.objects, "Foreign container must not be removed"
