from pathlib import Path
import subprocess
from subprocess import CompletedProcess
from unittest.mock import MagicMock

from pytest import MonkeyPatch

import pytest


def test_pgvector_readiness_crosses_psql_format_boundary(monkeypatch: MonkeyPatch) -> None:
    from repomap_test_support import postgres_container as container

    monkeypatch.setattr(container, "active_resource_run", lambda: None)
    monkeypatch.setenv("REPOMAP_TEST_PG_IMAGE", "sha256:" + "b" * 64)
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        if "pg_isready" in command:
            return CompletedProcess(command, 0, "accepting connections\n", "")
        machine_format = all(flag in command for flag in ("-X", "-A", "-t"))
        stdout = "1\n" if machine_format else " count\n-------\n     1\n(1 row)\n"
        return CompletedProcess(command, 0, stdout, "")

    harness = container.PostgresContainerHarness(container.PgvectorContainerConfig(), runner=runner)
    harness.wait_until_ready()
    command, options = calls[-1]
    assert command == [
        "docker", "exec", "-i", "-e", "PGPASSWORD", harness.container_name,
        "psql", "-h", "127.0.0.1", "-p", "5432", "-U", harness.config.user,
        "-d", harness.config.database, "-v", "ON_ERROR_STOP=1", "-X", "-A", "-t",
    ]
    assert options["env"]["PGPASSWORD"] == harness.config.password
    assert options["input"] == (
        "SELECT count(*) FROM pg_available_extension_versions "
        "WHERE name = 'vector' AND version = '0.8.7';"
    )
    assert options["check"] is False
    assert options["timeout"] == 30
    assert harness.start_command()[-1] == "sha256:" + "b" * 64
    assert "--pull=never" in harness.start_command()


@pytest.fixture
def readiness_harness(monkeypatch: MonkeyPatch):
    from repomap_test_support import postgres_container as container

    monkeypatch.setattr(container, "active_resource_run", lambda: None)
    monkeypatch.setenv("REPOMAP_TEST_PG_IMAGE", "sha256:" + "b" * 64)
    calls = []

    def make(stdout="1\n", returncode=0, stderr="", error=None):
        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if "pg_isready" in command:
                return CompletedProcess(command, 0, "accepting connections\n", "")
            if error is not None:
                raise error
            machine_format = all(flag in command for flag in ("-X", "-A", "-t"))
            output = stdout if machine_format else " count\n-------\n     1\n(1 row)\n"
            return CompletedProcess(command, returncode, output, stderr)

        return container.PostgresContainerHarness(container.PgvectorContainerConfig(), runner=runner)

    return make, calls


@pytest.mark.parametrize("stdout", ["1", "1\n", "1\r\n"])
def test_pgvector_scalar_one_is_available(readiness_harness, stdout) -> None:
    make, _ = readiness_harness
    make(stdout=stdout).wait_until_ready()


def test_pgvector_scalar_zero_reports_absence_and_image_readback(readiness_harness) -> None:
    make, _ = readiness_harness
    harness = make(stdout="0\n")
    harness.container_id = "c" * 64
    harness._docker_client = MagicMock()
    harness._docker_client.containers.get.return_value.attrs = {"Image": "sha256:" + "b" * 64}
    with pytest.raises(RuntimeError, match="version 0.8.7 is not available") as caught:
        harness.wait_until_ready()
    message = str(caught.value)
    assert "profile=pgvector" in message
    assert "resolved_image_id=sha256:" + "b" * 64 in message
    assert "container_image_id=sha256:" + "b" * 64 in message
    assert "query_returncode=0 catalog_count=0" in message
    assert harness.config.password not in message
    harness._docker_client.containers.get.assert_called_once_with(harness.container_id)


@pytest.mark.parametrize("stdout", [
    "", "\n", "1\n1\n", "0\n1\n", "1\n\n1\n", "1\n\n",
    " count\n-------\n(1 row)\n", " count\n-------\n     1\n(1 row)\n",
    "invalid\n1\n", "(1 row)\n", "count\n1\n", "1|0\n", "2\n", " 1\n", "1\x00\n",
])
def test_pgvector_malformed_scalar_is_probe_error(readiness_harness, stdout) -> None:
    make, _ = readiness_harness
    with pytest.raises(RuntimeError, match="probe-output error") as caught:
        make(stdout=stdout).wait_until_ready()
    message = str(caught.value)
    assert "is not available" not in message
    assert "query_returncode=0 catalog_count=invalid" in message
    assert "container_image_id=unavailable" in message


@pytest.mark.parametrize("returncode,stderr", [
    (3, "ERROR: catalog query failed"),
    (2, "psql: connection refused"),
    (125, "container exec failed"),
])
def test_pgvector_nonzero_probe_preserves_failure(readiness_harness, returncode, stderr) -> None:
    make, _ = readiness_harness
    harness = make(stdout="1\n", returncode=returncode, stderr=stderr)
    with pytest.raises(RuntimeError, match=stderr) as caught:
        harness.wait_until_ready()
    assert "is not available" not in str(caught.value)
    assert f"query_returncode={returncode} catalog_count=unavailable" in str(caught.value)
    assert isinstance(caught.value.__cause__, RuntimeError)


@pytest.mark.parametrize("error", [
    FileNotFoundError("fixture runtime missing"),
    OSError("fixture process failed"),
    subprocess.TimeoutExpired("fixture psql", 30),
])
def test_pgvector_process_error_preserves_cause(readiness_harness, error) -> None:
    make, _ = readiness_harness
    with pytest.raises(RuntimeError, match="container command failed") as caught:
        make(error=error).wait_until_ready()
    cause = caught.value.__cause__
    assert cause is not None and cause.__cause__ is error
    assert "query_returncode=unavailable catalog_count=unavailable" in str(caught.value)
    assert "is not available" not in str(caught.value)


def test_pgvector_image_readback_failure_keeps_probe_failure(readiness_harness) -> None:
    make, _ = readiness_harness
    harness = make(stdout="0\n")
    harness.container_id = "c" * 64
    harness._docker_client = MagicMock()
    harness._docker_client.containers.get.side_effect = RuntimeError("image readback failed")
    with pytest.raises(RuntimeError, match="version 0.8.7 is not available") as caught:
        harness.wait_until_ready()
    assert "container_image_id=unavailable" in str(caught.value)
    assert "image readback failed" not in str(caught.value)


def test_core_readiness_and_ordinary_psql_preserve_contract(monkeypatch: MonkeyPatch) -> None:
    from repomap_test_support import postgres_container as container

    monkeypatch.setattr(container, "active_resource_run", lambda: None)
    monkeypatch.setenv("REPOMAP_TEST_PG_PROFILE", "core")
    verifier = MagicMock(side_effect=AssertionError("optional readiness requested by core"))
    monkeypatch.setattr(container, "verify_pgvector_readiness", verifier)
    calls = []
    aligned = " count\n-------\n     1\n(1 row)\n"

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, aligned, "")

    harness = container.PostgresContainerHarness(container.PostgresContainerConfig(), runner=runner)
    harness.wait_until_ready()
    assert len(calls) == 1 and "pg_isready" in calls[0][0]
    verifier.assert_not_called()
    result = harness.run_psql("SELECT count(*) FROM fixture;")
    assert result.stdout == aligned
    command, options = calls[-1]
    assert command == [
        "docker", "exec", "-i", "-e", "PGPASSWORD", harness.container_name,
        "psql", "-h", "127.0.0.1", "-p", "5432", "-U", harness.config.user,
        "-d", harness.config.database, "-v", "ON_ERROR_STOP=1",
    ]
    assert options["env"]["PGPASSWORD"] == harness.config.password
    harness.reset_database()
    assert calls[-1][0] == command


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


@pytest.mark.parametrize("sql,stdout,expected", [
    ("SELECT 42", "42\n", "42"),
    ("SELECT count(*) FROM fixture", "0\n", "0"),
    ("SELECT id FROM fixture WHERE false", "", ""),
    ("SELECT NULL", "\n", ""),
    ("SELECT 'INSERT 0 1'", "INSERT 0 1\n", "INSERT 0 1"),
])
def test_database_scalar_preserves_container_runner_patch(
    monkeypatch: MonkeyPatch, sql: str, stdout: str, expected: str,
) -> None:
    from repomap_test_support import postgres_container as container

    calls: list[str] = []

    def run(command: list[str], sql: str) -> CompletedProcess[str]:
        calls.append(sql)
        return CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(container, "run", run)
    database = container.PostgresContainerDatabase("127.0.0.1", 55433, "test", "test", "psql")
    assert database.psql_scalar(sql) == expected
    assert calls == [sql]


def test_database_scalar_insert_returning_suppresses_command_tag(monkeypatch: MonkeyPatch) -> None:
    from repomap_test_support import postgres_container as container

    calls: list[tuple[list[str], str]] = []
    sql = "INSERT INTO fixture(value) VALUES ('public-fixture') RETURNING id"

    def run(command: list[str], input_text: str) -> CompletedProcess[str]:
        calls.append((command, input_text))
        quiet = any(flag in command for flag in ("-q", "-qAt", "--quiet"))
        return CompletedProcess(command, 0, "42\n" if quiet else "42\nINSERT 0 1\n", "")

    monkeypatch.setattr(container, "run", run)
    database = container.PostgresContainerDatabase("127.0.0.1", 55433, "test", "test", "psql")
    assert database.psql_scalar(sql) == "42"
    assert calls == [(["psql", *database.psql_args, "-X", "-qAt", "-v", "ON_ERROR_STOP=1"], sql)]


def test_database_scalar_query_error_preserves_failure(monkeypatch: MonkeyPatch) -> None:
    from repomap_test_support import postgres_container as container

    sql = "SELECT missing_column FROM fixture"
    failure = subprocess.CalledProcessError(3, ["psql"], output="42\n", stderr="ERROR: fixture query failed")
    runner = MagicMock(side_effect=failure)
    monkeypatch.setattr(subprocess, "run", runner)
    database = container.PostgresContainerDatabase("127.0.0.1", 55433, "test", "test", "psql")
    with pytest.raises(AssertionError, match="ERROR: fixture query failed") as caught:
        database.psql_scalar(sql)
    assert caught.value.__cause__ is failure
    assert runner.call_args.kwargs["input"] == sql
    assert runner.call_args.kwargs["check"] is True
    assert "ON_ERROR_STOP=1" in runner.call_args.args[0]


def test_database_creation_preserves_connection_and_password(monkeypatch: MonkeyPatch) -> None:
    from repomap_test_support import postgres_container as container

    runner = MagicMock(return_value=CompletedProcess(["psql"], 0, "", ""))
    monkeypatch.setattr(container, "run", runner)
    database = container.PostgresContainerDatabase(
        "127.0.0.1", 55433, "test", "test", "psql", password="fixture-password",
    )
    created = database.create_database("fixture_restored")
    command, sql = runner.call_args.args
    assert sql == 'CREATE DATABASE "fixture_restored";'
    assert command == ["psql", *database.psql_args, "-X", "-qAt", "-v", "ON_ERROR_STOP=1"]
    assert created == container.PostgresContainerDatabase(
        database.host, database.port, database.user, "fixture_restored", database.psql_command, database.password,
    )
    assert database.password is not None
    assert database.password not in command and database.password not in repr(created)
    with pytest.raises(ValueError, match="test database name is invalid"):
        database.create_database('invalid";')
    assert runner.call_count == 1


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
    from common_lore_index.coordinator.configured_refresh import _psql_environment
    from repomap_test_support.postgres_container_config import build_psql_wrapper_script

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(mode=0o700)
    (bin_dir / "python3").symlink_to(sys.executable)
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "record = {'DOCKER_HOST': os.environ.get('DOCKER_HOST'), 'PGPASSWORD': os.environ.get('PGPASSWORD'), 'PGOPTIONS': os.environ.get('PGOPTIONS'), 'argv': sys.argv[1:]}\n"
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
    sanitized_env["PGOPTIONS"] = "-c role=fixture_reader -c default_transaction_read_only=on"
    subprocess.run([sys.executable, str(wrapper_forwarded_path), "-c", "SELECT 1"], env=sanitized_env, check=True)
    forwarded_data = json.loads(record_file.read_text(encoding="utf-8"))
    assert forwarded_data["DOCKER_HOST"] == "unix:///run/repomap-docker.sock"
    assert forwarded_data["PGPASSWORD"] == "test-pg-password"
    assert forwarded_data["PGOPTIONS"] == sanitized_env["PGOPTIONS"]
    assert forwarded_data["argv"][3:7] == ["PGPASSWORD", "-e", "PGOPTIONS", "test-container"]

    record_file_unf = tmp_path / "record_unforwarded.json"
    sanitized_env["TEST_RECORD_PATH"] = str(record_file_unf)
    subprocess.run([sys.executable, str(wrapper_unforwarded_path), "-c", "SELECT 1"], env=sanitized_env, check=True)
    unforwarded_data = json.loads(record_file_unf.read_text(encoding="utf-8"))
    assert unforwarded_data["DOCKER_HOST"] is None
