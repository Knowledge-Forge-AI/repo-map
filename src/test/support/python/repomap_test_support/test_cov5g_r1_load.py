"""Exact-scope bounded load contexts for TEST-COV5G-R1."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
from threading import Event, Thread
import time

import psycopg
from psycopg.conninfo import make_conninfo

from repomap_test_support.test_cov5g_r1_characterization import Condition


LOAD_DURATION_SECONDS = 25.0
CPU_WORKER_COUNT = 2
FILESYSTEM_WORKER_COUNT = 1
CONTAINER_WORKER_COUNT = 1
CHURN_WORKER_COUNT = 1


@dataclass(frozen=True, slots=True)
class ExactContainerHandle:
    """One disposable harness-returned container handle."""

    runtime: str
    name: str


class BoundedConditionLoad(AbstractContextManager["BoundedConditionLoad"]):
    """Own fixed-count, fixed-duration test load and exact cleanup."""

    def __init__(
        self,
        condition: Condition,
        *,
        parameters: dict[str, object],
        filesystem_root: Path,
        container: ExactContainerHandle,
    ) -> None:
        self.condition = condition
        self.parameters = parameters
        self.filesystem_root = filesystem_root
        self.container = container
        self._deadline = 0.0
        self._stop = Event()
        self._threads: list[Thread] = []
        self._errors: list[BaseException] = []

    def __enter__(self) -> "BoundedConditionLoad":
        self._deadline = time.monotonic() + LOAD_DURATION_SECONDS
        targets = {
            Condition.CPU: [self._cpu_worker] * CPU_WORKER_COUNT,
            Condition.FILESYSTEM_CONTAINER: (
                [self._filesystem_worker] * FILESYSTEM_WORKER_COUNT
                + [self._container_worker] * CONTAINER_WORKER_COUNT
            ),
            Condition.CONNECTION_CHURN: [self._churn_worker]
            * CHURN_WORKER_COUNT,
        }.get(self.condition, [])
        for index, target in enumerate(targets):
            thread = Thread(
                target=self._guarded,
                args=(target,),
                name=f"cov5g-r1-load-{self.condition.value}-{index}",
            )
            thread.start()
            self._threads.append(thread)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._threads:
            remaining = self._deadline - time.monotonic()
            if remaining > 0:
                self._stop.wait(remaining)
        self._stop.set()
        for thread in self._threads:
            thread.join(5.0)
            if thread.is_alive():
                raise AssertionError("TEST-COV5G-R1 load worker was abandoned")
        if self._errors:
            raise AssertionError("TEST-COV5G-R1 load worker failed") from (
                self._errors[0]
            )

    def _guarded(self, target) -> None:
        try:
            target()
        except BaseException as error:
            self._errors.append(error)
            self._stop.set()

    def _active(self) -> bool:
        return not self._stop.is_set() and time.monotonic() < self._deadline

    def _cpu_worker(self) -> None:
        payload = b"TEST-COV5G-R1 bounded CPU contention"
        while self._active():
            for _index in range(2_000):
                payload = hashlib.sha256(payload).digest()

    def _filesystem_worker(self) -> None:
        target = self.filesystem_root / "bounded-contention.bin"
        payload = b"TEST-COV5G-R1" * 4_096
        while self._active():
            target.write_bytes(payload)
            if target.read_bytes() != payload:
                raise AssertionError("bounded filesystem payload changed")
        target.unlink(missing_ok=True)

    def _container_worker(self) -> None:
        command = [
            self.container.runtime,
            "exec",
            self.container.name,
            "true",
        ]
        while self._active():
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise AssertionError("exact-scope container command failed")
            self._stop.wait(0.02)

    def _churn_worker(self) -> None:
        conninfo = make_conninfo(**{str(k): str(v) for k, v in self.parameters.items()})
        while self._active():
            with psycopg.connect(
                conninfo,
                autocommit=True,
                application_name="cov5g_r1_unrelated_churn",
            ) as connection:
                connection.execute("SELECT 1").fetchone()
            self._stop.wait(0.01)
