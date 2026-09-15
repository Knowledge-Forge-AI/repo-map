"""Shared process and freshness scenarios for SCALE28-ADR2 support."""

from __future__ import annotations

from dataclasses import dataclass, field
from multiprocessing.connection import Connection
import time
from typing import NoReturn, Protocol

from .scale28_adr2_accepted_evidence import AcceptedPreparationEvidence
from .scale28_adr2_frame_model import (
    MAX_SIGNED_INT,
    ObservationExpectations,
    PreparationObservation,
    PreparationObservationAcknowledgement,
    bounded_protocol_int,
    canonical_protocol_bytes,
)
from .scale28_adr2_receipt_model import ReceiptExpectations


def process_send_messages(
    connection: Connection,
    payloads: tuple[bytes, ...],
) -> None:
    """Send test messages from an importable spawned-process target."""

    try:
        for payload in payloads:
            connection.send_bytes(payload)
    except (BrokenPipeError, OSError):
        pass
    finally:
        connection.close()


def process_send_delayed_second_message(
    connection: Connection,
    first: bytes,
    second: bytes,
    delay_seconds: float,
) -> None:
    """Send a delayed duplicate from an importable spawned-process target."""

    try:
        connection.send_bytes(first)
        time.sleep(delay_seconds)
        connection.send_bytes(second)
    except (BrokenPipeError, OSError):
        pass
    finally:
        connection.close()


def process_close_without_send(connection: Connection) -> None:
    """Close a test sender before emitting a message."""

    connection.close()


def process_send_raw_frame(
    connection: Connection,
    declared_length: int,
    body: bytes,
    header_bytes: int,
) -> None:
    """Send a partial or declared-oversized raw test frame."""

    from .scale28_adr2_bounded_ipc import write_raw_connection_frame

    try:
        write_raw_connection_frame(
            connection,
            declared_length=declared_length,
            body=body,
            header_bytes=header_bytes,
        )
    finally:
        connection.close()


def process_wait_for_ack_timeout(
    connection: Connection,
    timeout_seconds: float,
) -> None:
    """Return a distinct process code after an actual ACK deadline expires."""

    from . import scale28_adr2_bounded_ipc as bounded_ipc

    try:
        bounded_ipc.receive_bounded_message(
            connection,
            bounded_ipc.ACKNOWLEDGEMENT_MESSAGE,
            timeout_seconds=timeout_seconds,
        )
    except bounded_ipc.BoundedIpcFailure as error:
        connection.close()
        raise SystemExit(45 if error.category == "message_timeout" else 46) from error
    raise SystemExit(47)


def process_wait_for_ack_after_parent_close(connection: Connection) -> None:
    """Return a distinct process code for the observed parent-close result."""

    from . import scale28_adr2_bounded_ipc as bounded_ipc

    try:
        bounded_ipc.receive_bounded_message(
            connection,
            bounded_ipc.ACKNOWLEDGEMENT_MESSAGE,
            timeout_seconds=1.0,
        )
    except bounded_ipc.BoundedIpcFailure as error:
        connection.close()
        raise SystemExit(
            42 if error.category == "sender_exit_before_message" else 43
        ) from error
    raise SystemExit(44)


@dataclass(frozen=True)
class FreshnessLeaseDerivation:
    """Frozen integer-millisecond lease derivation."""

    frame_to_receipt_max_ms: int
    component_margin_ms: int
    observation_to_receipt_budget_ms: int
    freshness_component_bound_ms: int
    frame_to_release_max_ms: int
    measured_observation_to_release_bound_ms: int
    selected_freshness_lease_ms: int


def derive_freshness_lease(
    *,
    frame_to_receipt_max_ms: int,
    frame_to_release_max_ms: int,
    final_release_ceiling_ms: int = 650,
) -> FreshnessLeaseDerivation:
    """Derive the pre-registered parent-owned freshness lease."""

    frame_to_receipt = bounded_protocol_int(frame_to_receipt_max_ms)
    frame_to_release = bounded_protocol_int(frame_to_release_max_ms)
    final_release = bounded_protocol_int(final_release_ceiling_ms)
    if final_release != 650:
        raise ValueError("final release ceiling is invalid")
    component_margin = _round_up(
        max(25, _ceil_div(frame_to_receipt, 10)),
        10,
    )
    observation_to_receipt = _round_up(
        max(frame_to_receipt + component_margin, 410),
        10,
    )
    component_bound = 100 + observation_to_receipt + final_release + 250
    measured_bound = frame_to_release + 100
    selected = _round_up(max(component_bound, measured_bound), 50)
    return FreshnessLeaseDerivation(
        frame_to_receipt_max_ms=frame_to_receipt,
        component_margin_ms=component_margin,
        observation_to_receipt_budget_ms=observation_to_receipt,
        freshness_component_bound_ms=component_bound,
        frame_to_release_max_ms=frame_to_release,
        measured_observation_to_release_bound_ms=measured_bound,
        selected_freshness_lease_ms=selected,
    )


@dataclass(frozen=True, slots=True)
class ParentFreshnessAuthority:
    """Conservative parent-monotonic freshness origin and lease."""

    observation_frame_received_parent_ns: int
    freshness_lease_ms: int
    observation_transfer_reserve_ms: int = 100
    _canonical_bytes: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        received = bounded_protocol_int(self.observation_frame_received_parent_ns)
        lease = bounded_protocol_int(self.freshness_lease_ms)
        reserve = bounded_protocol_int(self.observation_transfer_reserve_ms)
        if lease < 1 or reserve != 100:
            raise ValueError("parent freshness authority is invalid")
        object.__setattr__(
            self,
            "_canonical_bytes",
            canonical_protocol_bytes(
                {
                    "freshness_lease_ms": lease,
                    "observation_frame_received_parent_ns": received,
                    "observation_transfer_reserve_ms": reserve,
                }
            ),
        )

    def assert_canonical(self) -> None:
        current = canonical_protocol_bytes(
            {
                "freshness_lease_ms": self.freshness_lease_ms,
                "observation_frame_received_parent_ns": (
                    self.observation_frame_received_parent_ns
                ),
                "observation_transfer_reserve_ms": (
                    self.observation_transfer_reserve_ms
                ),
            }
        )
        if current != self._canonical_bytes:
            raise ValueError("parent freshness authority changed")

    def to_bytes(self) -> bytes:
        self.assert_canonical()
        return self._canonical_bytes

    def conservative_origin_ns(self) -> int:
        """Return the parent-owned conservative observation origin."""

        self.assert_canonical()
        received = bounded_protocol_int(self.observation_frame_received_parent_ns)
        reserve_ms = bounded_protocol_int(self.observation_transfer_reserve_ms)
        if reserve_ms != 100:
            raise ValueError("observation transfer reserve is invalid")
        reserve_ns = reserve_ms * 1_000_000
        if received < reserve_ns:
            raise ValueError("parent observation origin underflows")
        return received - reserve_ns

    def validate_age_ns(self, parent_now_ns: int) -> int:
        """Return a fresh age or reject the equality-exclusive boundary."""

        now = bounded_protocol_int(parent_now_ns)
        origin = self.conservative_origin_ns()
        if now < origin:
            raise ValueError("parent freshness clock is invalid")
        age = now - origin
        if age > MAX_SIGNED_INT:
            raise ValueError("parent freshness age overflows")
        lease_ms = bounded_protocol_int(self.freshness_lease_ms)
        if lease_ms < 1 or age >= lease_ms * 1_000_000:
            raise ValueError("preparation evidence is stale")
        return age


class _PreparationProtocolAuthorityView(Protocol):
    expectations: ObservationExpectations
    freshness_lease_ms: int

    def assert_canonical(self) -> None: ...

    def to_bytes(self) -> bytes: ...


class PreparationStateRetentionMixin:
    """Retained-value views and fail-closed authority checks for protocol state."""

    __slots__ = ()
    _authority: _PreparationProtocolAuthorityView
    _authority_bytes: bytes
    _accepted_frame: PreparationObservation | None
    _accepted_frame_bytes: bytes | None
    _accepted_acknowledgement: PreparationObservationAcknowledgement | None
    _accepted_acknowledgement_bytes: bytes | None
    _accepted_evidence: AcceptedPreparationEvidence | None
    _accepted_evidence_bytes: bytes | None
    _parent_freshness_authority: ParentFreshnessAuthority | None
    _parent_freshness_authority_bytes: bytes | None
    _completed_checkpoints: tuple[str, ...]
    _checkpoint_parent_times_ns: tuple[int, ...]
    _refused: bool
    _sealed: bool

    def validate_retained_authority(self) -> None:
        """Reconstruct retained canonical evidence and reject any substitution."""

        if self._refused:
            raise ValueError("preparation attempt is refused")
        try:
            self._assert_retained_authority()
        except ValueError:
            self._discard()
            raise

    def refuse_external_transport_failure(self) -> None:
        """Discard this generation after a fail-closed transport boundary."""

        self._require_open()
        self._discard()

    def _assert_retained_authority(self) -> None:
        """Validate anchors without recursively invoking refusal handling."""

        self._authority.assert_canonical()
        if self._authority.to_bytes() != self._authority_bytes:
            raise ValueError("preparation protocol authority was substituted")
        if self._parent_freshness_authority is None:
            if self._parent_freshness_authority_bytes is not None:
                raise ValueError("parent freshness authority anchor is invalid")
        else:
            self._parent_freshness_authority.assert_canonical()
            if (
                self._parent_freshness_authority_bytes is None
                or self._parent_freshness_authority.to_bytes()
                != self._parent_freshness_authority_bytes
            ):
                raise ValueError("parent freshness authority was substituted")
            if (
                self._parent_freshness_authority.freshness_lease_ms
                != self._authority.freshness_lease_ms
            ):
                raise ValueError("parent freshness lease authority changed")
        if self._accepted_frame is None:
            if self._accepted_frame_bytes is not None:
                raise ValueError("accepted observation frame anchor is invalid")
        else:
            self._accepted_frame.assert_canonical(self._authority.expectations)
            if (
                self._accepted_frame_bytes is None
                or self._accepted_frame.to_bytes() != self._accepted_frame_bytes
            ):
                raise ValueError("accepted observation frame was substituted")
        if self._accepted_acknowledgement is None:
            if self._accepted_acknowledgement_bytes is not None:
                raise ValueError(
                    "accepted observation acknowledgement anchor is invalid"
                )
        else:
            if self._accepted_frame is None:
                raise ValueError("observation frame is missing")
            self._accepted_acknowledgement.assert_canonical(
                self._authority.expectations,
                self._accepted_frame,
            )
            if (
                self._accepted_acknowledgement_bytes is None
                or self._accepted_acknowledgement.to_bytes()
                != self._accepted_acknowledgement_bytes
            ):
                raise ValueError(
                    "accepted observation acknowledgement was substituted"
                )
        if self._accepted_evidence is None:
            if self._accepted_evidence_bytes is not None:
                raise ValueError("accepted preparation evidence anchor is invalid")
        else:
            if (
                self._accepted_frame is None
                or self._accepted_acknowledgement is None
            ):
                raise ValueError("accepted preparation evidence is unbound")
            self._accepted_evidence.assert_canonical()
            if (
                self._accepted_evidence_bytes is None
                or self._accepted_evidence.to_bytes()
                != self._accepted_evidence_bytes
            ):
                raise ValueError("accepted preparation evidence was substituted")
            expectations = ReceiptExpectations(
                observation_expectations=self._authority.expectations,
                accepted_frame=self._accepted_frame,
                accepted_acknowledgement=self._accepted_acknowledgement,
            )
            rebuilt = AcceptedPreparationEvidence.from_values(
                expectations,
                self._accepted_evidence.receipt,
            )
            if rebuilt != self._accepted_evidence:
                raise ValueError("accepted preparation evidence bindings changed")

    def _require_open(self) -> None:
        if self._refused:
            raise ValueError("preparation attempt is refused")
        self.validate_retained_authority()

    def _refuse(self, message: str) -> NoReturn:
        self._discard()
        raise ValueError(message)

    def _discard(self) -> None:
        object.__setattr__(self, "_accepted_frame", None)
        object.__setattr__(self, "_accepted_frame_bytes", None)
        object.__setattr__(self, "_accepted_acknowledgement", None)
        object.__setattr__(self, "_accepted_acknowledgement_bytes", None)
        object.__setattr__(self, "_accepted_evidence", None)
        object.__setattr__(self, "_accepted_evidence_bytes", None)
        object.__setattr__(self, "_parent_freshness_authority", None)
        object.__setattr__(self, "_parent_freshness_authority_bytes", None)
        object.__setattr__(self, "_completed_checkpoints", ())
        object.__setattr__(self, "_checkpoint_parent_times_ns", ())
        object.__setattr__(self, "_refused", True)


def _round_up(value: int, quantum: int) -> int:
    return _ceil_div(value, quantum) * quantum


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor
