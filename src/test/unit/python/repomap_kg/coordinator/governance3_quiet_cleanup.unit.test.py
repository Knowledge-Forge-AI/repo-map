"""Quiet unknown-status cleanup, closed group vocabulary and the native signal guard."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest

import common_lore_index.coordinator.process_supervision as supervision
from common_lore_index.coordinator._child_reaper import ChildReaper
from common_lore_index.coordinator.process_supervision import ManagedProcess, PosixProcessGroup


class _Popen:
    pid = 4242
    args = ("worker",)

    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.stdin, self.stdout, self.stderr = BytesIO(), BytesIO(), BytesIO()

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = -15 if self.returncode is None else self.returncode
        return self.returncode


class _Boundary:
    kind = "fake"

    def __init__(self, states: list[str] | None = None, *, close_error: Exception | None = None) -> None:
        self.states = list(states or ["empty"])
        self.events: list[str] = []
        self.close_error = close_error

    def group_state(self) -> str:
        self.events.append("probe")
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def terminate_gracefully(self) -> None:
        self.events.append("term")

    def kill_tree(self) -> None:
        self.events.append("kill")

    def tree_exists(self) -> bool:
        raise AssertionError("group_state is preferred when the boundary provides it")

    def close(self) -> None:
        self.events.append("close")
        if self.close_error is not None:
            raise self.close_error


def _unknown_owner() -> ChildReaper:
    def echild(pid: int, flags: int) -> Any:
        raise ChildProcessError

    return ChildReaper(_Popen.pid, _wait4=echild)


def _managed(boundary: object, popen: _Popen | None = None, reaper: ChildReaper | None = None) -> ManagedProcess:
    return ManagedProcess(cast(Any, popen or _Popen()), cast(Any, boundary), _reaper=reaper)


@pytest.mark.parametrize(("states", "events", "expected_group_empty"), [
    (["empty"], ["probe", "close"], True),
    (["members", "members", "empty"], ["probe", "kill", "probe", "probe", "close"], True),
    (["unprobeable"], ["probe", "close"], False),
])
def test_unknown_status_skips_the_leader_phase_and_is_never_clean(
    states: list[str], events: list[str], expected_group_empty: bool,
) -> None:
    boundary = _Boundary(states)
    managed = _managed(boundary, reaper=_unknown_owner())
    assert managed.cleanup(0.1, 1.0) is False
    assert managed.reap_state() == "status_unknown" and managed.closed
    assert managed.group_empty_observed is expected_group_empty
    assert boundary.events == events, "no raising poll, no TERM, kill only on a fresh members probe"
    assert managed.cleanup(0.1, 1.0) is False and boundary.events == events, "released: retained, unsignalled"


def test_a_live_leader_keeps_incumbent_term_then_retains_a_clean_result() -> None:
    boundary = _Boundary(["empty"])
    managed = _managed(boundary)
    assert managed.cleanup(0.1, 0.1) is True
    assert managed.group_empty_observed is True
    assert boundary.events == ["term", "probe", "close"]
    assert managed.cleanup(0.1, 0.1) is True and boundary.events == ["term", "probe", "close"]


def test_unprobeable_group_is_never_signalled_or_clean() -> None:
    boundary = _Boundary(["unprobeable"])
    managed = _managed(boundary, popen=_Popen(returncode=0))
    assert managed.cleanup(0.1, 0.1) is False
    assert managed.group_empty_observed is False
    assert "kill" not in boundary.events and boundary.events[-1] == "close"


def test_close_failure_is_unproven_and_propagates() -> None:
    boundary = _Boundary(["empty"], close_error=OSError("close"))
    managed = _managed(boundary, popen=_Popen(returncode=0))
    with pytest.raises(OSError, match="close"):
        managed.cleanup(0.1, 0.1)
    assert managed._cleanup_clean is None and not managed.closed


def test_legacy_boundary_maps_tree_exists_and_ordinary_errors_propagate() -> None:
    class Legacy:
        kind = "legacy"

        def __init__(self, error: Exception | None) -> None:
            self.error, self.closed = error, 0

        def tree_exists(self) -> bool:
            if self.error is not None:
                raise self.error
            return False

        def terminate_tree(self) -> None:
            return None

        def close(self) -> None:
            self.closed += 1

    assert _managed(Legacy(None)).group_state() == "empty"
    failing = Legacy(OSError("probe failed"))
    managed = _managed(failing, popen=_Popen(returncode=0))
    with pytest.raises(OSError, match="probe failed"):
        managed.cleanup(0.1, 0.1)
    assert failing.closed == 1 and managed.cleanup(0.1, 0.1) is False


def test_posix_group_probe_maps_lookup_and_permission(monkeypatch) -> None:
    outcomes: list[BaseException | None] = [None, ProcessLookupError(), PermissionError()]

    def killpg(pid: int, sig: int) -> None:
        assert sig == 0
        failure = outcomes.pop(0)
        if failure is not None:
            raise failure

    monkeypatch.setattr(supervision.os, "killpg", killpg)
    group = PosixProcessGroup(77)
    assert [group.group_state() for _ in range(3)] == ["members", "empty", "unprobeable"]


def test_non_native_posix_group_signals_are_refused_before_any_killpg(monkeypatch) -> None:
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(supervision.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    managed = _managed(PosixProcessGroup(_Popen.pid))
    assert not managed.native
    for method in (managed.kill_tree, managed.terminate_gracefully):
        with pytest.raises(supervision.ProcessBoundaryError, match="native launch provenance"):
            method()
    assert signals == []
    managed.close()
    managed.kill_tree()
    managed.terminate_gracefully()
    assert signals == [], "a released boundary is never signalled"


def test_fake_popen_factory_never_earns_native_custody_or_a_wait4_owner(monkeypatch, tmp_path: Path) -> None:
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(supervision.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(supervision.os, "wait4", lambda *args: pytest.fail("no wait4 on a fake child"))
    managed = supervision.launch_managed_process(
        ("worker",), {}, tmp_path, popen_factory=lambda *a, **k: _Popen(), collect_usage=True,
    )
    assert not managed.native and managed._reaper is None
    assert managed.resource_usage is not None and managed.resource_usage.reason == "platform_unsupported"
    with pytest.raises(supervision.ProcessBoundaryError):
        managed.cleanup(0.1, 0.1)
    assert managed.closed and signals == [], "the refused signal never reached a real group"
