"""Private validate-before-ack event receiver for supervised refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Condition, Event, Thread, current_thread
import time
from typing import Callable, Protocol, TypeVar

from actual_refresh_failure_causality import FailureCausalityAuthority
from actual_refresh_startup import StartupReadinessError


Frame = TypeVar("Frame", covariant=True)
_RECEIVE_TIMEOUT_SECONDS = 0.25
_CLOSE_TIMEOUT_SECONDS = 1.0


class _EventChannel(Protocol[Frame]):
    def receive(
        self,
        *,
        timeout_seconds: float,
        validator: Callable[[Frame], None] | None = None,
        readiness: Callable[[], None] | None = None,
    ) -> Frame: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class _Failure:
    error: BaseException


@dataclass(frozen=True)
class _Activity:
    pass


class ActualRefreshEventPump:
    """Own the sole background receive and validate-before-ack authority."""

    def __init__(
        self,
        channel: _EventChannel[Frame],
        validator: Callable[[Frame], None],
        failure_handler: Callable[[BaseException], None] | None = None,
        *,
        failure_causality: FailureCausalityAuthority | None = None,
        child_released: Callable[[], bool] | None = None,
    ) -> None:
        self._channel = channel
        self._validator = validator
        self._failure_handler = failure_handler
        self._failure_causality = failure_causality
        self._child_released = child_released
        self._items: Queue[_Activity | _Failure] = Queue(maxsize=1)
        self._condition = Condition()
        self._ready = False
        self._done = False
        self._first_failure: BaseException | None = None
        self._terminal_eof: EOFError | None = None
        self._closing = Event()
        self._thread: Thread | None = None

    def start(self, *, timeout_seconds: float) -> None:
        """Start the receiver and wait until it enters the receive boundary."""

        if self._thread is not None:
            raise StartupReadinessError("startup event receiver is already started")
        self._thread = Thread(
            target=self._consume,
            name="actual-refresh-event-pump",
            daemon=False,
        )
        try:
            self._thread.start()
        except RuntimeError as error:
            self._thread = None
            raise StartupReadinessError(
                "startup event receiver could not start"
            ) from error
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while not self._ready and not self._done:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            if self._ready:
                return
        self.close()
        raise StartupReadinessError("startup event receiver readiness failed")

    def receive(self, *, timeout_seconds: float) -> bool:
        """Return one coalesced notification of validated event activity."""

        with self._condition:
            first_failure = self._first_failure
        if first_failure is not None:
            raise first_failure

        try:
            item = self._items.get(timeout=timeout_seconds)
        except Empty as error:
            with self._condition:
                first_failure = self._first_failure
            if first_failure is not None:
                raise first_failure
            raise TimeoutError from error
        if isinstance(item, _Failure):
            raise item.error
        return True

    def wait_done(self, *, timeout_seconds: float) -> bool:
        """Wait a bounded interval for the lifetime receiver to settle."""

        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while not self._done:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self) -> None:
        """Close the channel and wait for the receiver thread to terminate."""

        first_close = not self._closing.is_set()
        self._closing.set()
        if first_close:
            self._channel.close()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(_CLOSE_TIMEOUT_SECONDS)
            if thread.is_alive():
                raise StartupReadinessError("startup event receiver did not close")

    def take_failure(self) -> BaseException | None:
        """Return the persistent initial failure without exposing frames."""

        try:
            item = self._items.get_nowait()
        except Empty:
            item = None
        if isinstance(item, _Failure):
            return item.error
        with self._condition:
            return self._first_failure

    def terminal_eof(self) -> EOFError | None:
        """Return a physically observed event-channel EOF, if any."""

        with self._condition:
            return self._terminal_eof

    def _consume(self) -> None:
        try:
            while not self._closing.is_set():
                try:
                    frame = self._channel.receive(
                        timeout_seconds=_RECEIVE_TIMEOUT_SECONDS,
                        validator=self._validator,
                        readiness=self._mark_ready,
                    )
                except TimeoutError:
                    continue
                except BaseException as error:
                    if not self._closing.is_set():
                        if not isinstance(error, EOFError):
                            self._record_failure_creation(error)
                            self._handle_failure(error)
                        self._publish_failure(error)
                        if not isinstance(error, EOFError):
                            self._await_terminal_eof()
                    return
                del frame
                self._publish_activity()
        finally:
            with self._condition:
                self._done = True
                self._condition.notify_all()

    def _mark_ready(self) -> None:
        with self._condition:
            self._ready = True
            self._condition.notify_all()

    def _publish_failure(self, error: BaseException) -> None:
        publish = False
        with self._condition:
            if self._first_failure is None:
                self._first_failure = error
                publish = True
            if isinstance(error, EOFError):
                self._terminal_eof = error
            self._condition.notify_all()
        if not publish:
            return
        try:
            self._items.get_nowait()
        except Empty:
            pass
        self._items.put_nowait(_Failure(error))

    def _handle_failure(self, error: BaseException) -> None:
        if self._failure_handler is None:
            return
        self._failure_handler(error)

    def _record_failure_creation(self, error: BaseException) -> None:
        if self._failure_causality is None:
            return
        released = True if self._child_released is None else self._child_released()
        code = getattr(getattr(error, "code", None), "value", None)
        code = code or getattr(error, "category", None)
        self._failure_causality.record_exception(
            error,
            code=code or "event_transport_failed",
            authority_owner="event_transport",
            lifecycle_boundary=("active_event_receive" if released else "startup"),
            existed_before_child_release=not released,
            test_injected=bool(getattr(error, "test_injected", False)),
        )

    def _await_terminal_eof(self) -> None:
        while not self._closing.is_set():
            try:
                self._channel.receive(
                    timeout_seconds=_RECEIVE_TIMEOUT_SECONDS,
                    validator=_reject_late_frame,
                )
            except TimeoutError:
                continue
            except EOFError as error:
                if not self._closing.is_set():
                    self._publish_failure(error)
                return
            except BaseException:
                continue

    def _publish_activity(self) -> None:
        try:
            self._items.put_nowait(_Activity())
        except Full:
            pass


def _reject_late_frame(_frame: object) -> None:
    raise ValueError("event stream continued after semantic rejection")


__all__ = ["ActualRefreshEventPump"]
