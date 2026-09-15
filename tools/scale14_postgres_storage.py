"""Exact PostgreSQL PGDATA and backing-space sampling for SCALE14."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
from typing import Callable, Mapping, Sequence


PGDATA_CONTAINER_PATH = "/var/lib/postgresql/data"
_METRIC_CODE = "postgresql_pgdata_allocated_delta"
_PUBLIC_SCOPE = "owned_postgresql_pgdata"
_RUN_TIMEOUT_SECONDS = 1.0


def read_allocated_tree_bytes(root: Path) -> int | None:
    """Return allocated bytes beneath one local bind root without following links."""

    try:
        root_stat = root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode):
            return None
        pending = [root]
        seen: set[tuple[int, int]] = set()
        allocated = 0
        while pending:
            path = pending.pop()
            path_stat = path.lstat()
            identity = (path_stat.st_dev, path_stat.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            blocks = getattr(path_stat, "st_blocks", None)
            if isinstance(blocks, bool) or not isinstance(blocks, int) or blocks < 0:
                return None
            allocated += blocks * 512
            if stat.S_ISDIR(path_stat.st_mode):
                with os.scandir(path) as entries:
                    pending.extend(Path(entry.path) for entry in entries)
        return allocated
    except OSError:
        return None


def read_backing_free_bytes(root: Path) -> int | None:
    """Return exact free bytes for the filesystem backing one local bind root."""

    try:
        root_stat = root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode):
            return None
        free_bytes = shutil.disk_usage(root).free
    except OSError:
        return None
    return free_bytes if isinstance(free_bytes, int) and free_bytes >= 0 else None


class PostgresStorageError(ValueError):
    """Raised when exact PostgreSQL storage ownership cannot be established."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "resource_reader_unavailable",
    ) -> None:
        self.category = category
        super().__init__(message)


@dataclass(frozen=True)
class PostgresStorageSample:
    """One public-safe exact-scope PGDATA storage observation."""

    metric_code: str
    scope: str
    baseline_bytes: int | None
    current_bytes: int | None
    delta_bytes: int | None
    free_bytes: int | None
    availability: str
    upper_bound: bool
    sampling_elapsed_ns: int

    def to_payload(self) -> dict[str, object]:
        """Return a bounded projection without runtime or filesystem identity."""

        return {
            "schema_version": 1,
            "metric_code": self.metric_code,
            "scope": self.scope,
            "baseline_bytes": self.baseline_bytes,
            "current_bytes": self.current_bytes,
            "delta_bytes": self.delta_bytes,
            "free_bytes": self.free_bytes,
            "availability": self.availability,
            "upper_bound": self.upper_bound,
            "sampling_elapsed_ns": self.sampling_elapsed_ns,
        }


class PostgresStorageAuthority:
    """Validate one owned PGDATA bind and sample its allocated and free bytes."""

    def __init__(
        self,
        plan,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        allocated_reader: Callable[[Path], int | None] = read_allocated_tree_bytes,
        free_reader: Callable[[Path], int | None] = read_backing_free_bytes,
    ) -> None:
        _validate_plan(plan)
        self._plan = plan
        self._runner = runner
        self._clock_ns = clock_ns
        self._allocated_reader = allocated_reader
        self._free_reader = free_reader
        self._data_root = Path(_normalized_path(plan.postgres_data_dir))
        self._baseline_bytes: int | None = None
        self._scope_fingerprint: tuple[str, ...] | None = None

    def capture_baseline(self) -> PostgresStorageSample:
        """Capture the settled PGDATA counter used by later delta samples."""

        sample = self._capture(require_baseline=False)
        if sample.availability == "available":
            assert sample.current_bytes is not None
            self._baseline_bytes = sample.current_bytes
            return PostgresStorageSample(
                sample.metric_code,
                sample.scope,
                sample.current_bytes,
                sample.current_bytes,
                0,
                sample.free_bytes,
                sample.availability,
                sample.upper_bound,
                sample.sampling_elapsed_ns,
            )
        return sample

    def capture(self) -> PostgresStorageSample:
        """Capture one current exact-scope storage delta and free-space floor."""

        return self._capture(require_baseline=True)

    def _capture(self, *, require_baseline: bool) -> PostgresStorageSample:
        started_ns = self._clock_ns()
        inspection = self._run(
            (
                self._plan.container_runtime,
                "inspect",
                self._plan.identity.postgres_container,
            )
        )
        if inspection is None:
            return self._unavailable(
                "runtime_inspection_unavailable", started_ns
            )
        fingerprint = self._validate_inspection(inspection)
        if self._scope_fingerprint is None:
            self._scope_fingerprint = fingerprint
        elif fingerprint != self._scope_fingerprint:
            raise PostgresStorageError(
                "postgresql storage scope changed",
                category="storage_scope_changed",
            )

        current_bytes = self._read_pgdata_bytes()
        if current_bytes is None:
            return self._unavailable(
                "pgdata_measurement_unavailable", started_ns
            )
        free_bytes = self._read_backing_free_bytes()
        if free_bytes is None:
            return self._unavailable(
                "backing_free_measurement_unavailable", started_ns
            )
        if require_baseline and self._baseline_bytes is None:
            return self._unavailable("baseline_unavailable", started_ns)
        baseline = self._baseline_bytes
        if baseline is None:
            baseline = current_bytes
        return PostgresStorageSample(
            _METRIC_CODE,
            _PUBLIC_SCOPE,
            baseline,
            current_bytes,
            max(0, current_bytes - baseline),
            free_bytes,
            "available",
            False,
            self._elapsed(started_ns),
        )

    def _run(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            completed = self._runner(
                tuple(arguments),
                check=False,
                capture_output=True,
                text=True,
                timeout=_RUN_TIMEOUT_SECONDS,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return completed if completed.returncode == 0 else None

    def _validate_inspection(
        self,
        completed: subprocess.CompletedProcess[str],
    ) -> tuple[str, ...]:
        try:
            documents = json.loads(completed.stdout)
            document = documents[0]
            labels = document["Config"]["Labels"]
            mounts = document["Mounts"]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise PostgresStorageError(
                "postgresql runtime inspection is invalid"
            ) from error
        expected_labels: Mapping[str, str] = self._plan.identity.labels("postgres")
        if not all(labels.get(key) == value for key, value in expected_labels.items()):
            raise PostgresStorageError("postgresql runtime labels are invalid")

        expected_source = _normalized_path(self._plan.postgres_data_dir)
        matching = [
            mount
            for mount in mounts
            if isinstance(mount, dict)
            and mount.get("Destination") == PGDATA_CONTAINER_PATH
        ]
        if len(matching) != 1:
            raise PostgresStorageError("postgresql PGDATA mount is invalid")
        mount = matching[0]
        if (
            mount.get("Type") != "bind"
            or _normalized_path(mount.get("Source")) != expected_source
            or mount.get("RW") is not True
            or "ro" in str(mount.get("Mode", "")).split(",")
        ):
            raise PostgresStorageError("postgresql PGDATA mount is invalid")
        return (
            self._plan.identity.postgres_container,
            expected_source,
            *(f"{key}={expected_labels[key]}" for key in sorted(expected_labels)),
        )

    def _read_pgdata_bytes(self) -> int | None:
        try:
            value = self._allocated_reader(self._data_root)
        except OSError:
            return None
        return _nonnegative_bytes(value)

    def _read_backing_free_bytes(self) -> int | None:
        try:
            value = self._free_reader(self._data_root)
        except OSError:
            return None
        return _nonnegative_bytes(value)

    def _unavailable(
        self,
        availability: str,
        started_ns: int,
    ) -> PostgresStorageSample:
        return PostgresStorageSample(
            _METRIC_CODE,
            _PUBLIC_SCOPE,
            self._baseline_bytes,
            None,
            None,
            None,
            availability,
            False,
            self._elapsed(started_ns),
        )

    def _elapsed(self, started_ns: int) -> int:
        finished_ns = self._clock_ns()
        if finished_ns < started_ns:
            raise PostgresStorageError("postgresql storage clock regressed")
        return finished_ns - started_ns


def _normalized_path(value: object) -> str:
    if not isinstance(value, (str, Path)):
        raise PostgresStorageError("postgresql PGDATA mount is invalid")
    path = os.fspath(value)
    if not os.path.isabs(path):
        raise PostgresStorageError("postgresql PGDATA mount is invalid")
    return os.path.normpath(path)


def _validate_plan(plan) -> None:
    if getattr(plan, "container_runtime", None) not in {"docker", "podman"}:
        raise PostgresStorageError("postgresql container runtime is invalid")
    container = getattr(getattr(plan, "identity", None), "postgres_container", None)
    if (
        not isinstance(container, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container) is None
    ):
        raise PostgresStorageError("postgresql container identity is invalid")
    _normalized_path(getattr(plan, "postgres_data_dir", None))


def _nonnegative_bytes(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


__all__ = [
    "PGDATA_CONTAINER_PATH",
    "PostgresStorageAuthority",
    "PostgresStorageError",
    "PostgresStorageSample",
    "read_allocated_tree_bytes",
    "read_backing_free_bytes",
]
