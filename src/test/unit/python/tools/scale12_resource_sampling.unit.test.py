from __future__ import annotations

import json
import subprocess
import time

import pytest

import scale12_resource_sampling as resource_sampling
import scale12_resource_readers as resource_readers

from scale12_resource_sampling import (
    RESOURCE_METRICS,
    ResourceSamplingError,
    Scale12ResourceSampler,
    parse_container_memory_bytes,
    process_tree_rss_bytes,
    threshold_specs,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 1_000_000_000

    def __call__(self) -> int:
        return self.value


def test_resource_sampler_enforces_cadence_and_records_elapsed() -> None:
    clock = _Clock()
    sampler = Scale12ResourceSampler({}, clock_ns=clock, cadence_ns=1_000_000_000)

    first = sampler.capture()
    assert first is not None
    assert first.values["elapsed_seconds"] == 0
    assert sampler.capture() is None

    clock.value += 1_000_000_000
    second = sampler.capture()
    assert second is not None
    assert second.values["elapsed_seconds"] == 1


def test_resource_sampler_derives_counter_deltas_and_detects_reset() -> None:
    clock = _Clock()
    temporary = iter((100, 150, 20))
    sampler = Scale12ResourceSampler(
        {"temporary_byte_upper_bound_delta": lambda: next(temporary)},
        clock_ns=clock,
        cadence_ns=1,
    )

    first = sampler.capture()
    clock.value += 1
    second = sampler.capture()
    clock.value += 1
    third = sampler.capture()

    assert first is not None and first.values["temporary_byte_upper_bound_delta"] == 0
    assert second is not None and second.values["temporary_byte_upper_bound_delta"] == 50
    assert third is not None
    assert third.values["temporary_byte_upper_bound_delta"] is None
    assert third.availability["temporary_byte_upper_bound_delta"] == "counter_reset_or_wrap"


def test_resource_sampler_marks_unavailable_and_rejects_malformed_values() -> None:
    sampler = Scale12ResourceSampler(
        {
            "client_peak_rss_bytes": lambda: None,
            "host_free_bytes": lambda: -1,
        },
        cadence_ns=1,
    )

    with pytest.raises(ResourceSamplingError, match="value"):
        sampler.capture()

    unavailable = Scale12ResourceSampler(
        {"client_peak_rss_bytes": lambda: None}, cadence_ns=1
    ).capture()
    assert unavailable is not None
    assert unavailable.availability["client_peak_rss_bytes"] == "unavailable"
    assert unavailable.values["owned_postgresql_process_group_rss_bytes"] is None


def test_resource_sampler_seeds_prepared_peak_readers() -> None:
    class Peak:
        def __init__(self):
            self.value = None

        def accept(self, value):
            self.value = value

        def __call__(self):
            return self.value

    client = Peak()
    container = Peak()
    sampler = Scale12ResourceSampler(
        {
            "client_peak_rss_bytes": client,
            "postgresql_container_rss_upper_bound": container,
        },
        cadence_ns=1,
    )

    sampler.accept_prepared_values(
        {
            "client_peak_rss_bytes": 10,
            "postgresql_container_rss_upper_bound": 20,
        }
    )
    sample = sampler.capture()

    assert sample is not None
    assert sample.values["client_peak_rss_bytes"] == 10
    assert sample.values["postgresql_container_rss_upper_bound"] == 20


def test_resource_registry_preserves_upper_bounds_and_host_floor() -> None:
    descriptors = {item.metric_code: item for item in RESOURCE_METRICS}
    specs = {item.category: item for item in threshold_specs()}

    assert descriptors["wal_upper_bound_delta"].upper_bound is True
    assert descriptors["temporary_byte_upper_bound_delta"].upper_bound is True
    assert descriptors["owned_postgresql_process_group_rss_bytes"].scope == (
        "owned_postgresql_process_group"
    )
    assert specs["host_free_bytes"].lower_bound is True
    assert specs["host_free_bytes"].limit == 20 * 1024**3


def test_resource_sample_projection_is_bounded_and_contains_no_source_values() -> None:
    sample = Scale12ResourceSampler(
        {"client_peak_rss_bytes": lambda: 123}, cadence_ns=1
    ).capture()
    assert sample is not None

    encoded = json.dumps(sample.to_payload(), sort_keys=True, separators=(",", ":"))

    assert len(encoded.encode("utf-8")) < 65_536
    assert "client_peak_rss_bytes" in encoded
    for forbidden in (
        "/private/",
        "database_name",
        "backend_pid",
        "repository",
        "graph_id",
        '"sql"',
    ):
        assert forbidden not in encoded.lower()


def test_process_tree_rss_sums_only_owned_descendants() -> None:
    assert process_tree_rss_bytes(
        10,
        (
            (10, 1, 100),
            (11, 10, 20),
            (12, 11, 30),
            (13, 99, 400),
        ),
    ) == 150 * 1024


def test_container_memory_parser_preserves_upper_bound_units() -> None:
    assert parse_container_memory_bytes("1.5GiB") == 1.5 * 1024**3
    assert parse_container_memory_bytes("750MB") == 750_000_000
    with pytest.raises(ResourceSamplingError, match="container memory"):
        parse_container_memory_bytes("unavailable")


def test_container_growth_uses_facade_command_seam_without_reader_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_runner = resource_readers._run_bounded_text_command
    original_validator = resource_readers._validate_container_reader_inputs
    calls: list[tuple[tuple[str, ...], float]] = []

    def command_runner(
        arguments: tuple[str, ...], *, timeout_seconds: float
    ) -> subprocess.CompletedProcess[str]:
        calls.append((arguments, timeout_seconds))
        return subprocess.CompletedProcess(arguments, 0, "123\n", "")

    monkeypatch.setattr(resource_sampling, "_run_bounded_text_command", command_runner)

    assert resource_sampling.read_container_growth_bytes(
        "docker", "public-postgres"
    ) == 123
    assert calls == [
        (
            ("docker", "inspect", "--size", "--format", "{{.SizeRw}}", "public-postgres"),
            5.0,
        )
    ]
    assert resource_readers._run_bounded_text_command is original_runner
    assert resource_readers._validate_container_reader_inputs is original_validator


def test_docker_facade_dependencies_are_call_local(monkeypatch: pytest.MonkeyPatch) -> None:
    client = object()
    fake_docker = type(
        "_Docker",
        (),
        {"APIClient": staticmethod(lambda **_kwargs: client)},
    )()
    fake_context = type(
        "_Context",
        (),
        {
            "kwargs_from_context": staticmethod(
                lambda **_kwargs: {"base_url": "unix:///public/context.sock"}
            )
        },
    )
    originals = (
        resource_readers.docker,
        resource_readers.ContextAPI,
        resource_readers.kwargs_from_env,
        resource_readers.psutil,
    )
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "unix:///public/docker.sock")
    monkeypatch.setattr(resource_sampling, "docker", fake_docker)
    monkeypatch.setattr(resource_sampling, "ContextAPI", fake_context)
    monkeypatch.setattr(
        resource_sampling,
        "kwargs_from_env",
        lambda **_kwargs: {"base_url": "unix:///public/docker.sock"},
    )
    monkeypatch.setattr(resource_sampling, "psutil", object())

    assert resource_sampling._create_docker_api_client("docker") == (
        client,
        "unix_socket",
    )
    assert (
        resource_readers.docker,
        resource_readers.ContextAPI,
        resource_readers.kwargs_from_env,
        resource_readers.psutil,
    ) == originals


def test_bounded_command_capture_terminates_inherited_output_holders(tmp_path) -> None:
    runtime = tmp_path / "blocking-runtime"
    runtime.write_text(
        """#!/usr/bin/env python3
import subprocess
import sys
import time

subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(1)"],
    stdout=sys.stdout,
    stderr=sys.stderr,
)
time.sleep(1)
""",
        encoding="utf-8",
    )
    runtime.chmod(0o755)

    started = time.monotonic()
    completed = resource_sampling._run_bounded_text_command(
        (str(runtime),), timeout_seconds=0.05
    )

    assert completed is None
    assert time.monotonic() - started < 0.75


def test_bounded_command_teardown_reaps_after_direct_kill(monkeypatch) -> None:
    class _Process(subprocess.Popen[str]):
        pid = 17

        def __init__(self):
            self.wait_calls = 0
            self.kill_calls = 0

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired("public", 1)
            return -9

        def kill(self):
            self.kill_calls += 1

    process = _Process()
    monkeypatch.setattr(resource_sampling.os, "name", "non-posix")

    resource_sampling._terminate_bounded_process(process)

    assert process.kill_calls == 2
    assert process.wait_calls == 2
