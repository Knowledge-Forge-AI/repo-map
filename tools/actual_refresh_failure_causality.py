"""Source-sequenced failure causality for supervised actual refreshes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock
import time
from typing import Callable

from scale15_terminal_contracts import ControlFailureCode


_PUBLIC_FAILURE_CODES = frozenset(
    {candidate.value for candidate in ControlFailureCode}
    | {"threshold_limit_crossed"}
)


class FailureCausalityError(RuntimeError):
    """Raised when a causal record is invalid, conflicting, or frozen."""


@dataclass(frozen=True)
class FailureCandidate:
    """Immutable private evidence for one causally created failure."""

    code: str
    authority_owner: str
    causal_sequence: int
    observation_sequence: int | None
    monotonic_ns: int
    lifecycle_boundary: str
    existed_before_child_release: bool
    test_injected: bool
    terminal_secondary: bool
    source_event_key: str


@dataclass(frozen=True)
class FailureCausalitySnapshot:
    """Frozen ordered candidates and their public-safe projection."""

    candidates: tuple[FailureCandidate, ...]

    def public_projection(self) -> dict[str, object]:
        return {
            "order_status": "empty" if not self.candidates else "causally_ordered",
            "categories": [candidate.code for candidate in self.candidates],
        }


class FailureCausalityAuthority:
    """Assign total source order independently from callback observation order."""

    def __init__(
        self,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._clock_ns = clock_ns
        self._lock = RLock()
        self._next_causal_sequence = 1
        self._next_observation_sequence = 1
        self._by_key: dict[str, FailureCandidate] = {}
        self._by_error: dict[BaseException, FailureCandidate] = {}
        self._snapshot: FailureCausalitySnapshot | None = None

    def record_code(
        self,
        code: object,
        *,
        authority_owner: str,
        lifecycle_boundary: str,
        existed_before_child_release: bool,
        test_injected: bool = False,
        terminal_secondary: bool = False,
        source_event_key: str | None = None,
    ) -> FailureCandidate:
        """Create one candidate at its source-owned causal boundary."""

        normalized = _normalized_code(code)
        owner = _bounded_text(authority_owner, "failure authority owner")
        boundary = _bounded_text(lifecycle_boundary, "failure lifecycle boundary")
        with self._lock:
            self._require_mutable()
            key = source_event_key or f"source-{self._next_causal_sequence}"
            existing = self._by_key.get(key)
            if existing is not None:
                expected = (
                    normalized,
                    owner,
                    boundary,
                    existed_before_child_release,
                    test_injected,
                    terminal_secondary,
                )
                actual = (
                    existing.code,
                    existing.authority_owner,
                    existing.lifecycle_boundary,
                    existing.existed_before_child_release,
                    existing.test_injected,
                    existing.terminal_secondary,
                )
                if actual != expected:
                    raise FailureCausalityError("failure causal record conflicts")
                return existing
            candidate = FailureCandidate(
                normalized,
                owner,
                self._next_causal_sequence,
                None,
                self._validated_clock(),
                boundary,
                _boolean(existed_before_child_release),
                _boolean(test_injected),
                _boolean(terminal_secondary),
                _bounded_text(key, "failure source event key"),
            )
            self._next_causal_sequence += 1
            self._by_key[key] = candidate
            return candidate

    def record_exception(
        self,
        error: BaseException,
        *,
        code: object,
        authority_owner: str,
        lifecycle_boundary: str,
        existed_before_child_release: bool,
        test_injected: bool = False,
        terminal_secondary: bool = False,
    ) -> FailureCandidate:
        """Bind an exception once at creation and preserve that causal order."""

        if not isinstance(error, BaseException):
            raise FailureCausalityError("failure exception is invalid")
        with self._lock:
            existing = self._by_error.get(error)
            if existing is not None:
                expected = (
                    _normalized_code(code),
                    authority_owner,
                    lifecycle_boundary,
                    existed_before_child_release,
                    test_injected,
                    terminal_secondary,
                )
                actual = (
                    existing.code,
                    existing.authority_owner,
                    existing.lifecycle_boundary,
                    existing.existed_before_child_release,
                    existing.test_injected,
                    existing.terminal_secondary,
                )
                if actual != expected:
                    raise FailureCausalityError("failure exception binding conflicts")
                return existing
            candidate = self.record_code(
                code,
                authority_owner=authority_owner,
                lifecycle_boundary=lifecycle_boundary,
                existed_before_child_release=existed_before_child_release,
                test_injected=test_injected,
                terminal_secondary=terminal_secondary,
            )
            self._by_error[error] = candidate
            return candidate

    def observe_exception(self, error: BaseException) -> FailureCandidate | None:
        """Assign observation order without changing an exception's causal order."""

        with self._lock:
            candidate = self._by_error.get(error)
            if candidate is None:
                return None
            return self._observe(candidate)

    def observe(self, candidate: FailureCandidate) -> FailureCandidate:
        """Assign an immutable first observation sequence to one candidate."""

        with self._lock:
            return self._observe(candidate)

    def candidates(self) -> tuple[FailureCandidate, ...]:
        """Return the current immutable causal ordering without freezing it."""

        with self._lock:
            return tuple(self._by_key.values())

    def freeze(self) -> FailureCausalitySnapshot:
        """Freeze once; repeated reads return the identical snapshot."""

        with self._lock:
            if self._snapshot is None:
                self._snapshot = FailureCausalitySnapshot(
                    tuple(self._by_key.values())
                )
            return self._snapshot

    def _observe(self, candidate: FailureCandidate) -> FailureCandidate:
        current = self._by_key.get(candidate.source_event_key)
        if current is None or current.causal_sequence != candidate.causal_sequence:
            raise FailureCausalityError("failure causal record is unknown")
        if current.observation_sequence is not None:
            return current
        self._require_mutable()
        observed = replace(
            current,
            observation_sequence=self._next_observation_sequence,
        )
        self._next_observation_sequence += 1
        self._by_key[current.source_event_key] = observed
        for error, bound in tuple(self._by_error.items()):
            if bound.source_event_key == current.source_event_key:
                self._by_error[error] = observed
        return observed

    def _validated_clock(self) -> int:
        value = self._clock_ns()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise FailureCausalityError("failure causal clock is invalid")
        return value

    def _require_mutable(self) -> None:
        if self._snapshot is not None:
            raise FailureCausalityError("failure causal record is frozen")


def failure_owner(code: object) -> str:
    """Return a closed source-owner family without imposing category priority."""

    value = _normalized_code(code)
    if value.startswith("event_transport"):
        return "event_transport"
    if value.startswith("backend_") or value == "ambient_client_detected":
        return "backend_ownership"
    if "resource" in value or value.startswith("storage_"):
        return "resource_sampling"
    if value.startswith("launch_"):
        return "launch_binding"
    if value.startswith("threshold_"):
        return "threshold_monitor"
    if value.startswith("child_"):
        return "child_terminal"
    return "refresh_supervisor"


def _normalized_code(code: object) -> str:
    value = getattr(code, "value", code)
    if not isinstance(value, str) or value not in _PUBLIC_FAILURE_CODES:
        raise FailureCausalityError("failure category is invalid")
    return value


def _bounded_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise FailureCausalityError(f"{label} is invalid")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise FailureCausalityError("failure causal boolean is invalid")
    return value


__all__ = [
    "FailureCandidate",
    "FailureCausalityAuthority",
    "FailureCausalityError",
    "FailureCausalitySnapshot",
    "failure_owner",
]
