from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, cast

import pytest

from scale28_observer_deadlines import DEFAULT_OBSERVER_DEADLINE_POLICY
import repomap_test_support.test_cov5k_r2_observer_protocol as observer_protocol
from repomap_test_support.test_cov5k_r2_observer_protocol import (
    ADR_0046_EXPECTATIONS,
    FROZEN_SUCCESSOR_SOURCE_DIGESTS,
    POLICY_DIGEST,
    PRE_NAMESPACE_SOURCE_COMMIT,
    PRE_NAMESPACE_SOURCE_MANIFEST_DIGEST,
    PRE_NAMESPACE_SUCCESSOR_SOURCE_DIGESTS,
    SOURCE_MANIFEST_DIGEST,
    OperationAuthority,
    QualificationPlan,
    SourceDigest,
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
_CHANGED_OBSERVER_PATHS = (
    "tools/scale15_actual_path_readback.py",
    "tools/scale15_readback_records.py",
    "tools/scale15_readback_contracts.py",
    "tools/scale28_backend_observer_session.py",
    "tools/scale14_backend_monitor.py",
    "tools/scale14_backend_monitor_events.py",
)
_UNCHANGED_OBSERVER_PATHS = (
    "tools/scale28_backend_observer_session_values.py",
    "tools/scale28_backend_observer_session_startup.py",
    "tools/scale28_backend_observer_session_cleanup.py",
    "tools/scale28_observer_deadlines.py",
    "tools/scale14_backend_monitor_reporting.py",
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
        400, 450, 250, 300, 50, 300, 900, 1_000, 500, 5_000, 600, 650,
    )
    assert POLICY_DIGEST != SOURCE_MANIFEST_DIGEST
    assert PRE_NAMESPACE_SOURCE_COMMIT == "6d818ad6d43d38d47c64b8c474c2b64b853f631a"
    assert PRE_NAMESPACE_SOURCE_MANIFEST_DIGEST == "a461e7eb6fc5001059eacd397fb39b5952466b9012d40606a7432fa5e62397e7"
    assert SOURCE_MANIFEST_DIGEST == "b77f0fb41577375b2b9179f91ac1fe27676f03aea61b1c2ce48801c97dd60bb2"
    assert PRE_NAMESPACE_SOURCE_MANIFEST_DIGEST != SOURCE_MANIFEST_DIGEST
    assert [item.relative_path for item in PRE_NAMESPACE_SUCCESSOR_SOURCE_DIGESTS] == [
        item.relative_path for item in FROZEN_SUCCESSOR_SOURCE_DIGESTS
    ]
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


def test_pre_namespace_to_post_namespace_whole_identifier_projection_is_exact() -> None:
    changed: list[str] = []
    unchanged: list[str] = []
    for pre, current in zip(PRE_NAMESPACE_SUCCESSOR_SOURCE_DIGESTS, FROZEN_SUCCESSOR_SOURCE_DIGESTS, strict=True):
        assert pre.relative_path == current.relative_path
        current_bytes = (_ROOT / current.relative_path).read_bytes()
        assert hashlib.sha256(current_bytes).hexdigest() == current.sha256
        reverse_projected = re.sub(rb"\bcommon_lore_index\b", rb"repomap_kg", current_bytes)
        assert hashlib.sha256(reverse_projected).hexdigest() == pre.sha256
        assert re.sub(rb"\brepomap_kg\b", rb"common_lore_index", reverse_projected) == current_bytes
        (changed if pre.sha256 != current.sha256 else unchanged).append(current.relative_path)
    assert tuple(changed) == _CHANGED_OBSERVER_PATHS
    assert tuple(unchanged) == _UNCHANGED_OBSERVER_PATHS


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
    assert verify_source_freeze(_ROOT) == FROZEN_SUCCESSOR_SOURCE_DIGESTS
    original, target = Path.read_bytes, _ROOT / "tools" / name
    monkeypatch.setattr(Path, "read_bytes", lambda path: original(path) + b"\n# changed\n" if path == target else original(path))
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_freeze(_ROOT)


@pytest.mark.parametrize("relative_path", [item.relative_path for item in FROZEN_SUCCESSOR_SOURCE_DIGESTS])
def test_all_eleven_observer_source_files_refuse_byte_drift(
    monkeypatch: pytest.MonkeyPatch, relative_path: str,
) -> None:
    assert verify_source_freeze(_ROOT) == FROZEN_SUCCESSOR_SOURCE_DIGESTS
    original, target = Path.read_bytes, _ROOT / relative_path
    monkeypatch.setattr(Path, "read_bytes", lambda path: original(path) + b"\n# drift\n" if path == target else original(path))
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_freeze(_ROOT)


@pytest.mark.parametrize("relative_path", _CHANGED_OBSERVER_PATHS)
def test_pre_namespace_source_bytes_are_refused(
    monkeypatch: pytest.MonkeyPatch, relative_path: str,
) -> None:
    assert verify_source_freeze(_ROOT) == FROZEN_SUCCESSOR_SOURCE_DIGESTS
    original, target = Path.read_bytes, _ROOT / relative_path
    pre_by_path = {item.relative_path: item.sha256 for item in PRE_NAMESPACE_SUCCESSOR_SOURCE_DIGESTS}

    def reverted(path: Path) -> bytes:
        content = original(path)
        if path != target:
            return content
        pre_bytes = re.sub(rb"\bcommon_lore_index\b", rb"repomap_kg", content)
        assert hashlib.sha256(pre_bytes).hexdigest() == pre_by_path[relative_path]
        return pre_bytes

    monkeypatch.setattr(Path, "read_bytes", reverted)
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_freeze(_ROOT)


@pytest.mark.parametrize("index", range(len(FROZEN_SUCCESSOR_SOURCE_DIGESTS)))
def test_wrong_expected_source_digest_is_refused(
    monkeypatch: pytest.MonkeyPatch, index: int,
) -> None:
    assert verify_source_freeze(_ROOT) == FROZEN_SUCCESSOR_SOURCE_DIGESTS
    entry = FROZEN_SUCCESSOR_SOURCE_DIGESTS[index]
    flipped_tail = "0" if entry.sha256[-1] != "0" else "1"
    mutated = list(FROZEN_SUCCESSOR_SOURCE_DIGESTS)
    mutated[index] = SourceDigest(entry.relative_path, entry.sha256[:-1] + flipped_tail)
    monkeypatch.setattr(observer_protocol, "FROZEN_SUCCESSOR_SOURCE_DIGESTS", tuple(mutated))
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_freeze(_ROOT)


@pytest.mark.parametrize("relative_path", _CHANGED_OBSERVER_PATHS)
def test_pre_namespace_expected_digest_on_changed_file_is_refused(
    monkeypatch: pytest.MonkeyPatch, relative_path: str,
) -> None:
    assert verify_source_freeze(_ROOT) == FROZEN_SUCCESSOR_SOURCE_DIGESTS
    pre_by_path = {item.relative_path: item for item in PRE_NAMESPACE_SUCCESSOR_SOURCE_DIGESTS}
    mutated = tuple(
        pre_by_path[item.relative_path] if item.relative_path == relative_path else item
        for item in FROZEN_SUCCESSOR_SOURCE_DIGESTS
    )
    monkeypatch.setattr(observer_protocol, "FROZEN_SUCCESSOR_SOURCE_DIGESTS", mutated)
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_freeze(_ROOT)


def test_wrong_expected_path_or_order_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    assert verify_source_freeze(_ROOT) == FROZEN_SUCCESSOR_SOURCE_DIGESTS
    swapped_paths = (
        SourceDigest(FROZEN_SUCCESSOR_SOURCE_DIGESTS[1].relative_path, FROZEN_SUCCESSOR_SOURCE_DIGESTS[0].sha256),
        SourceDigest(FROZEN_SUCCESSOR_SOURCE_DIGESTS[0].relative_path, FROZEN_SUCCESSOR_SOURCE_DIGESTS[1].sha256),
        *FROZEN_SUCCESSOR_SOURCE_DIGESTS[2:],
    )
    monkeypatch.setattr(observer_protocol, "FROZEN_SUCCESSOR_SOURCE_DIGESTS", swapped_paths)
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_freeze(_ROOT)

    wrong_existing_path = (
        SourceDigest("tools/scale28_observer_deadlines.py", FROZEN_SUCCESSOR_SOURCE_DIGESTS[0].sha256),
        *FROZEN_SUCCESSOR_SOURCE_DIGESTS[1:],
    )
    monkeypatch.setattr(observer_protocol, "FROZEN_SUCCESSOR_SOURCE_DIGESTS", wrong_existing_path)
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_freeze(_ROOT)

    missing_path = (
        SourceDigest("tools/nonexistent_observer_module.py", FROZEN_SUCCESSOR_SOURCE_DIGESTS[0].sha256),
        *FROZEN_SUCCESSOR_SOURCE_DIGESTS[1:],
    )
    monkeypatch.setattr(observer_protocol, "FROZEN_SUCCESSOR_SOURCE_DIGESTS", missing_path)
    with pytest.raises(FileNotFoundError):
        verify_source_freeze(_ROOT)


@pytest.mark.parametrize(
    ("relative_path", "old_bytes", "new_bytes"),
    (
        ("tools/scale15_actual_path_readback.py", b"common_lore_index", b"common_lore_indey"),
        ("tools/scale28_observer_deadlines.py", b"400", b"401"),
        ("tools/scale15_actual_path_readback.py", b"common_lore_index", b"repomap_kg"),
    ),
)
def test_semantic_source_mutations_are_refused(
    monkeypatch: pytest.MonkeyPatch, relative_path: str, old_bytes: bytes, new_bytes: bytes,
) -> None:
    assert verify_source_freeze(_ROOT) == FROZEN_SUCCESSOR_SOURCE_DIGESTS
    original, target = Path.read_bytes, _ROOT / relative_path

    def mutated(path: Path) -> bytes:
        content = original(path)
        if path != target:
            return content
        replaced = content.replace(old_bytes, new_bytes, 1)
        assert replaced != content
        return replaced

    monkeypatch.setattr(Path, "read_bytes", mutated)
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
