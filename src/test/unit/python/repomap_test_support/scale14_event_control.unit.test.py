from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.scale14_event_control import TestEventControlChannel


class _Channel:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, category, payload):
        self.sent.append((category, payload))

    def close(self):
        self.closed = True


def test_test_control_blocks_only_after_acknowledged_selected_start() -> None:
    channel = _Channel()
    calls = []
    controlled = TestEventControlChannel(
        channel,
        selected_code="refresh.source_discovery",
        wait_seconds=3.0,
        blocker=lambda seconds: calls.append((seconds, tuple(channel.sent))),
    )

    controlled.send(
        "phase",
        {
            "phase_code": "refresh.source_discovery",
            "event_category": "started",
        },
    )

    assert calls == [(3.0, tuple(channel.sent))]
    controlled.close()
    assert channel.closed is True


def test_test_control_announces_post_ack_blocker_entry_before_blocking() -> None:
    channel = _Channel()
    calls: list[tuple[str, object]] = []
    controlled = TestEventControlChannel(
        channel,
        selected_code="refresh.source_discovery",
        wait_seconds=3.0,
        blocker_entered=lambda: calls.append(("entered", tuple(channel.sent))),
        blocker=lambda seconds: calls.append(("blocked", seconds)),
    )

    controlled.send(
        "phase",
        {
            "phase_code": "refresh.source_discovery",
            "event_category": "started",
        },
    )

    assert calls == [
        ("entered", tuple(channel.sent)),
        ("blocked", 3.0),
    ]


@pytest.mark.parametrize("code", ("unknown.code", "", None))
def test_test_control_requires_one_closed_registry_code(code) -> None:
    with pytest.raises(ValueError, match="code"):
        TestEventControlChannel(_Channel(), selected_code=code, wait_seconds=1.0)


def test_product_source_has_no_test_support_import_or_control() -> None:
    product_root = Path(__file__).resolve().parents[4] / "main" / "python"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(product_root.rglob("*.py"))
    )

    assert "repomap_test_support" not in source
    assert "scale14_event_control" not in source
    assert "SCALE14_CANCEL" not in source


@pytest.mark.parametrize("route", ("proxy-default", "actual-cli-child"))
def test_test_blocker_preserves_interrupt_at_condition_release_window(monkeypatch, route) -> None:
    import threading
    import time
    from types import SimpleNamespace

    from repomap_test_support import scale14_actual_refresh_child as child
    from repomap_test_support import scale14_event_control as control

    event = threading.Event()
    condition = getattr(event, "_cond")
    release = getattr(condition, "_release_save")

    def release_then_interrupt():
        release()
        raise KeyboardInterrupt("after condition release")

    def interrupted_sleep(_seconds):
        raise KeyboardInterrupt("during lock-free delay")

    # Event.wait loses this interrupt when its outer context releases the
    # already-released lock. That RuntimeError is an ordinary telemetry error.
    # Only the owned old-style blocker receives the fault. Other test-runner
    # threads keep their real Condition and sleep implementations.
    monkeypatch.setattr(condition, "_release_save", release_then_interrupt)
    for module in (control, child):
        monkeypatch.setattr(module, "Event", lambda: event, raising=False)
        monkeypatch.setattr(module, "time", SimpleNamespace(sleep=interrupted_sleep), raising=False)
    assert threading.Event().wait(0.0) is False
    time.sleep(0.0)
    payload: dict[str, object] = {"operation_code": "guard.source_index_stage", "event_category": "started"}
    if route == "proxy-default":
        controlled = TestEventControlChannel(
            _Channel(), selected_code="guard.source_index_stage", wait_seconds=1.0)
        with pytest.raises(KeyboardInterrupt):
            controlled.send("operation", payload)
    else:
        product_cli = child.product_cli
        assert product_cli is not None
        monkeypatch.setattr(product_cli, "staging_event_channel_from_inherited_fd", lambda _fd: _Channel())
        monkeypatch.setattr(child.cli_facade, "staging_event_channel_from_inherited_fd", lambda _fd: _Channel())

        def product_main(_arguments):
            product_cli.staging_event_channel_from_inherited_fd(0).send("operation", payload)
            pytest.fail("selected blocker returned instead of propagating interruption")

        monkeypatch.setattr(product_cli, "main", product_main)
        with pytest.raises(KeyboardInterrupt):
            child.main(["--cancel-code", "guard.source_index_stage", "--wait-seconds", "1",
                        "--", "ops", "refresh-graph"])
