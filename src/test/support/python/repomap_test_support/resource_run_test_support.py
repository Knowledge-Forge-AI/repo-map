"""Controlled admitted host signals for semantic test-resource-run modules."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os

from repomap_test_support.resource_admission import HostSignals, MemoryPressure
from repomap_test_support.resource_hygiene_policy import GIB
from repomap_test_support import resource_run


def admitted_host_signals(
    *,
    free_disk_bytes: int = 200 * GIB,
    free_disk_percent: int = 50,
    memory_pressure: MemoryPressure = MemoryPressure.NORMAL,
    docker_responsive: bool | None = None,
    live_mutating_runs: int = 0,
    operator_attested_exclusive: bool = False,
    operator_attested_pressure_degradation: bool = False,
    campaign_plan_id: str | None = None,
    declared_complete_gates: int = 0,
    buildkit_image_present: bool | None = None,
    memory_free_percent: int | None = None,
) -> HostSignals:
    """Return signals clearing every profile disk floor without host observation.

    Semantic run tests assert post-admission behaviour, so they must not consume
    whatever free disk the developer or CI machine happens to have. Profiles
    beyond ORDINARY also gate on docker and attestation; those call sites
    override the relevant fields.
    """
    return HostSignals(
        free_disk_bytes=free_disk_bytes,
        free_disk_percent=free_disk_percent,
        memory_pressure=memory_pressure,
        docker_responsive=docker_responsive,
        live_mutating_runs=live_mutating_runs,
        operator_attested_exclusive=operator_attested_exclusive,
        operator_attested_pressure_degradation=operator_attested_pressure_degradation,
        campaign_plan_id=campaign_plan_id,
        declared_complete_gates=declared_complete_gates,
        buildkit_image_present=buildkit_image_present,
        memory_free_percent=memory_free_percent,
    )


@contextmanager
def preserve_resource_run_process_state() -> Iterator[None]:
    """Restore the exact active owner and ledger binding after a test seam."""
    active = resource_run.active_resource_run()
    ledger_present = resource_run.ENV_RESOURCE_LEDGER in os.environ
    ledger_value = (
        os.environ[resource_run.ENV_RESOURCE_LEDGER] if ledger_present else ""
    )
    try:
        yield
    finally:
        resource_run._ACTIVE_RESOURCE_RUN = active
        if ledger_present:
            os.environ[resource_run.ENV_RESOURCE_LEDGER] = ledger_value
        else:
            os.environ.pop(resource_run.ENV_RESOURCE_LEDGER, None)


__all__ = ["admitted_host_signals", "preserve_resource_run_process_state"]
