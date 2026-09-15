"""SCALE28-FIX12-DIAG1-FIX1: corrected process-boundary instrumentation.

The DIAG1 helper had two defects these tests pin closed.

One host process could produce two observations, because ``subprocess.run``
and ``subprocess.Popen.__init__`` were both wrapped while ``run`` itself
constructs a ``Popen``.

A nested ``psql`` token was reported as though it were the host executable, so
``docker exec ... psql`` was indistinguishable from a direct client
invocation.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from repomap_test_support.process_boundary import (
    POISON_PSQL_EXIT_CODE,
    PsqlInvokedError,
    RecordingProcessBoundary,
    classify_host_executable,
    poison_psql_directory,
)

NESTED_PSQL_ARGV = (
    "docker", "exec", "-i", "repomap-postgres", "psql",
    "--no-psqlrc", "-tAX", "-c", "select 1",
)


def test_one_subprocess_run_call_produces_one_host_observation(monkeypatch):
    boundary = RecordingProcessBoundary().install(monkeypatch)

    subprocess.run(
        [sys.executable, "-c", "pass"], capture_output=True, check=False
    )

    assert boundary.host_process_count == 1
    assert boundary.invocations[0].process_api == "subprocess.Popen"


def test_one_direct_popen_call_produces_one_host_observation(monkeypatch):
    boundary = RecordingProcessBoundary().install(monkeypatch)

    process = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    process.wait()

    assert boundary.host_process_count == 1


def test_check_output_still_produces_exactly_one_host_observation(monkeypatch):
    boundary = RecordingProcessBoundary().install(monkeypatch)

    subprocess.check_output([sys.executable, "-c", "print(1)"])

    assert boundary.host_process_count == 1


def test_nested_docker_psql_is_one_docker_process_and_one_psql_intent(
    monkeypatch,
):
    boundary = RecordingProcessBoundary(fail_closed_on_psql=True)
    boundary.install(monkeypatch)

    with pytest.raises(PsqlInvokedError):
        subprocess.run(list(NESTED_PSQL_ARGV), check=False)

    assert boundary.host_process_count == 1
    invocation = boundary.invocations[0]
    assert invocation.host_executable_basename == "docker"
    assert invocation.host_process_class == "container_runtime"
    assert invocation.nested_psql_token_positions == (4,)
    assert invocation.contains_nested_psql_intent is True
    assert invocation.is_host_psql_process is False

    assert boundary.host_process_count_by_class() == {"container_runtime": 1}
    assert boundary.nested_psql_intent_count == 1
    assert boundary.host_psql_process_count == 0


def test_direct_psql_is_one_host_psql_process_with_intent_at_position_zero(
    tmp_path, monkeypatch
):
    poison = poison_psql_directory(tmp_path / "bin")
    boundary = RecordingProcessBoundary().install(monkeypatch)

    result = subprocess.run(
        [str(poison), "-c", "select 1"], capture_output=True, check=False
    )

    assert result.returncode == POISON_PSQL_EXIT_CODE
    assert boundary.host_process_count == 1
    invocation = boundary.invocations[0]
    assert invocation.host_executable_basename == "psql"
    assert invocation.host_process_class == "psql"
    assert invocation.nested_psql_token_positions == (0,)
    assert invocation.is_host_psql_process is True

    assert boundary.host_psql_process_count == 1
    assert boundary.nested_psql_intent_count == 1


def test_counts_by_host_executable_never_substitute_a_nested_token(
    monkeypatch,
):
    boundary = RecordingProcessBoundary(fail_closed_on_psql=True)
    boundary.install(monkeypatch)

    with pytest.raises(PsqlInvokedError):
        subprocess.run(list(NESTED_PSQL_ARGV), check=False)

    counts = boundary.counts_by_host_executable()

    assert counts == {"docker": 1}
    assert "psql" not in counts


def test_fail_closed_detection_raises_before_the_host_child_is_created(
    tmp_path, monkeypatch
):
    sentinel = tmp_path / "child-ran"
    boundary = RecordingProcessBoundary(fail_closed_on_psql=True)
    boundary.install(monkeypatch)

    with pytest.raises(PsqlInvokedError):
        subprocess.run(
            [
                sys.executable, "-c",
                f"open({str(sentinel)!r}, 'w').write('x')",
                "psql",
            ],
            check=False,
        )

    assert not sentinel.exists()


def test_path_poison_alone_misses_a_nested_psql_invocation(
    tmp_path, monkeypatch
):
    """The trap the DIAG1 review caught: PATH poisoning is not sufficient."""
    poison = poison_psql_directory(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{poison.parent}{os.pathsep}{os.environ['PATH']}")
    log = poison.parent / "psql-invocations.log"

    result = subprocess.run(
        [sys.executable, "-c", "pass", "psql"], capture_output=True, check=False
    )

    assert result.returncode == 0
    assert not log.exists()


def test_whole_argv_detection_catches_what_the_path_poison_misses(
    tmp_path, monkeypatch
):
    poison = poison_psql_directory(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{poison.parent}{os.pathsep}{os.environ['PATH']}")
    boundary = RecordingProcessBoundary().install(monkeypatch)

    subprocess.run(
        [sys.executable, "-c", "pass", "psql"], capture_output=True, check=False
    )

    log = poison.parent / "psql-invocations.log"
    assert not log.exists()
    assert boundary.nested_psql_intent_count == 1
    assert boundary.host_psql_process_count == 0


@pytest.mark.parametrize(
    "basename,expected",
    [
        ("psql", "psql"),
        ("docker", "container_runtime"),
        ("podman", "container_runtime"),
        ("pg_dump", "postgres_client"),
        ("python3.13", "python"),
        ("go", "go_toolchain"),
        ("golangci-lint", "go_toolchain"),
        ("sh", "other"),
    ],
)
def test_host_executable_classification_is_bounded(basename, expected):
    assert classify_host_executable(basename) == expected


def test_exec_family_is_a_distinct_non_overlapping_owner(monkeypatch):
    """os.execvpe never reaches Popen, so it needs its own owner."""
    replaced = []
    # Stand in for the real image replacement before instrumenting, so the
    # owner wraps a call that returns instead of never coming back.
    monkeypatch.setattr(
        os, "execvpe", lambda file, argv, env: replaced.append(argv)
    )

    boundary = RecordingProcessBoundary()
    boundary.install(monkeypatch)
    boundary.install_exec_owner(monkeypatch)

    getattr(os, "execvpe")("python3", ["python3", "-c", "pass"], {})

    assert replaced == [["python3", "-c", "pass"]]
    assert boundary.host_process_count == 1
    assert boundary.invocations[0].process_api == "os.execvpe"
    assert boundary.invocations[0].host_executable_basename == "python3"
