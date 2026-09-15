#!/usr/bin/env python3
"""Fail-closed live attribution state for SCALE13 pre-final phases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from repomap_kg.storage.staging_phase_events import (
    STAGING_PHASE_CODES,
    StagingPhaseEventCategory,
)


class PhaseAttributionError(RuntimeError):
    """The phase lifecycle cannot establish exact active attribution."""


@dataclass(frozen=True)
class ActivePhaseSnapshot:
    """One exact active phase or an expected boundary state."""

    attribution: str
    active_sequence: int | None
    completed_sequence: int
    active_code: str | None = None
    active_started_offset_ns: int | None = None
    active_elapsed_ns: int | None = None


class PhaseAttributionState:
    """Validate nested phase lifecycle events and expose exact live state."""

    def __init__(self) -> None:
        self._active_sequence: int | None = None
        self._active_code: str | None = None
        self._active_started_offset_ns: int | None = None
        self._active_stack: list[tuple[int, str, int]] = []
        self._next_sequence = 1
        self._completed_sequence = 0
        self._last_event_offset_ns = 0
        self._attribution = "between_boundaries"
        self._closed = False

    @property
    def attribution(self) -> str:
        """Return the exact active phase or fail-closed state."""

        return self._attribution

    def accept(self, payload: dict[str, object]) -> None:
        """Validate and apply one strict phase lifecycle payload."""

        if self._closed:
            self._fail("phase lifecycle is closed")
        if not isinstance(payload, dict) or set(payload) != {
            "schema_version",
            "attempt_local_sequence",
            "phase_code",
            "event_category",
            "monotonic_offset_ns",
            "duration_ns_or_null",
            "terminal_category_or_null",
            "process_cpu_duration_ns_or_null",
        }:
            self._fail("phase lifecycle fields are invalid")
        if payload["schema_version"] != 1:
            self._fail("phase lifecycle schema is invalid")
        sequence = payload["attempt_local_sequence"]
        code = payload["phase_code"]
        category = payload["event_category"]
        offset = payload["monotonic_offset_ns"]
        cpu_duration = payload["process_cpu_duration_ns_or_null"]
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
        ):
            self._fail("phase lifecycle sequence is invalid")
        if not isinstance(code, str) or code not in STAGING_PHASE_CODES:
            self._fail("phase lifecycle code is invalid")
        if (
            not isinstance(category, str)
            or category not in {item.value for item in StagingPhaseEventCategory}
        ):
            self._fail("phase lifecycle category is invalid")
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < self._last_event_offset_ns
        ):
            self._fail("phase lifecycle offset is invalid")
        if cpu_duration is not None and (
            not isinstance(cpu_duration, int)
            or isinstance(cpu_duration, bool)
            or cpu_duration < 0
        ):
            self._fail("phase lifecycle CPU duration is invalid")
        if category == StagingPhaseEventCategory.STARTED.value:
            self._accept_started(sequence, code, payload)
            self._last_event_offset_ns = offset
            return
        self._accept_terminal(sequence, code, category, payload)
        self._last_event_offset_ns = offset

    def snapshot(
        self,
        monotonic_offset_ns: int | None = None,
    ) -> ActivePhaseSnapshot:
        """Return the bounded current attribution state."""

        if monotonic_offset_ns is None:
            monotonic_offset_ns = self._last_event_offset_ns
        if (
            not isinstance(monotonic_offset_ns, int)
            or isinstance(monotonic_offset_ns, bool)
            or monotonic_offset_ns < self._last_event_offset_ns
        ):
            self._fail("phase sample offset is invalid")
        elapsed_ns = (
            monotonic_offset_ns - self._active_started_offset_ns
            if self._active_started_offset_ns is not None
            else None
        )
        return ActivePhaseSnapshot(
            self._attribution,
            self._active_sequence,
            self._completed_sequence,
            self._active_code,
            self._active_started_offset_ns,
            elapsed_ns,
        )

    def close(self) -> None:
        """Require no open phase before accepting child completion."""

        if self._active_sequence is not None:
            self._fail(
                "phase lifecycle ended while active: "
                f"code={self._active_code}, sequence={self._active_sequence}, "
                f"depth={len(self._active_stack)}"
            )
        self._closed = True

    def _accept_started(
        self,
        sequence: int,
        code: str,
        payload: dict[str, object],
    ) -> None:
        if sequence != self._next_sequence:
            self._fail("phase lifecycle start sequence is invalid")
        if (
            payload["duration_ns_or_null"] is not None
            or payload["terminal_category_or_null"] is not None
            or payload["process_cpu_duration_ns_or_null"] is not None
        ):
            self._fail("phase lifecycle start is terminal")
        started_offset = payload["monotonic_offset_ns"]
        assert isinstance(started_offset, int)
        self._active_stack.append((sequence, code, started_offset))
        self._next_sequence += 1
        self._active_sequence = sequence
        self._active_code = code
        self._active_started_offset_ns = started_offset
        self._attribution = code

    def _accept_terminal(
        self,
        sequence: int,
        code: str,
        category: str,
        payload: dict[str, object],
    ) -> None:
        if sequence != self._active_sequence or code != self._active_code:
            self._fail("phase lifecycle terminal does not match active phase")
        duration = payload["duration_ns_or_null"]
        offset = payload["monotonic_offset_ns"]
        if not isinstance(offset, int) or isinstance(offset, bool):
            self._fail("phase lifecycle offset is invalid")
        assert self._active_started_offset_ns is not None
        if (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration < 0
            or duration != offset - self._active_started_offset_ns
            or payload["terminal_category_or_null"] != category
        ):
            self._fail("phase lifecycle terminal duration is invalid")
        self._completed_sequence = max(self._completed_sequence, sequence)
        self._active_stack.pop()
        if self._active_stack:
            (
                self._active_sequence,
                self._active_code,
                self._active_started_offset_ns,
            ) = self._active_stack[-1]
            self._attribution = self._active_code
        else:
            self._active_sequence = None
            self._active_code = None
            self._active_started_offset_ns = None
            self._attribution = "between_boundaries"

    def _fail(self, message: str) -> NoReturn:
        self._attribution = "pre_final_attribution_unknown"
        raise PhaseAttributionError(message)
