"""Private startup readiness authority for supervised actual refreshes."""

from __future__ import annotations

from enum import Enum
import os
import select
from typing import Sequence


_RELEASE_TOKEN = b"R"
_DEFAULT_CHILD_TIMEOUT_SECONDS = 30.0


class StartupState(str, Enum):
    """Closed parent-side startup readiness states."""

    CONSTRUCTED = "constructed"
    STORAGE_BASELINE_READY = "storage_baseline_ready"
    BACKEND_OBSERVER_READY = "backend_observer_ready"
    RESOURCE_AUTHORITIES_READY = "resource_authorities_ready"
    EVENT_RECEIVER_READY = "event_receiver_ready"
    FAILURE_COLLECTOR_READY = "failure_collector_ready"
    CHILD_RELEASED = "child_released"
    MONITORING = "monitoring"
    FAILED = "failed"
    CLOSED = "closed"


class StartupReadinessError(RuntimeError):
    """Report one bounded parent-side startup readiness failure."""

    category = "startup_readiness_failed"


class StartupChildError(RuntimeError):
    """Report one bounded child-side startup wait failure."""


class ActualRefreshStartup:
    """Own one private inherited pipe gate and its readiness state machine."""

    def __init__(
        self,
        read_descriptor: int,
        write_descriptor: int,
        *,
        child_timeout_seconds: float,
    ) -> None:
        self._read_descriptor: int | None = read_descriptor
        self._write_descriptor: int | None = write_descriptor
        self._child_timeout_seconds = child_timeout_seconds
        self._state = StartupState.CONSTRUCTED

    @classmethod
    def create(
        cls,
        *,
        child_timeout_seconds: float = _DEFAULT_CHILD_TIMEOUT_SECONDS,
    ) -> ActualRefreshStartup:
        """Create one parent/child pipe gate with a bounded child wait."""

        if (
            isinstance(child_timeout_seconds, bool)
            or not isinstance(child_timeout_seconds, (int, float))
            or not 0 < child_timeout_seconds <= 60
        ):
            raise StartupReadinessError("startup child timeout is invalid")
        read_descriptor, write_descriptor = os.pipe()
        return cls(
            read_descriptor,
            write_descriptor,
            child_timeout_seconds=float(child_timeout_seconds),
        )

    @property
    def state(self) -> StartupState:
        """Return the current public-safe readiness state."""

        return self._state

    @property
    def child_timeout_seconds(self) -> float:
        """Return the bounded child bootstrap timeout."""

        return self._child_timeout_seconds

    @property
    def child_descriptor(self) -> int:
        """Return the inherited child descriptor before launch."""

        if self._read_descriptor is None:
            raise StartupReadinessError(
                "startup child descriptor is unavailable"
            )
        return self._read_descriptor

    @property
    def released(self) -> bool:
        """Return whether the child has received release authority."""

        return self._state in {
            StartupState.CHILD_RELEASED,
            StartupState.MONITORING,
        }

    def child_started(self) -> None:
        """Close the parent's copy of the inherited child descriptor."""

        if self._read_descriptor is None:
            raise StartupReadinessError(
                "startup child descriptor is unavailable"
            )
        os.close(self._read_descriptor)
        self._read_descriptor = None

    def mark_storage_baseline_ready(self) -> None:
        self._advance(
            StartupState.CONSTRUCTED,
            StartupState.STORAGE_BASELINE_READY,
        )

    def mark_backend_observer_ready(self) -> None:
        self._advance(
            StartupState.STORAGE_BASELINE_READY,
            StartupState.BACKEND_OBSERVER_READY,
        )

    def mark_resource_authorities_ready(self) -> None:
        self._advance(
            StartupState.BACKEND_OBSERVER_READY,
            StartupState.RESOURCE_AUTHORITIES_READY,
        )

    def mark_event_receiver_ready(self) -> None:
        self._advance(
            StartupState.RESOURCE_AUTHORITIES_READY,
            StartupState.EVENT_RECEIVER_READY,
        )

    def mark_failure_collector_ready(self) -> None:
        self._advance(
            StartupState.EVENT_RECEIVER_READY,
            StartupState.FAILURE_COLLECTOR_READY,
        )

    def release(self) -> None:
        """Release the child exactly once after every authority is ready."""

        if self._state is not StartupState.FAILURE_COLLECTOR_READY:
            raise StartupReadinessError("startup readiness order is invalid")
        descriptor = self._write_descriptor
        if descriptor is None:
            raise StartupReadinessError("startup release descriptor is closed")
        try:
            written = os.write(descriptor, _RELEASE_TOKEN)
        except OSError as error:
            self.fail()
            raise StartupReadinessError("startup child release failed") from error
        finally:
            self._close_write_descriptor()
        if written != len(_RELEASE_TOKEN):
            self._state = StartupState.FAILED
            raise StartupReadinessError("startup child release failed")
        self._state = StartupState.CHILD_RELEASED

    def mark_monitoring(self) -> None:
        self._advance(StartupState.CHILD_RELEASED, StartupState.MONITORING)

    def fail(self) -> None:
        """Close the gate without granting product execution authority."""

        if self._read_descriptor is not None:
            os.close(self._read_descriptor)
            self._read_descriptor = None
        self._close_write_descriptor()
        if self._state is not StartupState.CLOSED:
            self._state = StartupState.FAILED

    def close(self) -> None:
        """Close every descriptor owned by the parent."""

        if self._read_descriptor is not None:
            os.close(self._read_descriptor)
            self._read_descriptor = None
        self._close_write_descriptor()
        self._state = StartupState.CLOSED

    def _advance(self, expected: StartupState, target: StartupState) -> None:
        if self._state is not expected:
            raise StartupReadinessError("startup readiness order is invalid")
        self._state = target

    def _close_write_descriptor(self) -> None:
        if self._write_descriptor is not None:
            os.close(self._write_descriptor)
            self._write_descriptor = None


def wait_for_startup_release(
    descriptor: int,
    *,
    timeout_seconds: float,
) -> None:
    """Wait for one exact release token and always close the descriptor."""

    if (
        isinstance(descriptor, bool)
        or not isinstance(descriptor, int)
        or descriptor < 0
    ):
        raise StartupChildError("startup descriptor is invalid")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < timeout_seconds <= 60
    ):
        raise StartupChildError("startup timeout is invalid")
    try:
        ready, _, _ = select.select([descriptor], [], [], timeout_seconds)
        if not ready:
            raise StartupChildError("startup gate timed out")
        try:
            token = os.read(descriptor, len(_RELEASE_TOKEN))
        except OSError as error:
            raise StartupChildError("startup gate read failed") from error
        if token == b"":
            raise StartupChildError("startup gate closed before release")
        if token != _RELEASE_TOKEN:
            raise StartupChildError("startup release token is invalid")
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def validate_actual_refresh_arguments(arguments: Sequence[str]) -> tuple[str, ...]:
    """Validate the closed product and test-support refresh argv forms."""

    argv = tuple(arguments)
    ordinary_child = len(argv) >= 5 and argv[1:5] == (
        "-m",
        "repomap_kg",
        "ops",
        "refresh-graph",
    )
    separator = argv.index("--") if "--" in argv[3:] else -1
    test_child = (
        len(argv) >= 8
        and argv[1:3]
        == ("-m", "repomap_test_support.scale14_actual_refresh_child")
        and separator >= 0
        and argv[separator + 1 : separator + 3] == ("ops", "refresh-graph")
    )
    if not ordinary_child and not test_child:
        raise StartupReadinessError("actual refresh argument vector is invalid")
    if not all(isinstance(argument, str) and argument for argument in argv):
        raise StartupReadinessError("actual refresh argument vector is invalid")
    return argv


__all__ = [
    "ActualRefreshStartup",
    "StartupChildError",
    "StartupReadinessError",
    "StartupState",
    "validate_actual_refresh_arguments",
    "wait_for_startup_release",
]
