from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from scale28_observer_deadlines import DEFAULT_OBSERVER_DEADLINE_POLICY
from repomap_test_support.test_cov5k_r2_observer_protocol import (
    ADR_0046_EXPECTATIONS,
    FROZEN_SUCCESSOR_SOURCE_DIGESTS,
    POLICY_DIGEST,
    SOURCE_MANIFEST_DIGEST,
    OperationAuthority,
    QualificationPlan,
    guard_support_independence,
    verify_enacted_operations,
    verify_product_observation,
    verify_qualification_plan,
    verify_source_freeze,
)


_ROOT = Path(__file__).resolve().parents[5]
_MEASUREMENT = (
    _ROOT
    / "src/test/support/python/repomap_test_support"
    / "test_cov5g_r1_measurement.py"
)
_PROCESS = (
    _ROOT
    / "src/test/support/python/repomap_test_support"
    / "test_cov5g_r1_process.py"
)


def _product(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "server_statement_timeout_ms": 400,
        "client_cancel_after_seconds": 0.45,
        "cancel_request_timeout_seconds": 0.25,
        "cancel_request_max_seconds": 0.3,
        "cancel_request_publication_margin_seconds": 0.05,
        "request_terminal_timeout_seconds": 0.3,
        "operation_settlement_timeout_seconds": 0.9,
        "close_timeout_seconds": 1.0,
        "terminal_readback_timeout_seconds": 0.5,
        "cleanup_timeout_seconds": 5.0,
        "final_release_timeout_seconds": 0.6,
        "final_release_max_seconds": 0.65,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _plan() -> QualificationPlan:
    return QualificationPlan(
        expected_values=ADR_0046_EXPECTATIONS.as_tuple(),
        operation_authorities=(
            OperationAuthority("operation-1", "authority-1"),
            OperationAuthority("operation-2", "authority-2"),
        ),
        thresholds_ms=(40, 80, 120, 160, 200, 250, 500, 1_000, 2_000),
        thresholds_frozen_before_observation=True,
        valid_observations_removed=0,
        uses_product_expected_mapping=False,
        accepts_any_positive_request_timeout=False,
    )


def test_successor_protocol_freezes_the_adr_owned_tuple() -> None:
    assert ADR_0046_EXPECTATIONS.as_tuple() == (
        400,
        450,
        250,
        300,
        50,
        300,
        900,
        1_000,
        500,
        5_000,
        600,
        650,
    )
    assert POLICY_DIGEST != SOURCE_MANIFEST_DIGEST
    assert {item.relative_path for item in FROZEN_SUCCESSOR_SOURCE_DIGESTS} == {
        "tools/scale15_actual_path_readback.py",
        "tools/scale15_readback_records.py",
        "tools/scale15_readback_contracts.py",
        "tools/scale28_backend_observer_session.py",
        "tools/scale28_backend_observer_session_values.py",
        "tools/scale28_backend_observer_session_startup.py",
        "tools/scale28_backend_observer_session_cleanup.py",
        "tools/scale28_observer_deadlines.py",
        "tools/scale14_backend_monitor.py",
        "tools/scale14_backend_monitor_events.py",
        "tools/scale14_backend_monitor_reporting.py",
    }
    assert verify_source_freeze(_ROOT) == FROZEN_SUCCESSOR_SOURCE_DIGESTS


@pytest.mark.parametrize("name", [
    "scale15_readback_records.py", "scale15_readback_contracts.py",
    "scale28_backend_observer_session_values.py",
    "scale28_backend_observer_session_startup.py",
    "scale28_backend_observer_session_cleanup.py",
    "scale14_backend_monitor_events.py",
    "scale14_backend_monitor_reporting.py",
])
def test_extracted_readback_source_drift_is_refused(
    monkeypatch: pytest.MonkeyPatch, name: str,
) -> None:
    original = Path.read_bytes
    target = _ROOT / "tools" / name

    def changed(path: Path) -> bytes:
        content = original(path)
        return content + b"\n# changed\n" if path == target else content

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_freeze(_ROOT)


def test_product_observation_is_compared_to_test_owned_values() -> None:
    assert (
        verify_product_observation(cast(Any, DEFAULT_OBSERVER_DEADLINE_POLICY))
        == ADR_0046_EXPECTATIONS
    )
    assert verify_product_observation(_product()) == ADR_0046_EXPECTATIONS

    with pytest.raises(ValueError, match="product observer policy changed"):
        verify_product_observation(
            _product(cancel_request_timeout_seconds=0.2)
        )
    with pytest.raises(ValueError, match="product observer policy changed"):
        verify_product_observation(
            _product(cancel_request_timeout_seconds=0.2504)
        )
    with pytest.raises(ValueError, match="product observer policy changed"):
        verify_product_observation(
            _product(terminal_readback_timeout_seconds=0.5004)
        )


def test_successor_support_does_not_import_product_expected_values() -> None:
    guard_support_independence((_MEASUREMENT, _PROCESS))


@pytest.mark.parametrize(
    "candidate",
    (
        replace(_plan(), accepts_any_positive_request_timeout=True),
        replace(_plan(), uses_product_expected_mapping=True),
        replace(_plan(), valid_observations_removed=1),
        replace(_plan(), thresholds_frozen_before_observation=False),
        replace(
            _plan(),
            operation_authorities=(
                OperationAuthority("operation-1", "authority-1"),
                OperationAuthority("operation-1", "authority-2"),
            ),
        ),
        replace(
            _plan(),
            thresholds_ms=(40, 80, 120, 160, 200, 300, 500, 1_000, 2_000),
        ),
    ),
)
def test_qualification_inflation_guard_rejects_candidate(
    candidate: QualificationPlan,
) -> None:
    with pytest.raises(ValueError, match="qualification"):
        verify_qualification_plan(candidate)


def test_qualification_inflation_guard_accepts_frozen_plan() -> None:
    assert verify_qualification_plan(_plan()) == _plan()
    assert verify_enacted_operations(
        _plan(),
        ("operation-1", "operation-2"),
    ) == ("operation-1", "operation-2")


@pytest.mark.parametrize(
    "enacted",
    (
        ("operation-1", "operation-1"),
        ("operation-2", "operation-1"),
        ("operation-1", "operation-3"),
        ("operation-1",),
    ),
)
def test_qualification_guard_rejects_enacted_operation_inflation(
    enacted: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="qualification enacted"):
        verify_enacted_operations(_plan(), enacted)
