"""SCALE14 resource composition with exact PostgreSQL storage authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from scale11_threshold_evaluator import MetricSpec
from scale12_resource_sampling import GIB, threshold_specs as scale12_threshold_specs


_REMOVED_METRICS = frozenset(
    {"disposable_runtime_growth_bytes", "host_free_bytes"}
)


@dataclass(frozen=True)
class Scale14ResourceSample:
    """One combined public-safe resource sample."""

    monotonic_offset_seconds: int
    values: Mapping[str, int | None]
    availability: Mapping[str, str]

    def to_payload(self) -> dict[str, object]:
        """Return stable metric records without local scope identities."""

        return {
            "schema_version": 1,
            "monotonic_offset_seconds": self.monotonic_offset_seconds,
            "metrics": [
                {
                    "metric_code": code,
                    "value": self.values[code],
                    "availability": self.availability[code],
                }
                for code in sorted(self.values)
            ],
        }


class PeakRetainingReader:
    """Retain the largest available reading across one child lifetime."""

    def __init__(self, reader: Callable[[], int | None]) -> None:
        self._reader = reader
        self._peak: int | None = None

    def __call__(self) -> int | None:
        try:
            value = self._reader()
        except (FileNotFoundError, ProcessLookupError):
            if self._peak is None:
                raise
            return self._peak
        if value is not None:
            self._peak = value if self._peak is None else max(self._peak, value)
        return self._peak

    def accept(self, value: int) -> None:
        """Seed one accepted pre-release peak without invoking the reader."""

        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("peak resource value is invalid")
        self._peak = value if self._peak is None else max(self._peak, value)


class Scale14ResourceSampler:
    """Extend the accepted sampler with exact PGDATA and backing-space values."""

    def __init__(self, base_sampler, storage_authority) -> None:
        self._base = base_sampler
        self._storage = storage_authority
        self._baseline_captured = False

    def capture_baseline(self) -> Scale14ResourceSample:
        """Capture the settled storage baseline before supervised work."""

        storage = self._storage.capture_baseline()
        self._baseline_captured = storage.availability == "available"
        return self._compose(None, storage)

    def capture(self, *, force: bool = False) -> Scale14ResourceSample | None:
        """Capture one due base sample and its same-loop storage observation."""

        base = self._base.capture(force=force)
        if base is None and not force:
            return None
        capture_terminal = getattr(self._storage, "capture_terminal", None)
        storage = (
            capture_terminal()
            if force and callable(capture_terminal)
            else self._storage.capture()
        )
        return self._compose(base, storage)

    def close(self) -> None:
        """Close the bounded storage reader after its terminal sample attempt."""

        close_storage = getattr(self._storage, "close", None)
        if callable(close_storage):
            close_storage()

    def settle_startup(self) -> None:
        """Settle storage work so no reader or deferred error crosses release."""

        settle_storage = getattr(self._storage, "settle_startup", None)
        if callable(settle_storage):
            settle_storage()

    def accept_preparation_baseline(self, baseline) -> None:
        """Seed active PGDATA sampling from accepted worker evidence."""

        accept = getattr(self._storage, "accept_prepared_sample", None)
        if not callable(accept):
            raise RuntimeError("prepared storage evidence is unsupported")
        accept(
            allocated_delta_bytes=baseline.allocated_delta_bytes,
            backing_free_bytes=baseline.backing_free_bytes,
            sampling_elapsed_ns=baseline.pgdata_reader_elapsed_ns,
        )
        accept_base = getattr(self._base, "accept_prepared_values", None)
        if not callable(accept_base):
            raise RuntimeError("prepared base resource evidence is unsupported")
        accept_base(
            {
                "client_peak_rss_bytes": baseline.client_peak_rss_bytes,
                "postgresql_container_rss_upper_bound": (
                    baseline.postgresql_container_rss_upper_bound
                ),
            }
        )

    def _compose(self, base, storage) -> Scale14ResourceSample:
        values = {
            code: value
            for code, value in getattr(base, "values", {}).items()
            if code not in _REMOVED_METRICS
        }
        availability = {
            code: value
            for code, value in getattr(base, "availability", {}).items()
            if code not in _REMOVED_METRICS
        }
        storage_values = {
            "postgresql_pgdata_allocated_delta": storage.delta_bytes,
            "postgresql_pgdata_backing_free_bytes": storage.free_bytes,
            "postgresql_pgdata_reader_elapsed_ns": storage.sampling_elapsed_ns,
        }
        storage_status = storage.availability
        values.update(storage_values)
        availability.update(
            {code: storage_status for code in storage_values}
        )
        return Scale14ResourceSample(
            getattr(base, "monotonic_offset_seconds", 0),
            values,
            availability,
        )


def threshold_specs() -> tuple[MetricSpec, ...]:
    """Return accepted SCALE12 ceilings with exact SCALE14 storage replacements."""

    overrides = {
        "client_peak_rss_bytes": 6 * GIB,
        "temporary_byte_upper_bound_delta": 2 * GIB,
    }
    retained = tuple(
        MetricSpec(
            spec.category,
            overrides.get(spec.category, spec.limit),
            spec.priority,
            False
            if spec.category
            in {"temporary_byte_upper_bound_delta", "wal_upper_bound_delta"}
            else spec.counter,
            spec.lower_bound,
            spec.scope,
        )
        for spec in scale12_threshold_specs()
        if spec.category not in _REMOVED_METRICS
    )
    return (
        *retained,
        MetricSpec(
            "postgresql_pgdata_allocated_delta",
            16 * GIB,
            5,
            False,
            False,
            "owned_postgresql_pgdata",
        ),
        MetricSpec(
            "postgresql_pgdata_backing_free_bytes",
            20 * GIB,
            6,
            False,
            True,
            "owned_postgresql_pgdata_backing_filesystem",
        ),
        MetricSpec(
            "postgresql_pgdata_reader_elapsed_ns",
            1_000_000_000,
            7,
            False,
            False,
            "supervisor_reader",
        ),
    )


__all__ = [
    "PeakRetainingReader",
    "Scale14ResourceSample",
    "Scale14ResourceSampler",
    "threshold_specs",
]
