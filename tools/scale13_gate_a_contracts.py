"""Fail-closed validation for SCALE13 actual-path resource and ownership proof."""

from __future__ import annotations

from collections.abc import Mapping

from scale12_resource_sampling import Scale12ResourceSample


class Scale13GateAContractError(RuntimeError):
    """A required Gate A observation is unavailable or ambiguous."""


_REQUIRED_METRICS = (
    "client_peak_rss_bytes",
    "temporary_byte_upper_bound_delta",
    "wal_upper_bound_delta",
    "disposable_runtime_growth_bytes",
    "host_free_bytes",
    "concurrent_profiles",
)
_POSTGRES_RSS_METRICS = (
    "owned_postgresql_process_group_rss_bytes",
    "postgresql_container_rss_upper_bound",
)


def validate_gate_a_resource_sample(sample: Scale12ResourceSample) -> None:
    """Require every launch reader and one truthful PostgreSQL RSS scope."""

    if any(
        status == "counter_reset_or_wrap"
        for status in sample.availability.values()
    ):
        raise Scale13GateAContractError("counter_authority_lost")
    for metric_code in _REQUIRED_METRICS:
        if (
            sample.availability.get(metric_code) != "available"
            or sample.values.get(metric_code) is None
        ):
            raise Scale13GateAContractError("resource_reader_unavailable")
    if sample.values["concurrent_profiles"] != 1:
        raise Scale13GateAContractError("concurrent_attempt_count_invalid")
    available_postgres_rss = [
        metric_code
        for metric_code in _POSTGRES_RSS_METRICS
        if sample.availability.get(metric_code) == "available"
        and sample.values.get(metric_code) is not None
    ]
    if len(available_postgres_rss) != 1:
        raise Scale13GateAContractError("resource_reader_unavailable")


def validate_gate_a_backend_summary(
    summary: Mapping[str, int],
    *,
    require_owned: bool,
) -> None:
    """Require exact observer ownership with no ambient or unknown clients."""

    if summary.get("observer", 0) != 1:
        raise Scale13GateAContractError("backend_ownership_unknown")
    if summary.get("ambient_client", 0) or summary.get("unknown", 0):
        raise Scale13GateAContractError("backend_ownership_unknown")
    if require_owned and summary.get("direct_owned_client", 0) < 1:
        raise Scale13GateAContractError("backend_ownership_unknown")
