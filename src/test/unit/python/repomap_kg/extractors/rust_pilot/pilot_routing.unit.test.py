"""Callback-free facade and import-boundary owner."""

from __future__ import annotations

import inspect

import pytest

from common_lore_index.extractors.rust_pilot import pilot


def test_open_facade_forwards_only_approved_controller_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class Recorder:
        def __init__(self, **kwargs: object) -> None:
            seen.update(kwargs)

    monkeypatch.setattr(pilot, "RustPilotController", Recorder)
    result = pilot.open_rust_pilot(
        docker_cli="/usr/bin/docker", sdk_image_id="sha256:" + "a" * 64,
        profile_dir="/private/profile", platform="linux/arm64", audit_dir="/private/audit",
    )
    assert isinstance(result, Recorder)
    assert set(seen) == {"docker_cli", "sdk_image_id", "profile_dir", "platform", "audit_dir"}
    assert not {"runner", "clock", "sleep", "verifier", "callback"} & set(seen)
    assert not {"runner", "clock", "sleep"} & set(inspect.signature(pilot.open_rust_pilot).parameters)
