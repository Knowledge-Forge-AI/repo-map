"""ADR-owned observer protocol authority for the FIX2 successor evidence."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable, Protocol


@dataclass(frozen=True, slots=True)
class ObserverProtocolExpectations:
    """Test-owned values derived from ADR 0046, never from product policy."""

    server_statement_ms: int = 400
    client_trigger_ms: int = 450
    request_bound_ms: int = 250
    request_max_ms: int = 300
    request_publication_margin_ms: int = 50
    request_deadline_ms: int = 300
    operation_classification_ms: int = 900
    close_attempt_ms: int = 1_000
    terminal_read_ms: int = 500
    cleanup_attempt_ms: int = 5_000
    final_release_ms: int = 600
    final_release_max_ms: int = 650

    def as_tuple(self) -> tuple[int, ...]:
        """Return the closed ADR-owned expectation tuple."""

        return (
            self.server_statement_ms,
            self.client_trigger_ms,
            self.request_bound_ms,
            self.request_max_ms,
            self.request_publication_margin_ms,
            self.request_deadline_ms,
            self.operation_classification_ms,
            self.close_attempt_ms,
            self.terminal_read_ms,
            self.cleanup_attempt_ms,
            self.final_release_ms,
            self.final_release_max_ms,
        )


ADR_0046_EXPECTATIONS = ObserverProtocolExpectations()
FROZEN_THRESHOLDS_MS = (
    40,
    80,
    120,
    160,
    200,
    250,
    500,
    1_000,
    2_000,
)


@dataclass(frozen=True, slots=True)
class SourceDigest:
    """One path-bound successor production-source identity."""

    relative_path: str
    sha256: str


FROZEN_SUCCESSOR_SOURCE_DIGESTS = (
    SourceDigest(
        "tools/scale15_actual_path_readback.py",
        "2a67a8ec2eee4fab3de049a489976351a7b7b328bf935cc1beba62b04a3ff606",
    ),
    SourceDigest(
        "tools/scale15_readback_records.py",
        "52b2aaff5dc51a0090f2d2ad19bf2cc8edebb125c87bf87bf2b2580f4ae39e6c",
    ),
    SourceDigest(
        "tools/scale15_readback_contracts.py",
        "25a278749c397eb59b3b8cdf0c1dccebcf3481538e487d628248619e1290fdd4",
    ),
    SourceDigest(
        "tools/scale28_backend_observer_session.py",
        "fe387621d9fa9b1f5c227a31921418622b6bacc11f84a80951205ff6493a667b",
    ),
    SourceDigest(
        "tools/scale28_backend_observer_session_values.py",
        "8dd549a0458cec893c1e1aa9a45b62605d869ed2dff4ccdea4dffe50bd6293a0",
    ),
    SourceDigest(
        "tools/scale28_backend_observer_session_startup.py",
        "116da58e7c83927c6578fef562a8de83d660b3451ec41e56e4ac79855809bb1c",
    ),
    SourceDigest(
        "tools/scale28_backend_observer_session_cleanup.py",
        "eb6e3d79bec896245a606d39e6e3346281b6271d7e966433c14f656a34b65fc6",
    ),
    SourceDigest(
        "tools/scale28_observer_deadlines.py",
        "c8443c8ce449d1dbcb00a0dbb93e33b8defbcc1cab3d780c0058c35e8c35a858",
    ),
    SourceDigest(
        "tools/scale14_backend_monitor.py",
        "2cb531278eb69ae32568f2cc3983ee5535868d5eb1c194227ec0cf50f551811c",
    ),
    SourceDigest(
        "tools/scale14_backend_monitor_events.py",
        "6fd2c064da8ae35a33e23861dbda757e57f019086eb6cf5977881b42de4c09f9",
    ),
    SourceDigest(
        "tools/scale14_backend_monitor_reporting.py",
        "cbd10fb98e42aee0d13c66728e969d8462326795c8f99668024fdd92b0ca05ed",
    ),
)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


POLICY_DIGEST = _digest(
    {
        "adr": "0046",
        "expectations": ADR_0046_EXPECTATIONS.as_tuple(),
        "thresholds_ms": FROZEN_THRESHOLDS_MS,
    }
)
SOURCE_MANIFEST_DIGEST = _digest(
    [
        (item.relative_path, item.sha256)
        for item in FROZEN_SUCCESSOR_SOURCE_DIGESTS
    ]
)


def verify_source_freeze(repository_root: Path) -> tuple[SourceDigest, ...]:
    """Return the successor identities or reject production drift."""

    observed = tuple(
        SourceDigest(
            expected.relative_path,
            hashlib.sha256(
                (repository_root / expected.relative_path).read_bytes()
            ).hexdigest(),
        )
        for expected in FROZEN_SUCCESSOR_SOURCE_DIGESTS
    )
    if observed != FROZEN_SUCCESSOR_SOURCE_DIGESTS:
        raise ValueError("successor observer production source changed")
    return observed


class ObserverDeadlineProduct(Protocol):
    @property
    def server_statement_timeout_ms(self) -> int | float: ...
    @property
    def client_cancel_after_seconds(self) -> int | float: ...
    @property
    def cancel_request_timeout_seconds(self) -> int | float: ...
    @property
    def cancel_request_max_seconds(self) -> int | float: ...
    @property
    def cancel_request_publication_margin_seconds(self) -> int | float: ...
    @property
    def request_terminal_timeout_seconds(self) -> int | float: ...
    @property
    def operation_settlement_timeout_seconds(self) -> int | float: ...
    @property
    def close_timeout_seconds(self) -> int | float: ...
    @property
    def terminal_readback_timeout_seconds(self) -> int | float: ...
    @property
    def cleanup_timeout_seconds(self) -> int | float: ...
    @property
    def final_release_timeout_seconds(self) -> int | float: ...
    @property
    def final_release_max_seconds(self) -> int | float: ...

def verify_product_observation(product: ObserverDeadlineProduct) -> ObserverProtocolExpectations:
    """Compare observed product fields against the ADR-owned tuple."""

    observed = (
        product.server_statement_timeout_ms,
        product.client_cancel_after_seconds,
        product.cancel_request_timeout_seconds,
        product.cancel_request_max_seconds,
        product.cancel_request_publication_margin_seconds,
        product.request_terminal_timeout_seconds,
        product.operation_settlement_timeout_seconds,
        product.close_timeout_seconds,
        product.terminal_readback_timeout_seconds,
        product.cleanup_timeout_seconds,
        product.final_release_timeout_seconds,
        product.final_release_max_seconds,
    )
    expected = (
        400,
        0.45,
        0.25,
        0.3,
        0.05,
        0.3,
        0.9,
        1.0,
        0.5,
        5.0,
        0.6,
        0.65,
    )
    if observed != expected:
        raise ValueError("product observer policy changed")
    return ADR_0046_EXPECTATIONS


@dataclass(frozen=True, slots=True)
class OperationAuthority:
    """Bind one enacted operation to exactly one authority identity."""

    operation_id: str
    authority_id: str


@dataclass(frozen=True, slots=True)
class QualificationPlan:
    """Closed anti-inflation inputs for successor implementation evidence."""

    expected_values: tuple[int, ...]
    operation_authorities: tuple[OperationAuthority, ...]
    thresholds_ms: tuple[int, ...]
    thresholds_frozen_before_observation: bool
    valid_observations_removed: int
    uses_product_expected_mapping: bool
    accepts_any_positive_request_timeout: bool


def verify_qualification_plan(plan: QualificationPlan) -> QualificationPlan:
    """Reject product-coupled, relabelled, removed, or retuned evidence."""

    operation_ids = tuple(
        item.operation_id for item in plan.operation_authorities
    )
    authority_ids = tuple(
        item.authority_id for item in plan.operation_authorities
    )
    if plan.expected_values != ADR_0046_EXPECTATIONS.as_tuple():
        raise ValueError("qualification expected values changed")
    if (
        plan.uses_product_expected_mapping
        or plan.accepts_any_positive_request_timeout
    ):
        raise ValueError("qualification expected-value authority is invalid")
    if plan.valid_observations_removed != 0:
        raise ValueError("qualification removed a valid observation")
    if (
        plan.thresholds_ms != FROZEN_THRESHOLDS_MS
        or not plan.thresholds_frozen_before_observation
    ):
        raise ValueError("qualification thresholds changed")
    if (
        not operation_ids
        or len(set(operation_ids)) != len(operation_ids)
        or len(set(authority_ids)) != len(authority_ids)
        or any(not value for value in operation_ids + authority_ids)
    ):
        raise ValueError("qualification operation authority is inflated")
    return plan


def verify_enacted_operations(
    plan: QualificationPlan,
    enacted_operation_ids: Iterable[str],
) -> tuple[str, ...]:
    """Bind every enacted result to its one predeclared operation identity."""

    expected = tuple(
        item.operation_id for item in plan.operation_authorities
    )
    enacted = tuple(enacted_operation_ids)
    if (
        enacted != expected
        or len(set(enacted)) != len(enacted)
        or any(not value for value in enacted)
    ):
        raise ValueError("qualification enacted operation manifest changed")
    return enacted


def guard_support_independence(paths: Iterable[Path]) -> None:
    """Reject qualification support importing product expected values."""

    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            imported: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported = (node.module or "",)
            if any(
                name == "scale28_observer_deadlines"
                or name.startswith("scale28_observer_deadlines.")
                for name in imported
            ):
                raise ValueError(
                    "qualification support imports product policy"
                )
        if "DEFAULT_OBSERVER_DEADLINE_POLICY" in source:
            raise ValueError("qualification support uses product expected values")


__all__ = [
    "ADR_0046_EXPECTATIONS",
    "FROZEN_SUCCESSOR_SOURCE_DIGESTS",
    "FROZEN_THRESHOLDS_MS",
    "OperationAuthority",
    "POLICY_DIGEST",
    "QualificationPlan",
    "SOURCE_MANIFEST_DIGEST",
    "SourceDigest",
    "guard_support_independence",
    "verify_enacted_operations",
    "verify_product_observation",
    "verify_qualification_plan",
    "verify_source_freeze",
]
