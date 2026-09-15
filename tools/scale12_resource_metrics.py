"""Metric contracts and cadence logic for SCALE12 resource sampling."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
import time
from typing import Protocol, TypeAlias

from scale11_threshold_evaluator import MetricSpec


GIB = 1024**3


class ResourceSamplingError(ValueError):
    """Raised when a live resource observation violates the closed contract."""


def process_tree_rss_bytes(
    root_process_id: int,
    rows: tuple[tuple[int, int, int], ...],
) -> int | None:
    """Sum KiB RSS for one process and its transitive descendants."""

    owned = {root_process_id}
    changed = True
    while changed:
        changed = False
        for process_id, parent_process_id, _rss_kib in rows:
            if parent_process_id in owned and process_id not in owned:
                owned.add(process_id)
                changed = True
    values = [rss_kib for process_id, _parent, rss_kib in rows if process_id in owned]
    if not values:
        return None
    return sum(values) * 1024


def parse_container_memory_bytes(value: str) -> int:
    """Parse one Docker-compatible memory quantity without accepting negatives."""

    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(B|kB|MB|GB|KiB|MiB|GiB)", value)
    if match is None:
        raise ResourceSamplingError("container memory value is invalid")
    scales = {
        "B": 1,
        "kB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
    }
    try:
        parsed = Decimal(match.group(1)) * scales[match.group(2)]
    except InvalidOperation as error:
        raise ResourceSamplingError("container memory value is invalid") from error
    return int(parsed)


class DockerClient(Protocol):
    """Minimal client contract shared by bounded container readers."""

    @property
    def api_version(self) -> str: ...

    def version(self) -> object: ...

    def info(self) -> object: ...

    def inspect_container(self, container: str) -> object: ...

    def stats(
        self, container: str, *, stream: bool = ..., one_shot: bool = ...,
    ) -> object: ...

    def close(self) -> None: ...


DockerClientOpen: TypeAlias = tuple[DockerClient, str]


@dataclass(frozen=True)
class ResourceMetricDescriptor:
    """One closed resource metric with scope and threshold semantics."""

    metric_code: str
    scope: str
    limit: int
    priority: int
    counter: bool = False
    lower_bound: bool = False
    upper_bound: bool = False


RESOURCE_METRICS = (
    ResourceMetricDescriptor("elapsed_seconds", "supervisor", 300, 0),
    ResourceMetricDescriptor("client_peak_rss_bytes", "child_process", GIB, 1),
    ResourceMetricDescriptor(
        "owned_postgresql_process_group_rss_bytes",
        "owned_postgresql_process_group",
        2 * GIB,
        2,
    ),
    ResourceMetricDescriptor(
        "postgresql_container_rss_upper_bound",
        "scale_owned_postgresql_container",
        2 * GIB,
        2,
        upper_bound=True,
    ),
    ResourceMetricDescriptor(
        "temporary_byte_upper_bound_delta",
        "current_database",
        4 * GIB,
        3,
        counter=True,
        upper_bound=True,
    ),
    ResourceMetricDescriptor(
        "wal_upper_bound_delta",
        "current_database",
        8 * GIB,
        4,
        counter=True,
        upper_bound=True,
    ),
    ResourceMetricDescriptor(
        "disposable_runtime_growth_bytes",
        "disposable_runtime",
        16 * GIB,
        5,
        counter=True,
        upper_bound=True,
    ),
    ResourceMetricDescriptor(
        "host_free_bytes",
        "host_filesystem",
        20 * GIB,
        6,
        lower_bound=True,
    ),
    ResourceMetricDescriptor("concurrent_profiles", "supervisor", 1, 7),
)
_DESCRIPTORS = {item.metric_code: item for item in RESOURCE_METRICS}


@dataclass(frozen=True)
class Scale12ResourceSample:
    """One bounded resource sample without local or target identities."""

    monotonic_offset_seconds: int
    values: Mapping[str, int | None]
    availability: Mapping[str, str]

    def to_payload(self) -> dict[str, object]:
        """Return a versioned public-safe projection with explicit scopes."""

        return {
            "schema_version": 1,
            "monotonic_offset_seconds": self.monotonic_offset_seconds,
            "metrics": [
                {
                    "metric_code": descriptor.metric_code,
                    "scope": descriptor.scope,
                    "upper_bound": descriptor.upper_bound,
                    "value": self.values[descriptor.metric_code],
                    "availability": self.availability[descriptor.metric_code],
                }
                for descriptor in RESOURCE_METRICS
            ],
        }


class Scale12ResourceSampler:
    """Sample injected resource readers at a bounded monotonic cadence."""

    def __init__(
        self,
        readers: Mapping[str, Callable[[], int | None]],
        *,
        clock_ns: Callable[[], int] | None = None,
        cadence_ns: int = 1_000_000_000,
    ) -> None:
        if (
            isinstance(cadence_ns, bool)
            or not isinstance(cadence_ns, int)
            or cadence_ns < 1
        ):
            raise ResourceSamplingError("resource cadence is invalid")
        if not set(readers) <= set(_DESCRIPTORS) - {
            "elapsed_seconds",
            "concurrent_profiles",
        }:
            raise ResourceSamplingError("resource reader metric is invalid")
        self._readers = dict(readers)
        self._clock_ns = time.monotonic_ns if clock_ns is None else clock_ns
        self._cadence_ns = cadence_ns
        self._started_ns: int | None = None
        self._next_sample_ns: int | None = None
        self._counter_baselines: dict[str, int] = {}
        self._previous_counters: dict[str, int] = {}

    def accept_prepared_values(self, values: Mapping[str, int]) -> None:
        """Seed peak readers from accepted isolated preparation evidence."""

        for metric_code in (
            "client_peak_rss_bytes",
            "postgresql_container_rss_upper_bound",
        ):
            value = values.get(metric_code)
            reader = self._readers.get(metric_code)
            accept = getattr(reader, "accept", None)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or not callable(accept)
            ):
                raise ResourceSamplingError(
                    "prepared resource sample is invalid"
                )
            accept(value)

    def capture(self, *, force: bool = False) -> Scale12ResourceSample | None:
        """Capture one due sample or return ``None`` before the next cadence."""

        now_ns = self._clock_ns()
        if not isinstance(now_ns, int) or isinstance(now_ns, bool) or now_ns < 0:
            raise ResourceSamplingError("resource clock value is invalid")
        if self._started_ns is None:
            self._started_ns = now_ns
            self._next_sample_ns = now_ns
        assert self._next_sample_ns is not None
        if not force and now_ns < self._next_sample_ns:
            return None
        self._next_sample_ns = now_ns + self._cadence_ns

        values: dict[str, int | None] = {
            "elapsed_seconds": (now_ns - self._started_ns) // 1_000_000_000,
            "concurrent_profiles": 1,
        }
        availability = {
            "elapsed_seconds": "available",
            "concurrent_profiles": "available",
        }
        for descriptor in RESOURCE_METRICS[1:-1]:
            raw_value = self._read_value(descriptor.metric_code)
            value, status = self._normalize(descriptor, raw_value)
            values[descriptor.metric_code] = value
            availability[descriptor.metric_code] = status
        return Scale12ResourceSample(
            values["elapsed_seconds"] or 0,
            values,
            availability,
        )

    def _read_value(self, metric_code: str) -> int | None:
        reader = self._readers.get(metric_code)
        if reader is None:
            return None
        try:
            value = reader()
        except OSError:
            return None
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ResourceSamplingError("resource sample value is invalid")
        return value

    def _normalize(
        self,
        descriptor: ResourceMetricDescriptor,
        raw_value: int | None,
    ) -> tuple[int | None, str]:
        if raw_value is None:
            return None, "unavailable"
        if not descriptor.counter:
            return raw_value, "available"
        previous = self._previous_counters.get(descriptor.metric_code)
        baseline = self._counter_baselines.setdefault(
            descriptor.metric_code, raw_value
        )
        self._previous_counters[descriptor.metric_code] = raw_value
        if previous is not None and raw_value < previous:
            return None, "counter_reset_or_wrap"
        return raw_value - baseline, "available"


def threshold_specs() -> tuple[MetricSpec, ...]:
    """Return SCALE12 outer ceilings in deterministic stop-priority order."""

    return tuple(
        MetricSpec(
            descriptor.metric_code,
            descriptor.limit,
            descriptor.priority,
            descriptor.counter,
            descriptor.lower_bound,
            descriptor.scope,
        )
        for descriptor in RESOURCE_METRICS
    )
