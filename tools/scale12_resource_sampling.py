"""Compatibility facade for bounded public-safe SCALE12 resource sampling."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
import subprocess
import time

try:
    import docker
    from docker.context import ContextAPI
    from docker.utils import kwargs_from_env
    import psutil
    import requests
except ModuleNotFoundError as error:
    raise RuntimeError(
        "SCALE operational resource sampling requires the scale-tools extra; "
        "install with python3 -m pip install -e '.[test,scale-tools,static-analysis]'"
    ) from error

from scale12_resource_metrics import (
    GIB,
    RESOURCE_METRICS,
    ResourceMetricDescriptor,
    ResourceSamplingError,
    Scale12ResourceSample,
    Scale12ResourceSampler as _MetricResourceSampler,
    _DESCRIPTORS,
    parse_container_memory_bytes,
    process_tree_rss_bytes,
    threshold_specs,
)
import scale12_resource_readers as _readers
from scale12_resource_readers import (
    DockerClientOpen,
    _CONTAINER_COMMAND_OUTPUT_LIMIT_BYTES,
    _CONTAINER_COMMAND_TIMEOUT_SECONDS,
    _CONTAINER_STATS_TIMEOUT_SECONDS,
    _DOCKER_READ_ERRORS,
    _PROCESS_REAP_TIMEOUT_SECONDS,
    _PSUTIL_READ_ERRORS,
    _container_stats_memory_bytes,
    _docker_transport_class,
    _read_psutil_process_rss,
    _terminate_bounded_process as _reader_terminate_bounded_process,
    _validate_container_reader_inputs,
    directory_size_bytes,
    host_free_bytes,
    read_cluster_wal_bytes,
    read_database_size_bytes,
    read_database_temporary_bytes,
    read_postmaster_process_id,
)


__all__ = [
    "GIB",
    "RESOURCE_METRICS",
    "ResourceMetricDescriptor",
    "ResourceSamplingError",
    "Scale12ResourceSample",
    "Scale12ResourceSampler",
    "threshold_specs",
    "read_process_rss_bytes",
    "read_process_tree_rss_bytes",
    "process_tree_rss_bytes",
    "read_postmaster_process_id",
    "directory_size_bytes",
    "host_free_bytes",
    "read_database_temporary_bytes",
    "read_cluster_wal_bytes",
    "read_database_size_bytes",
    "parse_container_memory_bytes",
    "read_container_rss_upper_bound",
    "read_container_growth_bytes",
    "_DESCRIPTORS",
    "_CONTAINER_COMMAND_OUTPUT_LIMIT_BYTES",
    "_CONTAINER_COMMAND_TIMEOUT_SECONDS",
    "_CONTAINER_STATS_TIMEOUT_SECONDS",
    "_DOCKER_READ_ERRORS",
    "_PROCESS_REAP_TIMEOUT_SECONDS",
    "_PSUTIL_READ_ERRORS",
    "_container_stats_memory_bytes",
    "_create_docker_api_client",
    "_docker_client_parameters",
    "_docker_transport_class",
    "_read_psutil_process_rss",
    "_run_bounded_text_command",
    "_terminate_bounded_process",
    "_validate_container_reader_inputs",
    "os",
    "psutil",
    "requests",
]


class Scale12ResourceSampler(_MetricResourceSampler):
    """Preserve the facade clock seam while using the metrics implementation."""

    def __init__(
        self,
        readers: Mapping[str, Callable[[], int | None]],
        *,
        clock_ns: Callable[[], int] | None = None,
        cadence_ns: int = 1_000_000_000,
    ) -> None:
        super().__init__(
            readers,
            clock_ns=time.monotonic_ns if clock_ns is None else clock_ns,
            cadence_ns=cadence_ns,
        )


read_process_rss_bytes = _readers.read_process_rss_bytes
read_process_tree_rss_bytes = _readers.read_process_tree_rss_bytes


def read_container_rss_upper_bound(
    runtime: str,
    container_name: str,
) -> int | None:
    """Read container RSS through the facade's patchable Docker seams."""

    return _readers.read_container_rss_upper_bound(
        runtime,
        container_name,
        create_client=_create_docker_api_client,
        stats_reader=_container_stats_memory_bytes,
        validate_inputs=_validate_container_reader_inputs,
        monotonic=time.monotonic,
    )


def _create_docker_api_client(runtime: str) -> DockerClientOpen | None:
    """Open one Docker API client using patchable facade resolvers."""

    return _readers._create_docker_api_client(
        runtime,
        api_client_factory=docker.APIClient,
        kwargs_from_env_func=kwargs_from_env,
        context_from_env=ContextAPI.kwargs_from_context,
    )


def _docker_client_parameters(runtime: str) -> dict[str, object] | None:
    return _readers._docker_client_parameters(
        runtime,
        kwargs_from_env_func=kwargs_from_env,
        context_from_env=ContextAPI.kwargs_from_context,
    )


def read_container_growth_bytes(runtime: str, container_name: str) -> int | None:
    """Read container growth through the facade's patchable command seam."""

    return _readers.read_container_growth_bytes(
        runtime,
        container_name,
        run_command=_run_bounded_text_command,
        validate_inputs=_validate_container_reader_inputs,
    )


def _run_bounded_text_command(
    arguments: tuple[str, ...], *, timeout_seconds: float
) -> subprocess.CompletedProcess[str] | None:
    return _readers._run_bounded_text_command(
        arguments,
        timeout_seconds=timeout_seconds,
        terminate_process=_terminate_bounded_process,
    )


_terminate_bounded_process = _reader_terminate_bounded_process
