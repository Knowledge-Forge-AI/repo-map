from __future__ import annotations

import json
from pathlib import Path
import pytest

from ci import check_generated_drift as generated_drift
from ci import update_generated_locks as lock_upgrade
from repomap_test_support.generated_lock_fixtures import (
    LOCKS,
    POLICY,
    FakeUvIndex,
    configure_repository,
)


def test_explicit_upgrade_uses_separate_maintenance_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ci_root = configure_repository(monkeypatch, tmp_path)
    monkeypatch.setattr(lock_upgrade, "CI_ROOT", ci_root)
    monkeypatch.setattr(lock_upgrade, "POLICY_PATH", ci_root / "generated_lock_policy.json")
    monkeypatch.setattr(lock_upgrade, "PYTHON_LOCKS", LOCKS)
    monkeypatch.setattr(lock_upgrade, "verify_uv_version", lambda _uv, _env: None)
    for key in ("UV_CACHE_DIR", "UV_NO_CACHE"):
        monkeypatch.setenv(key, "ambient-override")
    fake_index = FakeUvIndex(warm_default_cache=True)
    monkeypatch.setattr(lock_upgrade, "run", fake_index)

    result = lock_upgrade.main(
        ["--exclude-newer", "2026-09-01T00:00:00Z", "--uv", "uv"]
    )

    assert result == 0
    uv_commands = [
        command for command in fake_index.commands if Path(command[0]).name == "uv"
    ]
    assert uv_commands
    assert all(
        command[1:4] == ("--no-cache", "--no-config", "pip")
        and "--upgrade" in command
        for command in uv_commands
    )
    assert all(
        key not in environment
        for environment in fake_index.environments
        for key in ("UV_CACHE_DIR", "UV_NO_CACHE")
    )
    policy = json.loads(
        (ci_root / "generated_lock_policy.json").read_text(encoding="utf-8")
    )
    assert policy["exclude_newer"] == "2026-09-01T00:00:00Z"


def test_failed_upgrade_does_not_mutate_repository_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ci_root = configure_repository(monkeypatch, tmp_path)
    monkeypatch.setattr(lock_upgrade, "CI_ROOT", ci_root)
    monkeypatch.setattr(lock_upgrade, "POLICY_PATH", ci_root / "generated_lock_policy.json")
    monkeypatch.setattr(lock_upgrade, "PYTHON_LOCKS", LOCKS)
    monkeypatch.setattr(lock_upgrade, "verify_uv_version", lambda _uv, _env: None)
    original = {
        path.name: path.read_bytes()
        for path in [
            *(ci_root / lock for _source, lock in LOCKS),
            ci_root / "generated_lock_policy.json",
        ]
    }

    def failed_upgrade(
        _command: list[str], *, cwd: Path, env: dict[str, str]
    ) -> None:
        del cwd, env
        raise generated_drift.ToolFailure("uv exited 2")

    monkeypatch.setattr(lock_upgrade, "run", failed_upgrade)

    result = lock_upgrade.main(["--exclude-newer", "2026-09-01T00:00:00Z"])

    assert result == 2
    assert original == {
        path.name: path.read_bytes()
        for path in [
            *(ci_root / lock for _source, lock in LOCKS),
            ci_root / "generated_lock_policy.json",
        ]
    }


def test_preserved_resolution_updates_inputs_without_transitive_upgrade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    ci_root = configure_repository(monkeypatch, tmp_path, direct_input="direct==2\n")
    monkeypatch.setattr(lock_upgrade, "CI_ROOT", ci_root)
    monkeypatch.setattr(lock_upgrade, "POLICY_PATH", ci_root / "generated_lock_policy.json")
    monkeypatch.setattr(lock_upgrade, "PYTHON_LOCKS", LOCKS)
    monkeypatch.setattr(lock_upgrade, "verify_uv_version", lambda _uv, _env: None)
    fake_index = FakeUvIndex(warm_default_cache=True)
    monkeypatch.setattr(lock_upgrade, "run", fake_index)

    result = lock_upgrade.main([
        "--exclude-newer", POLICY["exclude_newer"], "--preserve-existing",
    ])

    assert result == 0
    assert fake_index.seeded == [True, True]
    assert all("--upgrade" not in command for command in fake_index.commands)
    for _source, lock in LOCKS:
        assert (ci_root / lock).read_text() == "direct==2\ntransitive==1\n"
    policy = json.loads((ci_root / "generated_lock_policy.json").read_text())
    assert policy["authority_sha256"] == generated_drift.authority_digest(ci_root)
    assert policy["exclude_newer"] == POLICY["exclude_newer"]
