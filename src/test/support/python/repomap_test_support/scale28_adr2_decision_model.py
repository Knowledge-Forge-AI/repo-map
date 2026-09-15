"""Public-safe reproducible decision model for SCALE28-ADR2-FIX2."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .scale28_adr2_frame_model import (
    ObservationExpectations,
    encode_observation_acknowledgement,
    encode_observation_frame,
    validate_observation_acknowledgement,
    validate_observation_frame,
)
from .scale28_adr2_freshness_model import derive_freshness_lease
from .scale28_adr2_campaign_results import PROTOCOL_REVISION
from .scale28_adr2_receipt_model import (
    ReceiptExpectations,
    encode_receipt,
    validate_preparation_receipt,
)
from .scale28_adr2_successor_contracts import (
    Scale28Fix4Contract,
    TestCov5CContract,
)

__all__ = [
    "FreshnessDesign",
    "ObservationExpectations",
    "PrototypeEvidence",
    "ReceiptExpectations",
    "StartupArchitecture",
    "StartupAuthorityDecision",
    "StartupAuthorityInputs",
    "encode_observation_acknowledgement",
    "encode_observation_frame",
    "encode_receipt",
    "select_startup_authority",
    "validate_observation_acknowledgement",
    "validate_observation_frame",
    "validate_preparation_receipt",
]

_OWNING_AREA_COUNTS = (
    ("SCALE14", 10),
    ("SCALE23", 10),
    ("SCALE28", 10),
    ("SCALE28-FIX1", 10),
)
_ORIGINAL_FAULT_MATRIX = (
    "preparation_timeout",
    "worker_crash",
    "worker_signal_exit",
    "partial_result",
    "malformed_result",
    "duplicate_result",
    "stale_result",
    "scope_mismatch",
    "runtime_restart",
    "resource_reader_failure",
    "persistent_ambient_client",
    "transient_ambient_client",
    "unknown_client",
    "observer_failure",
    "event_readiness_failure",
    "child_release_refusal",
    "parent_cancellation",
    "cleanup_timeout",
)
_FRESHNESS_FAULT_MATRIX = (
    "missing_observation_frame",
    "duplicate_identical_frame",
    "changed_duplicate_frame",
    "frame_receipt_baseline_mismatch",
    "missing_ack",
    "wrong_ack",
    "ack_timeout",
    "delayed_result_creation",
    "stale_before_sample_one",
    "stale_before_sample_two",
    "stale_immediately_before_release",
    "cross_attempt_frame_or_receipt_reuse",
)
_MUTATION_MATRIX = (
    "caller_expectation_bindings",
    "caller_baseline_mapping",
    "accepted_frame_top_level",
    "accepted_frame_baseline_binding",
    "returned_frame_projection",
    "accepted_acknowledgement",
    "receipt_nested_baseline",
    "receipt_subordinate_cleanup",
    "receipt_expected_disposition",
    "retained_canonical_authority",
)
_IPC_FAULT_MATRIX = (
    "observation_overflow",
    "acknowledgement_overflow",
    "receipt_overflow",
    "partial_frame",
    "partial_receipt",
    "unexpected_second_message",
    "sender_exit_during_message",
    "acknowledgement_timeout_or_receiver_close",
)


class StartupArchitecture(str, Enum):
    """Closed SCALE28-ADR2 architecture vocabulary."""

    PROCESS_ISOLATED_FULL = "process_isolated_full"
    TWO_STAGE_IN_PROCESS = "two_stage_in_process"
    HYBRID = "hybrid_isolated_resource_preparation"


class FreshnessDesign(str, Enum):
    """Closed SCALE28-ADR2-FIX1 freshness-design vocabulary."""

    PARENT_ACKNOWLEDGED_FRAME = "parent_observed_acknowledged_observation_frame"
    ONE_RECEIPT_LAG = "conservative_one_receipt_lag"


@dataclass(frozen=True, slots=True)
class PrototypeEvidence:
    """Bounded aggregate evidence from the source-frozen revision-4 campaign."""

    protocol_revision: str
    receipt_schema_version: int
    immutable_canonical_authority: bool
    bounded_ipc_before_decode: bool
    observed_result_contract: bool
    source_hashes_match: bool
    selected_freshness_design: FreshnessDesign
    rejected_freshness_design_category: str
    cold_executions: int
    loaded_executions: int
    transient_executions: int
    owning_area_counts: tuple[tuple[str, int], ...]
    ordering_count: int
    original_fault_count: int
    original_fault_scenario_count: int
    freshness_fault_count: int
    freshness_fault_scenario_count: int
    mutation_attack_count: int
    mutation_family_count: int
    bounded_ipc_fault_count: int
    bounded_ipc_family_count: int
    postgres_visible_count: int
    postgres_settled_count: int
    static_probe_count: int
    preparation_max_ms: int
    frame_to_receipt_max_ms: int
    frame_to_release_max_ms: int
    final_release_max_ms: int
    total_observed_records: int
    valid_observations_removed: int
    cleanup_passed: bool

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if (
            self.protocol_revision != PROTOCOL_REVISION
            or self.receipt_schema_version != 3
            or self.immutable_canonical_authority is not True
            or self.bounded_ipc_before_decode is not True
            or self.observed_result_contract is not True
            or self.source_hashes_match is not True
        ):
            raise ValueError("revision-4 authority evidence is invalid")
        if self.selected_freshness_design is not FreshnessDesign.PARENT_ACKNOWLEDGED_FRAME:
            raise ValueError("freshness design selection is invalid")
        if (
            self.rejected_freshness_design_category
            != "unacknowledged_terminal_write_unbounded"
        ):
            raise ValueError("freshness design rejection is invalid")
        expected_counts = (
            self.cold_executions == 20
            and self.loaded_executions == 30
            and self.transient_executions == 20
            and self.owning_area_counts == _OWNING_AREA_COUNTS
            and self.ordering_count == 100
            and self.original_fault_count == 180
            and self.original_fault_scenario_count == len(_ORIGINAL_FAULT_MATRIX)
            and self.freshness_fault_count == 120
            and self.freshness_fault_scenario_count == len(_FRESHNESS_FAULT_MATRIX)
            and self.mutation_attack_count == 100
            and self.mutation_family_count == len(_MUTATION_MATRIX)
            and self.bounded_ipc_fault_count == 80
            and self.bounded_ipc_family_count == len(_IPC_FAULT_MATRIX)
            and self.postgres_visible_count == 10
            and self.postgres_settled_count == 10
            and self.static_probe_count == 2
            and self.total_observed_records == 702
        )
        if not expected_counts:
            raise ValueError("revision-4 prototype campaign is incomplete")
        numeric = (
            self.preparation_max_ms,
            self.frame_to_receipt_max_ms,
            self.frame_to_release_max_ms,
            self.final_release_max_ms,
        )
        if any(not _is_int(value) or value < 0 for value in numeric):
            raise ValueError("prototype aggregate is invalid")
        if self.preparation_max_ms > 5_000:
            raise ValueError("preparation attempt ceiling exceeded")
        if self.final_release_max_ms > 650:
            raise ValueError("final release ceiling exceeded")
        if self.valid_observations_removed != 0:
            raise ValueError("valid observation removal is forbidden")
        if self.cleanup_passed is not True:
            raise ValueError("prototype cleanup is required")


@dataclass(frozen=True, slots=True)
class StartupAuthorityInputs:
    """Frozen decision inputs and non-negotiable authority facts."""

    adr1_rejected_handoff_ms: int
    operator_guard_ms: int
    preparation_attempt_ceiling_ms: int
    preparation_total_ceiling_ms: int
    final_release_ceiling_ms: int
    freshness_lease_ms: int
    transfer_reserve_ms: int
    maximum_attempts: int
    stable_sample_count: int
    resource_result_settled: bool
    cleanup_complete: bool
    dynamic_tuning: bool
    public_configuration: bool
    blind_reconnect: bool
    observation_gap: bool
    scale29_requested: bool
    evidence: PrototypeEvidence

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.adr1_rejected_handoff_ms != 5_850:
            raise ValueError("ADR1 rejection is required")
        if self.operator_guard_ms != 3_000:
            raise ValueError("operator guard is invalid")
        if self.final_release_ceiling_ms != 650:
            raise ValueError("final release ceiling is invalid")
        if self.final_release_ceiling_ms > self.operator_guard_ms:
            raise ValueError("final release guard exceeded")
        if self.stable_sample_count < 2:
            raise ValueError("two stable ownership samples are required")
        if self.resource_result_settled is not True:
            raise ValueError("settled resource result is required")
        if self.cleanup_complete is not True:
            raise ValueError("cleanup is required")
        if self.dynamic_tuning is not False:
            raise ValueError("dynamic tuning is forbidden")
        if self.public_configuration is not False:
            raise ValueError("public configuration is forbidden")
        if self.blind_reconnect is not False:
            raise ValueError("blind reconnect is forbidden")
        if self.observation_gap is not False:
            raise ValueError("observation gap is forbidden")
        if self.scale29_requested is not False:
            raise ValueError("SCALE29 remains prohibited")
        if self.maximum_attempts != 2:
            raise ValueError("maximum attempts must be two")
        if self.preparation_attempt_ceiling_ms != 5_000:
            raise ValueError("preparation attempt ceiling is invalid")
        if self.preparation_total_ceiling_ms != 10_000:
            raise ValueError("total preparation ceiling is invalid")
        if self.transfer_reserve_ms != 100:
            raise ValueError("observation transfer reserve is invalid")
        self.evidence.validate()
        derivation = derive_freshness_lease(
            frame_to_receipt_max_ms=self.evidence.frame_to_receipt_max_ms,
            frame_to_release_max_ms=self.evidence.frame_to_release_max_ms,
            final_release_ceiling_ms=self.final_release_ceiling_ms,
        )
        if derivation.selected_freshness_lease_ms != 1_450:
            raise ValueError("revision-4 freshness lease derivation changed")
        if self.freshness_lease_ms != 1_450:
            raise ValueError("freshness lease is invalid")


@dataclass(frozen=True, slots=True)
class StartupAuthorityDecision:
    """Selected architecture and frozen corrected successor contracts."""

    selected_architecture: StartupArchitecture
    selected_freshness_design: FreshnessDesign
    static_rejections: tuple[tuple[StartupArchitecture, str], ...]
    freshness_design_rejection: tuple[FreshnessDesign, str]
    preparation_attempt_ceiling_ms: int
    preparation_total_ceiling_ms: int
    final_release_ceiling_ms: int
    freshness_lease_ms: int
    operator_guard_ms: int
    receipt_schema_version: int
    state_machine: tuple[str, ...]
    failure_states: tuple[str, str]
    original_failure_matrix: tuple[str, ...]
    freshness_failure_matrix: tuple[str, ...]
    mutation_matrix: tuple[str, ...]
    bounded_ipc_matrix: tuple[str, ...]
    selected_failure_surfaces: tuple[str, ...]
    fix4_contract: Scale28Fix4Contract
    test_cov5c_contract: TestCov5CContract
    production_qualified: bool
    scale29_authorized: bool


def select_startup_authority(
    inputs: StartupAuthorityInputs,
) -> StartupAuthorityDecision:
    """Retain the hybrid architecture with corrected freshness authority."""

    inputs.validate()
    return StartupAuthorityDecision(
        selected_architecture=StartupArchitecture.HYBRID,
        selected_freshness_design=FreshnessDesign.PARENT_ACKNOWLEDGED_FRAME,
        static_rejections=(
            (
                StartupArchitecture.PROCESS_ISOLATED_FULL,
                "nontransferable_parent_authority",
            ),
            (
                StartupArchitecture.TWO_STAGE_IN_PROCESS,
                "in_process_resource_not_forcibly_settleable",
            ),
        ),
        freshness_design_rejection=(
            FreshnessDesign.ONE_RECEIPT_LAG,
            "unacknowledged_terminal_write_unbounded",
        ),
        preparation_attempt_ceiling_ms=inputs.preparation_attempt_ceiling_ms,
        preparation_total_ceiling_ms=inputs.preparation_total_ceiling_ms,
        final_release_ceiling_ms=inputs.final_release_ceiling_ms,
        freshness_lease_ms=inputs.freshness_lease_ms,
        operator_guard_ms=inputs.operator_guard_ms,
        receipt_schema_version=3,
        state_machine=(
            "unprepared",
            "preparing",
            "observation_frame_received",
            "observation_frame_accepted",
            "observation_acknowledged",
            "preparation_result_received",
            "preparation_validated",
            "preparation_settled",
            "final_readiness_open",
            "transient_ownership_clear",
            "stable_sample_one",
            "stable_sample_two",
            "ready_to_release",
            "child_released",
        ),
        failure_states=("refused", "settled"),
        original_failure_matrix=_ORIGINAL_FAULT_MATRIX,
        freshness_failure_matrix=_FRESHNESS_FAULT_MATRIX,
        mutation_matrix=_MUTATION_MATRIX,
        bounded_ipc_matrix=_IPC_FAULT_MATRIX,
        selected_failure_surfaces=(
            "worker_process",
            "bounded_private_observation_control_channel",
            "immutable_canonical_evidence",
            "digest_bound_acknowledgement",
            "terminal_receipt_v3",
            "parent_observed_terminal_facts",
            "observed_campaign_results",
            "parent_monotonic_freshness",
            "process_tree_cleanup",
        ),
        fix4_contract=Scale28Fix4Contract(),
        test_cov5c_contract=TestCov5CContract(),
        production_qualified=False,
        scale29_authorized=False,
    )


def _is_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int)
