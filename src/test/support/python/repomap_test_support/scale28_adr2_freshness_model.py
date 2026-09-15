"""Parent-owned freshness and reacquisition model for SCALE28-ADR2-FIX1."""

from __future__ import annotations

from dataclasses import dataclass, field

from .scale28_adr2_accepted_evidence import AcceptedPreparationEvidence
from .scale28_adr2_frame_model import (
    ObservationExpectations,
    PreparationObservation,
    PreparationObservationAcknowledgement,
    bounded_protocol_int,
    canonical_protocol_bytes,
    validate_digest,
    validate_observation_acknowledgement,
    validate_observation_frame,
)
from .scale28_adr2_receipt_model import (
    PreparationTerminalReceipt,
    ReceiptExpectations,
    validate_preparation_receipt,
)
from . import scale28_adr2_scenarios as _adr2_scenarios

FreshnessLeaseDerivation = _adr2_scenarios.FreshnessLeaseDerivation
ParentFreshnessAuthority = _adr2_scenarios.ParentFreshnessAuthority
PreparationStateRetentionMixin = _adr2_scenarios.PreparationStateRetentionMixin
_PreparationProtocolAuthorityView = _adr2_scenarios._PreparationProtocolAuthorityView
derive_freshness_lease = _adr2_scenarios.derive_freshness_lease


FRESHNESS_CHECKPOINTS = (
    "observation_frame_acceptance",
    "terminal_receipt_acceptance",
    "process_tree_settlement",
    "before_stable_sample_one",
    "before_stable_sample_two",
    "immediately_before_release",
)


@dataclass(frozen=True, slots=True)
class PreparationProtocolAuthority:
    """Immutable construction-time attempt and freshness authority."""

    expectations: ObservationExpectations
    freshness_lease_ms: int
    _canonical_bytes: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.expectations, ObservationExpectations):
            raise ValueError("preparation expectations are invalid")
        lease = bounded_protocol_int(self.freshness_lease_ms)
        if lease != 1_450:
            raise ValueError("preparation freshness lease is invalid")
        object.__setattr__(
            self,
            "_canonical_bytes",
            canonical_protocol_bytes(
                {
                    **self.expectations.to_mapping(),
                    "freshness_lease_ms": lease,
                }
            ),
        )

    def assert_canonical(self) -> None:
        current = canonical_protocol_bytes(
            {
                **self.expectations.to_mapping(),
                "freshness_lease_ms": self.freshness_lease_ms,
            }
        )
        if current != self._canonical_bytes:
            raise ValueError("preparation protocol authority changed")

    def to_bytes(self) -> bytes:
        self.assert_canonical()
        return self._canonical_bytes


@dataclass(slots=True, init=False)
class PreparationProtocolState(PreparationStateRetentionMixin):
    """One attempt's closed frame, ACK, receipt, and checkpoint state."""

    _authority: _PreparationProtocolAuthorityView
    _authority_bytes: bytes = field(init=False, repr=False)
    _accepted_frame: PreparationObservation | None
    _accepted_frame_bytes: bytes | None = field(init=False, repr=False)
    _accepted_acknowledgement: PreparationObservationAcknowledgement | None
    _accepted_acknowledgement_bytes: bytes | None = field(
        init=False,
        repr=False,
    )
    _accepted_evidence: AcceptedPreparationEvidence | None
    _accepted_evidence_bytes: bytes | None = field(init=False, repr=False)
    _parent_freshness_authority: ParentFreshnessAuthority | None
    _parent_freshness_authority_bytes: bytes | None = field(
        init=False,
        repr=False,
    )
    _completed_checkpoints: tuple[str, ...]
    _checkpoint_parent_times_ns: tuple[int, ...]
    _refused: bool
    _sealed: bool

    def __init__(
        self,
        expectations: ObservationExpectations,
        freshness_lease_ms: int,
    ) -> None:
        authority = PreparationProtocolAuthority(
            expectations,
            freshness_lease_ms,
        )
        object.__setattr__(self, "_authority", authority)
        object.__setattr__(self, "_authority_bytes", authority.to_bytes())
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
        object.__setattr__(self, "_refused", False)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("preparation protocol state is read-only")
        object.__setattr__(self, name, value)

    @property
    def expectations(self) -> ObservationExpectations:
        return self._authority.expectations

    @property
    def freshness_lease_ms(self) -> int:
        return self._authority.freshness_lease_ms

    @property
    def accepted_frame(self) -> PreparationObservation | None:
        return self._accepted_frame

    @property
    def accepted_acknowledgement(
        self,
    ) -> PreparationObservationAcknowledgement | None:
        return self._accepted_acknowledgement

    @property
    def accepted_receipt(self) -> PreparationTerminalReceipt | None:
        if self._accepted_evidence is None:
            return None
        return self._accepted_evidence.receipt

    @property
    def accepted_evidence(self) -> AcceptedPreparationEvidence | None:
        return self._accepted_evidence

    @property
    def observation_frame_received_parent_ns(self) -> int | None:
        if self._parent_freshness_authority is None:
            return None
        return self._parent_freshness_authority.observation_frame_received_parent_ns

    @property
    def completed_checkpoints(self) -> tuple[str, ...]:
        return self._completed_checkpoints

    @property
    def checkpoint_parent_times_ns(self) -> tuple[int, ...]:
        return self._checkpoint_parent_times_ns

    @property
    def refused(self) -> bool:
        return self._refused

    def accept_observation_frame(
        self,
        encoded: bytes,
        *,
        parent_received_ns: int,
    ) -> PreparationObservation:
        """Accept exactly one frame and record its parent-monotonic boundary."""

        self._require_open()
        if self._accepted_frame is not None:
            self._refuse("observation frame is duplicate")
        try:
            frame = validate_observation_frame(encoded, self.expectations)
            received = bounded_protocol_int(parent_received_ns)
            freshness_authority = ParentFreshnessAuthority(
                observation_frame_received_parent_ns=received,
                freshness_lease_ms=self.freshness_lease_ms,
            )
            freshness_authority.validate_age_ns(received)
        except ValueError:
            self._discard()
            raise
        object.__setattr__(self, "_accepted_frame", frame)
        object.__setattr__(self, "_accepted_frame_bytes", frame.to_bytes())
        object.__setattr__(
            self,
            "_parent_freshness_authority",
            freshness_authority,
        )
        object.__setattr__(
            self,
            "_parent_freshness_authority_bytes",
            freshness_authority.to_bytes(),
        )
        object.__setattr__(
            self,
            "_completed_checkpoints",
            self._completed_checkpoints + ("observation_frame_acceptance",),
        )
        object.__setattr__(
            self,
            "_checkpoint_parent_times_ns",
            self._checkpoint_parent_times_ns + (received,),
        )
        return frame

    def accept_observation_acknowledgement(
        self,
        encoded: bytes,
    ) -> PreparationObservationAcknowledgement:
        """Accept exactly one ACK for the already accepted frame."""

        self._require_open()
        if self._accepted_frame is None:
            self._refuse("observation frame is missing")
        if self._accepted_acknowledgement is not None:
            self._refuse("observation acknowledgement is duplicate")
        try:
            acknowledgement = validate_observation_acknowledgement(
                encoded,
                self.expectations,
                accepted_frame=self._accepted_frame,
            )
        except ValueError:
            self._discard()
            raise
        object.__setattr__(
            self,
            "_accepted_acknowledgement",
            acknowledgement,
        )
        object.__setattr__(
            self,
            "_accepted_acknowledgement_bytes",
            acknowledgement.to_bytes(),
        )
        return acknowledgement

    def accept_terminal_receipt(
        self,
        encoded: bytes,
        *,
        parent_received_ns: int,
    ) -> PreparationTerminalReceipt:
        """Accept exactly one terminal receipt and validate its freshness."""

        self._require_open()
        if self._accepted_frame is None:
            self._refuse("observation frame is missing")
        if self._accepted_acknowledgement is None:
            self._refuse("observation acknowledgement is missing")
        if self._accepted_evidence is not None:
            self._refuse("preparation receipt is duplicate")
        try:
            receipt_expectations = ReceiptExpectations(
                observation_expectations=self.expectations,
                accepted_frame=self._accepted_frame,
                accepted_acknowledgement=self._accepted_acknowledgement,
            )
            receipt = validate_preparation_receipt(encoded, receipt_expectations)
            evidence = AcceptedPreparationEvidence.from_values(
                receipt_expectations,
                receipt,
            )
        except ValueError:
            self._discard()
            raise
        object.__setattr__(self, "_accepted_evidence", evidence)
        object.__setattr__(self, "_accepted_evidence_bytes", evidence.to_bytes())
        try:
            self.validate_checkpoint(
                "terminal_receipt_acceptance",
                parent_now_ns=parent_received_ns,
            )
        except ValueError:
            self._discard()
            raise
        return receipt

    def validate_checkpoint(self, checkpoint: str, *, parent_now_ns: int) -> int:
        """Validate one exact ordered parent freshness checkpoint."""

        self._require_open()
        try:
            self.validate_retained_authority()
            if checkpoint not in FRESHNESS_CHECKPOINTS:
                raise ValueError("freshness checkpoint is invalid")
            expected_index = len(self._completed_checkpoints)
            if expected_index >= len(FRESHNESS_CHECKPOINTS) or (
                checkpoint != FRESHNESS_CHECKPOINTS[expected_index]
            ):
                raise ValueError("freshness checkpoint order is invalid")
            if self._parent_freshness_authority is None:
                raise ValueError("parent observation timestamp is missing")
            if expected_index >= 1 and self._accepted_evidence is None:
                raise ValueError("terminal receipt is missing")
            now = bounded_protocol_int(parent_now_ns)
            if (
                self._checkpoint_parent_times_ns
                and now < self._checkpoint_parent_times_ns[-1]
            ):
                raise ValueError("parent freshness clock is invalid")
            age = self._parent_freshness_authority.validate_age_ns(now)
        except ValueError:
            self._discard()
            raise
        object.__setattr__(
            self,
            "_completed_checkpoints",
            self._completed_checkpoints + (checkpoint,),
        )
        object.__setattr__(
            self,
            "_checkpoint_parent_times_ns",
            self._checkpoint_parent_times_ns + (now,),
        )
        return age

@dataclass(frozen=True)
class AttemptGeneration:
    """All evidence identities that must change for reacquisition."""

    run_nonce: str
    attempt: int
    worker_identity_digest: str
    frame_sequence_generation_digest: str
    resource_baseline_digest: str
    observation_frame_digest: str
    observation_ack_digest: str
    receipt_digest: str
    parent_observation_timestamp_ns: int
    state_machine_generation_digest: str


def validate_reacquisition(
    first: AttemptGeneration,
    second: AttemptGeneration,
) -> None:
    """Reject any attempt-two reuse of attempt-one readiness evidence."""

    if first.attempt != 1 or second.attempt != 2:
        raise ValueError("reacquisition attempts are invalid")
    digest_fields = (
        "worker_identity_digest",
        "frame_sequence_generation_digest",
        "resource_baseline_digest",
        "observation_frame_digest",
        "observation_ack_digest",
        "receipt_digest",
        "state_machine_generation_digest",
    )
    for generation in (first, second):
        if (
            len(generation.run_nonce) != 32
            or any(character not in "0123456789abcdef" for character in generation.run_nonce)
        ):
            raise ValueError("reacquisition run nonce is invalid")
        for name in digest_fields:
            validate_digest(getattr(generation, name), "reacquisition evidence")
        bounded_protocol_int(generation.parent_observation_timestamp_ns)
    fields = (
        "run_nonce",
        "worker_identity_digest",
        "frame_sequence_generation_digest",
        "resource_baseline_digest",
        "observation_frame_digest",
        "observation_ack_digest",
        "receipt_digest",
        "parent_observation_timestamp_ns",
        "state_machine_generation_digest",
    )
    if any(getattr(first, name) == getattr(second, name) for name in fields):
        raise ValueError("reacquisition reused preparation evidence")
