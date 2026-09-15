from __future__ import annotations

import pytest

from scale13_phase_state import PhaseAttributionError, PhaseAttributionState


def _event(
    sequence: int,
    code: str,
    category: str,
    *,
    offset: int | None = None,
    duration: int | None = None,
) -> dict[str, object]:
    terminal = category if category != "started" else None
    if offset is None:
        offset = sequence * 10 if terminal is None else sequence * 10 + 5
    return {
        "schema_version": 1,
        "attempt_local_sequence": sequence,
        "phase_code": code,
        "event_category": category,
        "monotonic_offset_ns": offset,
        "duration_ns_or_null": None if terminal is None else (duration or 5),
        "terminal_category_or_null": terminal,
        "process_cpu_duration_ns_or_null": None,
    }


def test_scale13_phase_state_tracks_exact_active_phase_and_idle_boundary() -> None:
    state = PhaseAttributionState()
    state.accept(_event(1, "refresh.source_discovery", "started"))
    assert state.attribution == "refresh.source_discovery"
    active = state.snapshot(13)
    assert active.active_code == "refresh.source_discovery"
    assert active.active_started_offset_ns == 10
    assert active.active_elapsed_ns == 3
    state.accept(_event(1, "refresh.source_discovery", "completed"))
    assert state.attribution == "between_boundaries"
    completed = state.snapshot(16)
    assert completed.active_code is None
    assert completed.active_elapsed_ns is None
    state.close()


def test_scale13_phase_state_tracks_innermost_nested_phase() -> None:
    state = PhaseAttributionState()
    state.accept(_event(1, "refresh.total", "started", offset=10))
    state.accept(
        _event(2, "refresh.source_discovery", "started", offset=20)
    )
    assert state.snapshot(23).active_code == "refresh.source_discovery"
    state.accept(
        _event(
            2,
            "refresh.source_discovery",
            "completed",
            offset=25,
            duration=5,
        )
    )
    parent = state.snapshot(26)
    assert parent.active_code == "refresh.total"
    assert parent.active_elapsed_ns == 16
    state.accept(
        _event(1, "refresh.total", "completed", offset=30, duration=20)
    )
    assert state.attribution == "between_boundaries"
    state.close()


def test_scale13_phase_state_rejects_stale_offset_or_wrong_duration() -> None:
    stale = PhaseAttributionState()
    stale.accept(_event(1, "refresh.source_discovery", "started", offset=10))
    with pytest.raises(PhaseAttributionError, match="offset"):
        stale.snapshot(9)

    wrong_duration = PhaseAttributionState()
    wrong_duration.accept(
        _event(1, "refresh.source_discovery", "started", offset=10)
    )
    with pytest.raises(PhaseAttributionError, match="duration"):
        wrong_duration.accept(
            _event(
                1,
                "refresh.source_discovery",
                "completed",
                offset=20,
                duration=9,
            )
        )


@pytest.mark.parametrize(
    "events",
    (
        (_event(1, "refresh.source_discovery", "completed"),),
        (
            _event(1, "refresh.source_discovery", "started"),
            _event(1, "refresh.source_discovery", "started"),
        ),
        (
            _event(2, "refresh.source_discovery", "started"),
        ),
        (
            _event(1, "refresh.source_discovery", "started"),
            _event(1, "refresh.extraction", "completed"),
        ),
    ),
)
def test_scale13_phase_state_fails_closed_on_missing_duplicate_or_order_error(
    events: tuple[dict[str, object], ...],
) -> None:
    state = PhaseAttributionState()
    with pytest.raises(PhaseAttributionError):
        for event in events:
            state.accept(event)
    assert state.attribution == "pre_final_attribution_unknown"


def test_scale13_phase_state_close_reports_bounded_active_identity() -> None:
    state = PhaseAttributionState()
    state.accept(_event(1, "refresh.total", "started", offset=10))
    state.accept(_event(2, "refresh.extraction", "started", offset=20))

    with pytest.raises(
        PhaseAttributionError,
        match=(
            "phase lifecycle ended while active: "
            "code=refresh.extraction, sequence=2, depth=2"
        ),
    ):
        state.close()
