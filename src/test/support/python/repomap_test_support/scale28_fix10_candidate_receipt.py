"""Public-safe SCALE28-FIX10 corrected-candidate receipt qualification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


CORRECTED_FIX9_PATCH_SHA256 = (
    "c46003e5af8b72e2669b44764fc5daedba051d71cf6ee5091fbe485e67767f74"
)

_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ReceiptDefect(StrEnum):
    """Closed reasons a private candidate cannot be reconstructed."""

    OWNER_PRIVATE_RECEIPT_MISSING = "owner_private_receipt_missing"
    EXACT_BASE_MISSING = "exact_base_missing"
    EXACT_BASE_INVALID = "exact_base_invalid"
    PATCH_SHA256_INVALID = "patch_sha256_invalid"
    MODE_INVALID = "mode_invalid"
    CHANGED_PATH_COUNT_INVALID = "changed_path_count_invalid"
    MANIFEST_INCOMPLETE = "manifest_incomplete"
    MANIFEST_INVALID = "manifest_invalid"
    PURPOSE_MISSING = "purpose_missing"
    CREATION_PHASE_MISSING = "creation_phase_missing"


@dataclass(frozen=True, slots=True)
class CandidateReceiptEvidence:
    """One bounded public-safe view of owner-private receipt evidence."""

    owner_private_receipt_present: bool
    exact_base_commit: str | None
    patch_sha256: str
    mode: str
    changed_path_count: int
    changed_path_manifest: tuple[str, ...]
    purpose: str
    creation_phase: str


def receipt_defects(
    evidence: CandidateReceiptEvidence,
) -> tuple[ReceiptDefect, ...]:
    """Return every deterministic reconstruction blocker."""

    defects: list[ReceiptDefect] = []
    if not evidence.owner_private_receipt_present:
        defects.append(ReceiptDefect.OWNER_PRIVATE_RECEIPT_MISSING)
    if evidence.exact_base_commit is None:
        defects.append(ReceiptDefect.EXACT_BASE_MISSING)
    elif _COMMIT_PATTERN.fullmatch(evidence.exact_base_commit) is None:
        defects.append(ReceiptDefect.EXACT_BASE_INVALID)
    if _SHA256_PATTERN.fullmatch(evidence.patch_sha256) is None:
        defects.append(ReceiptDefect.PATCH_SHA256_INVALID)
    if evidence.mode != "600":
        defects.append(ReceiptDefect.MODE_INVALID)
    if evidence.changed_path_count < 1:
        defects.append(ReceiptDefect.CHANGED_PATH_COUNT_INVALID)
    if len(evidence.changed_path_manifest) != evidence.changed_path_count:
        defects.append(ReceiptDefect.MANIFEST_INCOMPLETE)
    elif (
        len(set(evidence.changed_path_manifest))
        != len(evidence.changed_path_manifest)
        or any(
            not path
            or path.startswith(("/", "../"))
            or "/../" in path
            for path in evidence.changed_path_manifest
        )
    ):
        defects.append(ReceiptDefect.MANIFEST_INVALID)
    if not evidence.purpose.strip():
        defects.append(ReceiptDefect.PURPOSE_MISSING)
    if not evidence.creation_phase.strip():
        defects.append(ReceiptDefect.CREATION_PHASE_MISSING)
    return tuple(defects)


def is_reconstructable(evidence: CandidateReceiptEvidence) -> bool:
    """Return whether evidence satisfies the complete receipt contract."""

    return not receipt_defects(evidence)


OBSERVED_CORRECTED_FIX9_EVIDENCE = CandidateReceiptEvidence(
    owner_private_receipt_present=False,
    exact_base_commit=None,
    patch_sha256=CORRECTED_FIX9_PATCH_SHA256,
    mode="600",
    changed_path_count=23,
    changed_path_manifest=(),
    purpose="corrected incomplete observer candidate",
    creation_phase="SCALE28-FIX9",
)
