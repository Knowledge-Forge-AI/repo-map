from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

from ci import check_generated_drift as generated_drift
from repomap_test_support.generated_lock_fixtures import (
    LOCKS,
    POLICY,
    AMBIENT_RESOLVER_KEYS,
    FakeUvIndex,
    configure_repository,
    run_checker,
)


def test_old_fresh_resolution_model_selects_newer_transitive(tmp_path: Path) -> None:
    fake_index = FakeUvIndex()
    workspace = tmp_path / "fresh"
    source = workspace / "tools" / "ci" / "first.in"
    source.parent.mkdir(parents=True)
    source.write_text("direct==1\n", encoding="utf-8")
    command = [
        "uv",
        "pip",
        "compile",
        "--generate-hashes",
        "tools/ci/first.in",
        "--output-file",
        "tools/ci/first.lock",
    ]

    fake_index(command, cwd=workspace, env={})

    assert (workspace / "tools" / "ci" / "first.lock").read_text() == (
        "direct==1\ntransitive==2\n"
    )


def test_unchanged_seeded_regeneration_remains_stable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_repository(monkeypatch, tmp_path)
    fake_index = FakeUvIndex()
    monkeypatch.setattr(generated_drift, "run", fake_index)

    result, evidence = run_checker(tmp_path)

    assert result == 0
    assert all(evidence.values())
    assert fake_index.seeded == [True, True]


def test_direct_input_change_is_detected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_repository(monkeypatch, tmp_path, direct_input="direct==2\n")
    monkeypatch.setattr(generated_drift, "run", FakeUvIndex())

    result, evidence = run_checker(tmp_path)

    assert result == 1
    assert not evidence["first.lock"]
    assert not evidence["second.lock"]


def test_gate_never_requests_explicit_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_repository(monkeypatch, tmp_path)
    fake_index = FakeUvIndex()
    monkeypatch.setattr(generated_drift, "run", fake_index)

    result, _evidence = run_checker(tmp_path)

    assert result == 0
    uv_commands = [command for command in fake_index.commands if command[0] == "uv"]
    assert uv_commands
    assert all("--upgrade" not in command and "-U" not in command for command in uv_commands)


def test_normal_gate_owns_index_cutoff_and_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_repository(monkeypatch, tmp_path)
    fake_index = FakeUvIndex(warm_default_cache=True)
    monkeypatch.setattr(generated_drift, "run", fake_index)

    result, _evidence = run_checker(tmp_path)

    assert result == 0
    uv_commands = [
        command for command in fake_index.commands if Path(command[0]).name == "uv"
    ]
    assert uv_commands
    for command in uv_commands:
        assert command[1:4] == ("--no-cache", "--no-config", "pip")
        assert command[command.index("--default-index") + 1] == POLICY["default_index"]
        assert command[command.index("--exclude-newer") + 1] == POLICY["exclude_newer"]


def test_ambient_upgrade_config_and_index_state_is_not_forwarded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_repository(monkeypatch, tmp_path)
    for key in AMBIENT_RESOLVER_KEYS:
        monkeypatch.setenv(key, "ambient-override")
    fake_index = FakeUvIndex()
    monkeypatch.setattr(generated_drift, "run", fake_index)

    result, evidence = run_checker(tmp_path)

    assert result == 0
    assert all(evidence.values())
    assert fake_index.environments
    assert all(
        key not in environment
        for environment in fake_index.environments
        for key in AMBIENT_RESOLVER_KEYS
    )


def test_post_cutoff_same_version_artifact_cannot_change_hash_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_repository(monkeypatch, tmp_path)
    fake_index = FakeUvIndex(expose_post_cutoff_artifact=True)
    monkeypatch.setattr(generated_drift, "run", fake_index)

    result, evidence = run_checker(tmp_path)

    assert result == 0
    assert all(evidence.values())


def test_removed_pre_cutoff_artifact_is_a_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_repository(monkeypatch, tmp_path)
    fake_index = FakeUvIndex(remove_pre_cutoff_artifact=True)
    monkeypatch.setattr(generated_drift, "run", fake_index)

    result, _evidence = run_checker(tmp_path)

    assert result == 2
    assert "frozen index view" in capsys.readouterr().err


@pytest.mark.parametrize(
    "missing_key", ["authority_sha256", "default_index", "exclude_newer"]
)
def test_missing_index_authority_is_a_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing_key: str,
) -> None:
    ci_root = configure_repository(monkeypatch, tmp_path)
    policy = json.loads(
        (ci_root / "generated_lock_policy.json").read_text(encoding="utf-8")
    )
    policy.pop(missing_key)
    (ci_root / "generated_lock_policy.json").write_text(
        json.dumps(policy) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(generated_drift, "run", FakeUvIndex())

    result, _evidence = run_checker(tmp_path)

    assert result == 2
    assert "tool/configuration failure" in capsys.readouterr().err


def test_index_unavailability_is_a_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_repository(monkeypatch, tmp_path)

    def unavailable_index(
        _command: list[str], *, cwd: Path, env: dict[str, str]
    ) -> None:
        del cwd, env
        raise generated_drift.ToolFailure("uv exited 2")

    monkeypatch.setattr(generated_drift, "run", unavailable_index)

    result, _evidence = run_checker(tmp_path)

    assert result == 2
    assert "tool/configuration failure" in capsys.readouterr().err


def test_missing_generator_is_a_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_repository(monkeypatch, tmp_path)

    def missing_generator(
        _command: list[str], *, cwd: Path, env: dict[str, str]
    ) -> None:
        del cwd, env
        raise FileNotFoundError("uv")

    monkeypatch.setattr(generated_drift, "run", missing_generator)

    result, _evidence = run_checker(tmp_path)

    assert result == 2
    assert "tool/configuration failure" in capsys.readouterr().err


def test_temporary_generation_does_not_mutate_repository_locks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ci_root = configure_repository(monkeypatch, tmp_path)
    original = {lock: (ci_root / lock).read_bytes() for _source, lock in LOCKS}
    fake_index = FakeUvIndex()

    def mutating_generator(
        command: list[str], *, cwd: Path, env: dict[str, str]
    ) -> None:
        fake_index(command, cwd=cwd, env=env)
        if Path(command[0]).name == "uv":
            fake_index.outputs[-1].write_text("generated\n", encoding="utf-8")

    monkeypatch.setattr(generated_drift, "run", mutating_generator)

    result, _evidence = run_checker(tmp_path)

    assert result == 2
    assert all(not output.is_relative_to(ci_root) for output in fake_index.outputs)
    assert original == {lock: (ci_root / lock).read_bytes() for _source, lock in LOCKS}


def test_subprocess_nonzero_is_a_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        generated_drift.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 17),
    )

    with pytest.raises(generated_drift.ToolFailure, match="uv exited 17"):
        generated_drift.run(["uv", "--version"], cwd=tmp_path, env={"PATH": "/bin"})


def test_wrong_uv_version_is_a_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "tools.json"
    manifest.write_text('{"tools":{"uv":{"version":"0.9.30"}}}\n', encoding="utf-8")
    monkeypatch.setattr(
        generated_drift.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, "uv 1.0.0\n", ""
        ),
    )
    monkeypatch.setattr(
        generated_drift,
        "expected_uv_version",
        lambda _path: json.loads(manifest.read_text(encoding="utf-8"))["tools"]["uv"][
            "version"
        ],
    )

    with pytest.raises(generated_drift.ToolFailure, match="version attestation"):
        generated_drift.verify_uv_version("uv", {"PATH": "/bin"})


def test_uv_version_attestation_accepts_release_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generated_drift.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, "uv 0.9.30 (release-id build-date)\n", ""
        ),
    )
    monkeypatch.setattr(
        generated_drift, "expected_uv_version", lambda _path: "0.9.30"
    )

    generated_drift.verify_uv_version("uv", {"PATH": "/bin"})
