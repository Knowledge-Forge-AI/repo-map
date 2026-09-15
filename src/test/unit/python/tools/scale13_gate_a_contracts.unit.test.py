from __future__ import annotations

import pytest

from scale12_resource_sampling import Scale12ResourceSample
from scale13_gate_a_contracts import (
    Scale13GateAContractError,
    validate_gate_a_backend_summary,
    validate_gate_a_resource_sample,
)


def _sample(**availability_overrides: str) -> Scale12ResourceSample:
    values = {
        "client_peak_rss_bytes": 1,
        "owned_postgresql_process_group_rss_bytes": None,
        "postgresql_container_rss_upper_bound": 2,
        "temporary_byte_upper_bound_delta": 3,
        "wal_upper_bound_delta": 4,
        "disposable_runtime_growth_bytes": 5,
        "host_free_bytes": 6,
        "concurrent_profiles": 1,
    }
    availability = {
        code: "available" if value is not None else "unavailable"
        for code, value in values.items()
    }
    availability.update(availability_overrides)
    return Scale12ResourceSample(0, values, availability)


def test_gate_a_resource_contract_accepts_container_upper_bound_fallback() -> None:
    validate_gate_a_resource_sample(_sample())


@pytest.mark.parametrize(
    ("metric_code", "status", "error"),
    (
        ("wal_upper_bound_delta", "unavailable", "resource_reader_unavailable"),
        (
            "temporary_byte_upper_bound_delta",
            "counter_reset_or_wrap",
            "counter_authority_lost",
        ),
    ),
)
def test_gate_a_resource_contract_fails_closed_on_reader_loss(
    metric_code: str,
    status: str,
    error: str,
) -> None:
    with pytest.raises(Scale13GateAContractError, match=error):
        validate_gate_a_resource_sample(_sample(**{metric_code: status}))


def test_gate_a_backend_contract_rejects_ambient_and_missing_owned() -> None:
    with pytest.raises(Scale13GateAContractError, match="ownership"):
        validate_gate_a_backend_summary(
            {"observer": 1, "ambient_client": 1},
            require_owned=True,
        )
    with pytest.raises(Scale13GateAContractError, match="ownership"):
        validate_gate_a_backend_summary({"observer": 1}, require_owned=True)


def test_gate_a_backend_contract_accepts_exact_owned_client() -> None:
    validate_gate_a_backend_summary(
        {"observer": 1, "direct_owned_client": 1},
        require_owned=True,
    )
