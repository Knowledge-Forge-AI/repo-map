from pathlib import Path
from subprocess import CompletedProcess

from pytest import MonkeyPatch


def test_rootpkg36_container_helpers_are_reexported() -> None:
    from repomap_test_support import postgres_harness as harness
    from repomap_test_support import postgres_container as container

    names = (
        "PostgresContainerConfig",
        "PostgresContainerDatabase",
        "PostgresContainerHarness",
        "PostgresContainerSession",
        "SubprocessRunner",
        "bounded_text",
        "is_local_port_open",
        "redact_secret_text",
        "redacted_command",
        "run",
        "safe_run_id_text",
    )
    for name in names:
        assert getattr(harness, name) is getattr(container, name)


def test_database_scalar_preserves_container_runner_patch(monkeypatch: MonkeyPatch) -> None:
    from repomap_test_support import postgres_container as container

    calls: list[str] = []

    def run(command: list[str], sql: str) -> CompletedProcess[str]:
        calls.append(sql)
        return CompletedProcess(command, 0, "42\n", "")

    monkeypatch.setattr(container, "run", run)
    database = container.PostgresContainerDatabase("127.0.0.1", 55433, "test", "test", "psql")
    assert database.psql_scalar("SELECT 42") == "42"
    assert calls == ["SELECT 42"]


def test_binary_resolution_preserves_harness_config_patch(monkeypatch: MonkeyPatch) -> None:
    from repomap_test_support import postgres_harness as harness

    expected = Path("/public-fixture/postgres/bin")
    monkeypatch.setattr(harness, "postgres_config_path", lambda option: expected)
    assert harness.postgres_bin_dir() == expected


def test_ipc_guard_preserves_harness_capture_patch(monkeypatch: MonkeyPatch) -> None:
    from repomap_test_support import postgres_harness as harness

    monkeypatch.setattr(harness, "capture_shared_memory_segments", lambda runner: ())
    guard = harness.PostgresIpcGuard(current_user="public-fixture")
    assert guard.capture_baseline()
    assert guard.baseline == ()
