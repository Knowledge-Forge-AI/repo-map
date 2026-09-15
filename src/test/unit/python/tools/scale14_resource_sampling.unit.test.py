from __future__ import annotations

import json
from types import SimpleNamespace

from scale14_postgres_storage import PostgresStorageSample
from scale14_resource_sampling import (
    PeakRetainingReader,
    Scale14ResourceSampler,
    threshold_specs,
)


def test_peak_reader_retains_settled_child_value_after_process_exit() -> None:
    values = iter((17, ProcessLookupError()))

    def read():
        value = next(values)
        if isinstance(value, BaseException):
            raise value
        return value

    reader = PeakRetainingReader(read)

    assert reader() == 17
    assert reader() == 17


def test_peak_retaining_reader_keeps_last_peak_after_reader_loss() -> None:
    values = iter((10, 8, None))
    reader = PeakRetainingReader(lambda: next(values))

    assert (reader(), reader(), reader()) == (10, 10, 10)


def test_peak_retaining_reader_accepts_prepared_peak_before_reader_loss() -> None:
    reader = PeakRetainingReader(lambda: (_ for _ in ()).throw(ProcessLookupError))

    reader.accept(12)

    assert reader() == 12


class _BaseSampler:
    def capture(self, *, force: bool = False):
        return SimpleNamespace(
            monotonic_offset_seconds=2,
            values={
                "elapsed_seconds": 2,
                "client_peak_rss_bytes": 100,
                "disposable_runtime_growth_bytes": 999,
                "host_free_bytes": 888,
            },
            availability={
                "elapsed_seconds": "available",
                "client_peak_rss_bytes": "available",
                "disposable_runtime_growth_bytes": "available",
                "host_free_bytes": "available",
            },
        )


class _Storage:
    def capture_baseline(self):
        return _storage_sample(10, 0, 900)

    def capture(self):
        return _storage_sample(14, 4, 800)


def _storage_sample(current: int, delta: int, free: int):
    return PostgresStorageSample(
        "postgresql_pgdata_allocated_delta",
        "owned_postgresql_pgdata",
        10,
        current,
        delta,
        free,
        "available",
        False,
        25,
    )


def test_scale14_resource_sampler_replaces_weak_runtime_metrics() -> None:
    sampler = Scale14ResourceSampler(_BaseSampler(), _Storage())
    sampler.capture_baseline()

    sample = sampler.capture(force=True)

    assert sample is not None
    assert sample.values["postgresql_pgdata_allocated_delta"] == 4
    assert sample.values["postgresql_pgdata_backing_free_bytes"] == 800
    assert sample.values["postgresql_pgdata_reader_elapsed_ns"] == 25
    assert "disposable_runtime_growth_bytes" not in sample.values
    assert "host_free_bytes" not in sample.values


def test_scale14_resource_projection_and_specs_are_exact_and_path_free() -> None:
    sampler = Scale14ResourceSampler(_BaseSampler(), _Storage())
    sampler.capture_baseline()
    sample = sampler.capture(force=True)
    assert sample is not None

    encoded = json.dumps(sample.to_payload(), sort_keys=True)
    specs = {spec.category: spec for spec in threshold_specs()}

    assert "/private/" not in encoded
    assert specs["postgresql_pgdata_allocated_delta"].scope == (
        "owned_postgresql_pgdata"
    )
    assert specs["postgresql_pgdata_backing_free_bytes"].lower_bound is True
    assert specs["client_peak_rss_bytes"].limit == 6 * 1024**3
    assert specs["temporary_byte_upper_bound_delta"].limit == 2 * 1024**3
    assert specs["temporary_byte_upper_bound_delta"].counter is False
    assert specs["wal_upper_bound_delta"].counter is False
    assert specs["postgresql_pgdata_allocated_delta"].counter is False
    assert "disposable_runtime_growth_bytes" not in specs
    assert "host_free_bytes" not in specs
