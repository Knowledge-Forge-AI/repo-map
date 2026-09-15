from __future__ import annotations

import json
import hashlib
import multiprocessing
import os
from pathlib import Path
from types import SimpleNamespace

from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_test_images import TestImageManager as ImageManager


BASE_REFERENCE = "python:3.12-slim-bookworm@sha256:" + "c" * 64
BASE_CANONICAL_REFERENCE = "python@sha256:" + "c" * 64
BASE_ID = "sha256:" + "b" * 64
BRIDGE_ID = "d" * 64
RUNTIME_ID = "sha256:" + "a" * 64
_CHILD_ERROR_CATEGORIES = (
    "failure_compensation_refused",
    "identity_or_state_validation_refused",
    "remove_api_rejected",
    "remove_absence_unproved",
    "remove_returned_container_present",
    "managed_runtime_build_cleanup_failed",
)
_CHILD_ERROR_TYPES = {
    "AssertionError",
    "AttributeError",
    "RuntimeMaterializationError",
    "TestImageError",
}


class SharedImage:
    def __init__(self, identity, *, tags=(), labels=None, repo_digests=()):
        self.id = identity
        self.tags = list(tags)
        self.attrs = {
            "Architecture": "arm64",
            "Created": "2026-08-16T12:00:00Z",
            "Size": 1,
            "RepoDigests": list(repo_digests),
            "Config": {"Labels": dict(labels or {})},
        }


class SharedImages:
    def __init__(self, root: Path):
        self.root = root

    def _base(self):
        return SharedImage(BASE_ID, repo_digests=(BASE_CANONICAL_REFERENCE,))

    def _runtime(self):
        record = json.loads(self.root.joinpath("runtime.json").read_text())
        return SharedImage(
            RUNTIME_ID, tags=(record["tag"],), labels=record["labels"]
        )

    def list(self, all=False):
        del all
        images = []
        if self.root.joinpath("base-ready").exists():
            images.append(self._base())
        if self.root.joinpath("runtime.json").exists():
            images.append(self._runtime())
        return images

    def get(self, reference):
        if self.root.joinpath("base-ready").exists() and reference in {
            BASE_REFERENCE,
            BASE_CANONICAL_REFERENCE,
            BASE_ID,
        }:
            return self._base()
        if self.root.joinpath("runtime.json").exists():
            runtime = self._runtime()
            if reference in {runtime.id, *runtime.tags}:
                return runtime
        raise type("NotFound", (Exception,), {})(reference)

    def pull(self, reference):
        assert reference == BASE_CANONICAL_REFERENCE
        with self.root.joinpath("pulls.log").open("a") as stream:
            stream.write(reference + "\n")
        self.root.joinpath("base-ready").touch()
        return self._base()

    def remove(self, identity, *, force, noprune):
        raise AssertionError((identity, force, noprune))


class SharedContainer:
    def __init__(self, root: Path, identity: str, record: dict):
        self.root = root
        self.id = identity
        self.record = record
        self.image = SimpleNamespace(id=record["image"])
        self.attrs = {
            "Config": {"Labels": record["labels"]},
            "Image": record["image"],
            "Mounts": [],
            "Name": f"/{record['name']}",
            "NetworkSettings": {
                "Networks": {"bridge": {"NetworkID": BRIDGE_ID}}
            },
            "HostConfig": {
                "AutoRemove": False,
                "NetworkMode": record["network_mode"],
                "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            },
            "State": dict(record["state"]),
        }

    def _persist_state(self):
        path = self.root.joinpath("container.json")
        record = json.loads(path.read_text())
        assert record["identity"] == self.id
        record["state"] = dict(self.attrs["State"])
        path.write_text(json.dumps(record))

    def reload(self):
        return None

    def start(self):
        self.attrs["State"].update(Status="running", Running=True)
        self._persist_state()

    def wait(self, *, timeout):
        assert timeout == 900
        self.attrs["State"].update(Status="exited", Running=False, ExitCode=0)
        self._persist_state()
        return {"StatusCode": 0}

    def stop(self, *, timeout):
        assert timeout == 10
        self.attrs["State"].update(Status="exited", Running=False)
        self._persist_state()

    def logs(self, *, stdout, stderr):
        return b""

    def commit(self, *, repository, tag, conf):
        labels = {**self.record["labels"], **dict(conf["Labels"])}
        full_tag = f"{repository}:{tag}"
        self.root.joinpath("runtime.json").write_text(
            json.dumps({"tag": full_tag, "labels": labels})
        )
        with self.root.joinpath("builds.log").open("a") as stream:
            stream.write(full_tag + "\n")
        return SharedImage(RUNTIME_ID, tags=(full_tag,), labels=labels)

    def remove(self, *, force, v):
        assert force is True
        assert v is False
        assert self.attrs["State"] == {
            "Status": "exited",
            "Running": False,
            "Paused": False,
            "Restarting": False,
            "Dead": False,
            "ExitCode": 0,
        }
        path = self.root.joinpath("container.json")
        record = json.loads(path.read_text())
        assert record["identity"] == self.id
        with self.root.joinpath("removals.log").open("a") as stream:
            stream.write(f"status=exited,force={force},v={v}\n")
        path.unlink()


class SharedContainers:
    def __init__(self, root: Path):
        self.root = root

    def create(self, image, command, *, labels, entrypoint, name, network_mode):
        assert image == BASE_ID
        assert command[0] == "-c"
        assert entrypoint == ["python"]
        assert network_mode == "bridge"
        identity = hashlib.sha256(f"{os.getpid()}:{name}".encode()).hexdigest()
        record = {
            "identity": identity,
            "image": image,
            "labels": labels,
            "name": name,
            "network_mode": network_mode,
            "state": {
                "Status": "created",
                "Running": False,
                "Paused": False,
                "Restarting": False,
                "Dead": False,
                "ExitCode": 0,
            },
        }
        self.root.joinpath("container.json").write_text(json.dumps(record))
        return SharedContainer(self.root, identity, record)

    def get(self, identity):
        path = self.root.joinpath("container.json")
        if path.exists():
            record = json.loads(path.read_text())
            if identity in {record["identity"], record["name"]}:
                return SharedContainer(self.root, record["identity"], record)
        raise type("NotFound", (Exception,), {})(identity)

    def list(self, all=False):
        del all
        path = self.root.joinpath("container.json")
        if not path.exists():
            return []
        record = json.loads(path.read_text())
        return [SharedContainer(self.root, record["identity"], record)]


class SharedClient:
    def __init__(self, root: Path):
        self.images = SharedImages(root)
        self.containers = SharedContainers(root)
        bridge = SimpleNamespace(
            id=BRIDGE_ID,
            attrs={
                "Id": BRIDGE_ID,
                "Name": "bridge",
                "Driver": "bridge",
                "Scope": "local",
                "Internal": False,
                "Options": {"com.docker.network.bridge.default_bridge": "true"},
            },
            reload=lambda: None,
        )
        self.networks = SimpleNamespace(get=lambda name: bridge)

    def info(self):
        return {"Architecture": "arm64"}


def _bounded_child_error(error: Exception) -> tuple[str, str, str]:
    error_text = str(error)
    category = next(
        (item for item in _CHILD_ERROR_CATEGORIES if item in error_text),
        "unclassified_lifecycle_error",
    )
    error_type = type(error).__name__
    if error_type not in _CHILD_ERROR_TYPES:
        error_type = "Exception"
    return ("error", error_type, category)


def _ensure_in_process(root_value: str, ordinal: int, queue) -> None:
    root = Path(root_value)
    run_root = root / f"run-{ordinal}"
    run_root.mkdir()
    ledger = ResourceLedger.create(
        run_root / "ledger.json",
        RunIdentity("repo-map", "TEST-IMAGE-LIFECYCLE1-R1", f"run-{ordinal}"),
    )
    manager = ImageManager(
        repo_root=root / "repo",
        resource_run=SimpleNamespace(ledger=ledger),
        client=SharedClient(root),
        base_reference=BASE_REFERENCE,
        python_base_family="python:3.12-slim-bookworm",
        python_version="3.12.13",
        psycopg_release_version="3.2.12",
        probe=lambda _identity: None,
    )
    try:
        queue.put(("ok", manager.ensure_runtime_image()))
    except Exception as error:
        queue.put(_bounded_child_error(error))


def test_process_concurrent_ensure_pulls_and_builds_once(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    repo.joinpath("pyproject.toml").write_text(
        """[project]
name = "fixture"
version = "0.1"
dependencies = ["psycopg[binary]==3.2.12", "typing-extensions==4.16.0"]
"""
    )
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    processes = [
        context.Process(target=_ensure_in_process, args=(str(tmp_path), index, queue))
        for index in (1, 2)
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=20) for _process in processes]
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    child_errors = [result for result in results if result[0] != "ok"]
    assert child_errors == [], f"bounded child failures: {child_errors!r}"
    assert results == [("ok", RUNTIME_ID), ("ok", RUNTIME_ID)]
    assert tmp_path.joinpath("pulls.log").read_text().splitlines() == [
        BASE_CANONICAL_REFERENCE
    ]
    assert len(tmp_path.joinpath("builds.log").read_text().splitlines()) == 1
    assert tmp_path.joinpath("removals.log").read_text().splitlines() == [
        "status=exited,force=True,v=False"
    ]
    assert not tmp_path.joinpath("container.json").exists()
