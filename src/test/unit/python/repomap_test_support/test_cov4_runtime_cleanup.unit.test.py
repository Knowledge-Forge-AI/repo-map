from __future__ import annotations

from types import SimpleNamespace

import pytest

from repomap_test_support import scale15_runtime_campaign as runtime_campaign


def test_runtime_start_failure_stops_exact_started_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    plan = SimpleNamespace(env_file=tmp_path / "runtime.env")
    stopped = []
    ports = iter((55431, 55432))
    monkeypatch.setattr(
        runtime_campaign,
        "setup_local_runtime",
        lambda home: home.mkdir(parents=True, exist_ok=True),
    )
    monkeypatch.setattr(runtime_campaign, "_available_port", ports.__next__)
    monkeypatch.setattr(
        runtime_campaign,
        "_runtime_config",
        lambda *_args: "runtime-config",
    )
    monkeypatch.setattr(
        runtime_campaign,
        "_actual_config",
        lambda *_args: "actual-config",
    )
    monkeypatch.setattr(
        runtime_campaign,
        "build_local_runtime_plan",
        lambda _home: plan,
    )
    monkeypatch.setattr(
        runtime_campaign,
        "read_runtime_password",
        lambda _path: "public-safe",
    )
    monkeypatch.setattr(
        runtime_campaign,
        "up_local_runtime",
        lambda _home: SimpleNamespace(result="started"),
    )
    def _fake_down_local_runtime(home: object) -> SimpleNamespace:
        stopped.append(home)
        return SimpleNamespace(result="stopped")

    monkeypatch.setattr(
        runtime_campaign,
        "down_local_runtime",
        _fake_down_local_runtime,
    )
    monkeypatch.setattr(
        runtime_campaign,
        "_start_loopback_proxy",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("startup failed")),
    )

    with pytest.raises(RuntimeError, match="startup failed"):
        runtime_campaign.start_scale15_runtime(tmp_path, ("public-graph",))

    assert stopped == [tmp_path / "runtime-home"]
