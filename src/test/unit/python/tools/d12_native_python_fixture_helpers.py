"""Shared ADR 0102 component unit fixtures: the retained native ARM observation and Docker-free lifecycle doubles.

The retained 143162-byte ARM report is public test-only source data. It never supplies AMD imports, AMD sizing or
native qualification; AMD cases built here are refusals only. No double reaches a real Docker daemon.
"""

from __future__ import annotations

import copy
from functools import lru_cache
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from common_lore_index.runtime import python_payload as payload
from repomap_test_support import d12_native_python_proof as proof
from repomap_test_support.resource_docker_operation_records import DERIVED_OPERATION_FIELDS
from repomap_test_support.resource_ledger import CleanupResult, FinalPresence, ResourceKind

ROOT = Path(__file__).resolve().parents[5]
FIXTURE = Path(__file__).with_name("d12_native_python_report_fixture.json")
FIXTURE_BYTES = 143_162
ARM, AMD = "linux/arm64", "linux/amd64"
ARM_TK = f"{payload.DYNLOAD}/_tkinter.cpython-312-aarch64-linux-gnu.so"
CONTAINER_ID = "f" * 64
ZERO = dict.fromkeys(DERIVED_OPERATION_FIELDS, 0)
CURRENT_ARM_EXCLUSION = payload.PYTHON_PAYLOAD_EXCLUSIONS["arm64"]


@lru_cache(maxsize=1)
def _loaded() -> dict[str, Any]:
    data = FIXTURE.read_bytes()
    assert len(data) == FIXTURE_BYTES, len(data)
    return dict(json.loads(data)["observation"])


def observation() -> dict[str, Any]:
    # A synthetic current-pin variant for validator mechanics. The historical fixture remains byte-for-byte intact.
    result = copy.deepcopy(_loaded())
    exclusion = result["trimmed_report"]["exclusion"]
    entry = CURRENT_ARM_EXCLUSION
    exclusion.update(python_index=entry.python_index, platform_manifest=entry.platform_manifest,
                     python_config=entry.python_config)
    return result


def raw_and_inner() -> tuple[dict[str, Any], dict[str, Any]]:
    """The inner probe's two records, rebuilt from the retained ARM observation (interpreter facts as observed)."""
    obs = observation()
    inner = {"python_version": obs["python_version"], "python_banner": obs["python_banner"], "machine": "aarch64",
             "rc_raw": 1, "rc_trimmed": 0, "default_enrolled": obs["default_enrolled"],
             "default_matches": obs["default_enrolled"], "entry_delta": obs["entry_delta"], "removed": [ARM_TK],
             "modified_survivors": obs["modified_survivors"], "trimmed_report": obs["trimmed_report"]}
    return {"rc": 1, "report": obs["raw_report"]}, inner


def capture(raw: Any = None, inner: Any = None, *, extra: str = "") -> bytes:
    lines = [] if raw is None else [proof.RAW_PREFIX + json.dumps(raw, sort_keys=True)]
    lines += [] if inner is None else [proof.INNER_PREFIX + json.dumps(inner, sort_keys=True)]
    return ("\n".join(lines) + "\n" + extra).encode("utf-8")


def image_attrs(platform: str = ARM) -> dict[str, Any]:
    hierarchy = proof.verify_hierarchy(proof.read_envelope(ROOT), platform)
    return {"Id": hierarchy["config"], "RepoDigests": [f"python@{hierarchy['index']}"], "Os": "linux",
            "Architecture": hierarchy["architecture"], "RootFS": {"Type": "layers", "Layers": hierarchy["diff_ids"]}}


class Ledger:
    def __init__(self) -> None:
        self.rows: dict[str, SimpleNamespace] = {}

    @property
    def records(self) -> tuple[SimpleNamespace, ...]:
        return tuple(self.rows.values())

    def get(self, kind: ResourceKind, identity: str) -> SimpleNamespace:
        assert kind is ResourceKind.DOCKER_CONTAINER
        return self.rows[identity]


class World:
    """One injectable daemon, run, owner and boundary; ``fail`` maps a lifecycle step to the exception it raises."""

    def __init__(self, *, daemon: str = "aarch64", status: Any = 0, stdout: bytes | None = None,
                 attrs: dict[str, Any] | None = None, network: str = "none") -> None:
        self.events: list[str] = []
        self.fail: dict[str, BaseException] = {}
        self.ledger, self.engine, self.counts = Ledger(), set[str](), dict(ZERO)
        self.daemon, self.status, self.network = daemon, status, network
        self.stdout = capture(*raw_and_inner()) if stdout is None else stdout
        self.stderr = b"Traceback: /home/runner/private-secret " + CONTAINER_ID.encode()
        self.attrs = image_attrs() if attrs is None else attrs
        self.created: list[tuple[str, list[str], str, dict[str, Any]]] = []
        self.on_wait: Any = None
        self.rollback = True
        self.client = SimpleNamespace(info=self.info, images=SimpleNamespace(get=self.image),
                                      containers=SimpleNamespace(get=self.container))
        self.run = SimpleNamespace(ledger=self.ledger)
        self.owner = SimpleNamespace(ledger=self.ledger, create=self.create, cleanup=self.cleanup,
                                     observe_removed=self.observe_removed,
                                     verify_baseline=lambda: self.step("verify_baseline"),
                                     api=SimpleNamespace(inspect=self.inspect))
        self.boundary = SimpleNamespace(projection=self.projection)

    def projection(self) -> dict[str, Any]:
        self.step("projection")
        return dict(self.counts)

    def step(self, name: str) -> None:
        self.events.append(name)
        if name in self.fail:
            raise self.fail[name]

    def info(self) -> dict[str, Any]:
        self.step("info")
        return {"Architecture": self.daemon}

    def image(self, reference: str) -> SimpleNamespace:
        self.step("image")
        return SimpleNamespace(attrs=copy.deepcopy(self.attrs), reference=reference)

    def create(self, image: str, command: list[str], *, role: str, **options: Any) -> str:
        self.step("create")
        self.created.append((image, list(command), role, dict(options)))
        self.engine.add(CONTAINER_ID)
        self.ledger.rows[CONTAINER_ID] = SimpleNamespace(
            kind=ResourceKind.DOCKER_CONTAINER, identity=CONTAINER_ID, cleanup_result=CleanupResult.NOT_ATTEMPTED,
            final_presence=FinalPresence.UNOBSERVED, creation_observed=True)
        try:
            self.step("registered")  # a failure here models a create whose readback failed after ledgering
        except Exception:
            if self.rollback:  # the real owner's exact rollback of a generic post-ledger failure
                self.engine.discard(CONTAINER_ID)
            raise
        return CONTAINER_ID

    def container(self, identity: str) -> SimpleNamespace:
        self.step("container")
        image = self.created[-1][0]
        return SimpleNamespace(attrs={"Image": image, "HostConfig": {"NetworkMode": self.network}},
                               start=lambda: self.step("start"), wait=self.wait,
                               logs=lambda stdout, stderr: self.stdout if stdout else self.stderr)

    def wait(self, timeout: int) -> dict[str, Any]:
        self.step("wait")
        if self.on_wait is not None:
            self.on_wait(self)
        return {"StatusCode": self.status}

    def cleanup(self, identity: str) -> None:
        self.step("cleanup")
        if identity not in self.ledger.rows:  # a legacy E1 container from the explore double
            return
        self.engine.discard(identity)
        self._close(identity)

    def observe_removed(self, identity: str) -> None:
        self.step("observe_removed")
        if identity in self.engine or not self.ledger.rows[identity].creation_observed:
            raise RuntimeError("exact container remains after command")
        self._close(identity)

    def _close(self, identity: str) -> None:
        row = self.ledger.rows[identity]
        self.ledger.rows[identity] = SimpleNamespace(**{**vars(row), "cleanup_result": CleanupResult.REMOVED,
                                                         "final_presence": FinalPresence.ABSENT})

    def inspect(self, kind: ResourceKind, identity: str) -> object | None:
        return object() if identity in self.engine else None
