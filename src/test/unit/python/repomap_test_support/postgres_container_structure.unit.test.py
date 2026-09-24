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


def test_build_psql_wrapper_script_embeds_docker_environment() -> None:
    from repomap_test_support.postgres_container_config import build_psql_wrapper_script

    script = build_psql_wrapper_script(
        password="secret-password",
        runtime="docker",
        container_name="repomap-pg-container",
        docker_host="unix:///run/repomap-docker.sock",
        docker_config="/custom/docker/config",
        docker_context="custom-context",
    )
    assert 'env.setdefault("DOCKER_HOST", \'unix:///run/repomap-docker.sock\')' in script
    assert 'env.setdefault("DOCKER_CONFIG", \'/custom/docker/config\')' in script
    assert 'env.setdefault("DOCKER_CONTEXT", \'custom-context\')' in script
    assert 'env["PGPASSWORD"] = \'secret-password\'' in script


def test_build_psql_wrapper_restores_docker_host_under_sanitized_psql_environment(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    import json
    import subprocess
    import sys
    from repomap_kg.coordinator.configured_refresh import _psql_environment
    from repomap_test_support.postgres_container_config import build_psql_wrapper_script

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(mode=0o700)
    (bin_dir / "python3").symlink_to(sys.executable)
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "record = {'DOCKER_HOST': os.environ.get('DOCKER_HOST'), 'PGPASSWORD': os.environ.get('PGPASSWORD')}\n"
        "target = os.environ.get('TEST_RECORD_PATH')\n"
        "if target:\n"
        "    with open(target, 'w', encoding='utf-8') as f:\n"
        "        json.dump(record, f)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    wrapper_forwarded_path = tmp_path / "psql_forwarded.py"
    wrapper_forwarded_path.write_text(
        build_psql_wrapper_script(
            password="test-pg-password",
            runtime="docker",
            container_name="test-container",
            docker_host="unix:///run/repomap-docker.sock",
        ),
        encoding="utf-8",
    )
    wrapper_forwarded_path.chmod(0o755)

    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONFIG", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    wrapper_unforwarded_path = tmp_path / "psql_unforwarded.py"
    wrapper_unforwarded_path.write_text(
        build_psql_wrapper_script(
            password="test-pg-password",
            runtime="docker",
            container_name="test-container",
        ),
        encoding="utf-8",
    )
    wrapper_unforwarded_path.chmod(0o755)

    sanitized_env = _psql_environment("test-pg-password", (bin_dir,))
    assert "DOCKER_HOST" not in sanitized_env

    record_file = tmp_path / "record_forwarded.json"
    sanitized_env["TEST_RECORD_PATH"] = str(record_file)
    subprocess.run([sys.executable, str(wrapper_forwarded_path), "-c", "SELECT 1"], env=sanitized_env, check=True)
    forwarded_data = json.loads(record_file.read_text(encoding="utf-8"))
    assert forwarded_data["DOCKER_HOST"] == "unix:///run/repomap-docker.sock"
    assert forwarded_data["PGPASSWORD"] == "test-pg-password"

    record_file_unf = tmp_path / "record_unforwarded.json"
    sanitized_env["TEST_RECORD_PATH"] = str(record_file_unf)
    subprocess.run([sys.executable, str(wrapper_unforwarded_path), "-c", "SELECT 1"], env=sanitized_env, check=True)
    unforwarded_data = json.loads(record_file_unf.read_text(encoding="utf-8"))
    assert unforwarded_data["DOCKER_HOST"] is None
