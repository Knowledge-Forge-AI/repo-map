"""Non-circular final qualification receipt contract for TEST-COV5K."""

from __future__ import annotations

from dataclasses import dataclass
import re

from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest


_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")


class QualificationReceiptError(ValueError):
    """The qualification receipt does not close its declared authority."""


@dataclass(frozen=True, slots=True)
class ResultBinding:
    result_id: str
    semantic_group: str
    result_digest: str
    purpose: str
    model_rehearsal_only: bool
    qualification_status: str


@dataclass(frozen=True, slots=True)
class GateBinding:
    gate_id: str
    manifest_digest: str
    passed: bool


@dataclass(frozen=True, slots=True)
class RuntimeIdentityBinding:
    source_commit: str
    python_identity: str
    postgres_identity: str
    container_identity_digest: str


@dataclass(frozen=True, slots=True)
class QualificationReceiptDraft:
    base_implementation_commit: str
    final_test_tree_digest: str
    runtime_identity: RuntimeIdentityBinding
    pre_registration_digest: str
    source_manifest_digest: str
    policy_manifest_digest: str
    protocol_manifest_digest: str
    dependency_manifest_digest: str
    executor_manifest_digest: str
    expected_result_ids: tuple[str, ...]
    accepted_results: tuple[ResultBinding, ...]
    per_group_acceptance: tuple[tuple[str, bool], ...]
    complete_gates: tuple[GateBinding, ...]
    focused_selections: tuple[GateBinding, ...]
    cleanup_digest: str
    cleanup_complete: bool
    qualification_candidate_outcome: str

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class FinalQualificationReceipt:
    draft: QualificationReceiptDraft
    frozen_draft_digest: str
    final_qualification_commit: str
    receipt_digest: str


@dataclass(frozen=True, slots=True)
class ReceiptExpectations:
    final_qualification_commit: str
    final_test_tree_digest: str
    runtime_identity: RuntimeIdentityBinding
    pre_registration_digest: str
    expected_result_ids: tuple[str, ...]
    required_groups: tuple[str, ...]
    required_complete_gate_ids: tuple[str, ...]
    cleanup_digest: str


def _digest(value: str, label: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise QualificationReceiptError(f"{label} is not a SHA-256 digest")


def _unique(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise QualificationReceiptError(f"{label} contains duplicates")


def validate_draft(draft: QualificationReceiptDraft) -> None:
    """Reject incomplete, inflated, or circular pre-commit authority."""

    if not _COMMIT.fullmatch(draft.base_implementation_commit):
        raise QualificationReceiptError("base implementation commit is invalid")
    if not _COMMIT.fullmatch(draft.runtime_identity.source_commit):
        raise QualificationReceiptError("runtime source commit is invalid")
    for label, value in (
        ("final test tree", draft.final_test_tree_digest),
        ("pre-registration", draft.pre_registration_digest),
        ("source manifest", draft.source_manifest_digest),
        ("policy manifest", draft.policy_manifest_digest),
        ("protocol manifest", draft.protocol_manifest_digest),
        ("dependency manifest", draft.dependency_manifest_digest),
        ("executor manifest", draft.executor_manifest_digest),
        ("cleanup", draft.cleanup_digest),
    ):
        _digest(value, label)
    _unique(draft.expected_result_ids, "expected result ids")
    result_ids = tuple(result.result_id for result in draft.accepted_results)
    _unique(result_ids, "accepted result ids")
    if set(result_ids) != set(draft.expected_result_ids):
        raise QualificationReceiptError("accepted result set is missing or extra")
    for result in draft.accepted_results:
        _digest(result.result_digest, f"result {result.result_id}")
        if result.model_rehearsal_only:
            raise QualificationReceiptError("model rehearsal cannot be accepted")
        if result.purpose != "qualification_observation":
            raise QualificationReceiptError("result purpose is not qualification")
        if result.qualification_status != "accepted":
            raise QualificationReceiptError("rejected result cannot be accepted")
    group_names = tuple(group for group, _ in draft.per_group_acceptance)
    _unique(group_names, "group acceptance")
    if not draft.per_group_acceptance or not all(
        accepted for _, accepted in draft.per_group_acceptance
    ):
        raise QualificationReceiptError("per-group acceptance is incomplete")
    gate_ids = tuple(gate.gate_id for gate in draft.complete_gates)
    _unique(gate_ids, "complete gates")
    if not draft.complete_gates or not all(gate.passed for gate in draft.complete_gates):
        raise QualificationReceiptError("complete gate authority is incomplete")
    for gate in (*draft.complete_gates, *draft.focused_selections):
        _digest(gate.manifest_digest, f"gate {gate.gate_id}")
        if not gate.passed:
            raise QualificationReceiptError("failed selection cannot be accepted")
    if not draft.cleanup_complete:
        raise QualificationReceiptError("cleanup is incomplete")
    if draft.qualification_candidate_outcome != "accepted":
        raise QualificationReceiptError("candidate outcome is not accepted")
    canonical_digest(draft)


def finalize_receipt(
    draft: QualificationReceiptDraft,
    final_qualification_commit: str,
) -> FinalQualificationReceipt:
    """Bind a pre-commit draft after commit without changing its bytes."""

    validate_draft(draft)
    if not _COMMIT.fullmatch(final_qualification_commit):
        raise QualificationReceiptError("final qualification commit is invalid")
    frozen = draft.digest
    payload = {
        "frozen_draft_digest": frozen,
        "final_qualification_commit": final_qualification_commit,
    }
    return FinalQualificationReceipt(
        draft,
        frozen,
        final_qualification_commit,
        canonical_digest(payload),
    )


def verify_final_receipt(
    receipt: FinalQualificationReceipt,
    expected: ReceiptExpectations,
) -> None:
    """Verify commit, tree, runtime, result, gate, cleanup, and receipt closure."""

    validate_draft(receipt.draft)
    if receipt.frozen_draft_digest != receipt.draft.digest:
        raise QualificationReceiptError("pre-commit draft changed after finalization")
    if receipt.final_qualification_commit != expected.final_qualification_commit:
        raise QualificationReceiptError("wrong final qualification commit")
    if receipt.draft.final_test_tree_digest != expected.final_test_tree_digest:
        raise QualificationReceiptError("wrong final test tree")
    if receipt.draft.runtime_identity != expected.runtime_identity:
        raise QualificationReceiptError("wrong runtime identity")
    if receipt.draft.pre_registration_digest != expected.pre_registration_digest:
        raise QualificationReceiptError("wrong pre-registration authority")
    if set(receipt.draft.expected_result_ids) != set(expected.expected_result_ids):
        raise QualificationReceiptError("wrong result authority")
    accepted_groups = {
        group for group, accepted in receipt.draft.per_group_acceptance if accepted
    }
    if accepted_groups != set(expected.required_groups):
        raise QualificationReceiptError("wrong per-group acceptance")
    gate_ids = {gate.gate_id for gate in receipt.draft.complete_gates if gate.passed}
    if gate_ids != set(expected.required_complete_gate_ids):
        raise QualificationReceiptError("wrong complete gate authority")
    if receipt.draft.cleanup_digest != expected.cleanup_digest:
        raise QualificationReceiptError("wrong cleanup authority")
    expected_receipt_digest = canonical_digest(
        {
            "frozen_draft_digest": receipt.frozen_draft_digest,
            "final_qualification_commit": receipt.final_qualification_commit,
        }
    )
    if receipt.receipt_digest != expected_receipt_digest:
        raise QualificationReceiptError("final receipt digest is invalid")
