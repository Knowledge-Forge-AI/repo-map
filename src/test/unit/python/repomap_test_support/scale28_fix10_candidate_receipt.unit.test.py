from __future__ import annotations

from dataclasses import replace

import pytest

from repomap_test_support.scale28_fix10_candidate_receipt import (
    CandidateReceiptEvidence,
    OBSERVED_CORRECTED_FIX9_EVIDENCE,
    ReceiptDefect,
    is_reconstructable,
    receipt_defects,
)


_COMPLETE = CandidateReceiptEvidence(
    owner_private_receipt_present=True,
    exact_base_commit="a" * 40,
    patch_sha256="b" * 64,
    mode="600",
    changed_path_count=2,
    changed_path_manifest=("tools/one.py", "tools/two.py"),
    purpose="bounded corrected candidate",
    creation_phase="SCALE28-FIX9",
)


def test_fix10_rejects_observed_corrected_candidate_packet() -> None:
    assert receipt_defects(OBSERVED_CORRECTED_FIX9_EVIDENCE) == (
        ReceiptDefect.OWNER_PRIVATE_RECEIPT_MISSING,
        ReceiptDefect.EXACT_BASE_MISSING,
        ReceiptDefect.MANIFEST_INCOMPLETE,
    )
    assert not is_reconstructable(OBSERVED_CORRECTED_FIX9_EVIDENCE)


def test_fix10_accepts_only_one_complete_owner_private_receipt() -> None:
    assert receipt_defects(_COMPLETE) == ()
    assert is_reconstructable(_COMPLETE)


@pytest.mark.parametrize(
    ("changed", "defect"),
    (
        (
            replace(_COMPLETE, owner_private_receipt_present=False),
            ReceiptDefect.OWNER_PRIVATE_RECEIPT_MISSING,
        ),
        (
            replace(_COMPLETE, exact_base_commit=None),
            ReceiptDefect.EXACT_BASE_MISSING,
        ),
        (
            replace(_COMPLETE, exact_base_commit="z" * 40),
            ReceiptDefect.EXACT_BASE_INVALID,
        ),
        (
            replace(_COMPLETE, patch_sha256="z" * 64),
            ReceiptDefect.PATCH_SHA256_INVALID,
        ),
        (replace(_COMPLETE, mode="644"), ReceiptDefect.MODE_INVALID),
        (
            replace(_COMPLETE, changed_path_count=0, changed_path_manifest=()),
            ReceiptDefect.CHANGED_PATH_COUNT_INVALID,
        ),
        (
            replace(_COMPLETE, changed_path_manifest=()),
            ReceiptDefect.MANIFEST_INCOMPLETE,
        ),
        (
            replace(
                _COMPLETE,
                changed_path_manifest=("tools/one.py", "tools/one.py"),
            ),
            ReceiptDefect.MANIFEST_INVALID,
        ),
        (
            replace(
                _COMPLETE,
                changed_path_manifest=("../one.py", "tools/two.py"),
            ),
            ReceiptDefect.MANIFEST_INVALID,
        ),
        (replace(_COMPLETE, purpose=""), ReceiptDefect.PURPOSE_MISSING),
        (
            replace(_COMPLETE, creation_phase=""),
            ReceiptDefect.CREATION_PHASE_MISSING,
        ),
    ),
)
def test_fix10_receipt_contract_rejects_each_independent_defect(
    changed: CandidateReceiptEvidence,
    defect: ReceiptDefect,
) -> None:
    assert defect in receipt_defects(changed)
