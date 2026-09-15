from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity

class NotFound(Exception):
    pass


class FakeContainer:
    def __init__(
        self,
        identity: str,
        labels: dict[str, str],
        *,
        volume_mount: bool = False,
        remove_error: Exception | None = None,
    ) -> None:
        self.id = identity
        self.labels = dict(labels)
        self.image = SimpleNamespace(id="sha256:test-image")
        mounts = [{"Type": "volume", "Name": "anon-vol"}] if volume_mount else []
        self.attrs = {
            "Config": {"Labels": self.labels},
            "Image": "sha256:test-image",
            "Mounts": mounts,
        }
        self.removed = False
        self.remove_error = remove_error

    def remove(self, **kwargs: Any) -> None:
        del kwargs
        if self.remove_error is not None:
            raise self.remove_error
        self.removed = True


class FakeContainers:
    def __init__(self, preexisting: tuple[FakeContainer, ...] = ()) -> None:
        self.objects_by_id: dict[str, FakeContainer] = {c.id: c for c in preexisting}
        self.objects_by_name: dict[str, FakeContainer] = {}

    def list(self, all: bool = False) -> list[FakeContainer]:
        del all
        return [c for c in self.objects_by_id.values() if not c.removed]

    def get(self, identity_or_name: str) -> FakeContainer:
        if identity_or_name in self.objects_by_id:
            c = self.objects_by_id[identity_or_name]
            if not c.removed:
                return c
        if identity_or_name in self.objects_by_name:
            c = self.objects_by_name[identity_or_name]
            if not c.removed:
                return c
        raise NotFound(f"container {identity_or_name} not found")

    def register(self, name: str, container: FakeContainer) -> None:
        self.objects_by_id[container.id] = container
        self.objects_by_name[name] = container


class FakeDockerClient:
    def __init__(self, preexisting: tuple[FakeContainer, ...] = ()) -> None:
        self.containers = FakeContainers(preexisting)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _make_resource_run(tmp_path: Path) -> SimpleNamespace:
    identity = RunIdentity("repo-map_dev", "TEST-GROUP-K", "run-1")
    ledger_path = tmp_path / "ledger.json"
    ledger = ResourceLedger.create(ledger_path, identity)
    return SimpleNamespace(ledger=ledger)


def _make_entry(condition_id: str = "K09") -> SimpleNamespace:
    return SimpleNamespace(
        condition_id=condition_id,
    )
