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
