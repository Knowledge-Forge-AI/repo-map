from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import math
from pathlib import Path

import pytest

from repomap_test_support.test_cov5k_r2_fix2_catalog import (
    ALLOWED_READINESS,
    build_closed_catalog,
)
from repomap_test_support.test_cov5k_r2_fix2_encoding import (
    CanonicalEncodingError,
    canonical_digest,
)
from repomap_test_support.test_cov5k_r2_fix2_gate_executor import (
    _cleanup_complete,
)
from repomap_test_support.test_cov5k_r2_fix2_receipt import (
    GateBinding,
    QualificationReceiptDraft,
    QualificationReceiptError,
    ReceiptExpectations,
    ResultBinding,
    RuntimeIdentityBinding,
    finalize_receipt,
    verify_final_receipt,
)
from repomap_test_support.test_cov5k_r2_fix2_registry import (
    build_executor_registry,
    readiness_counts,
)


def _entries(group: str):
    return tuple(entry for entry in build_closed_catalog() if entry.semantic_group == group)


def _digest(label: str) -> str:
    return canonical_digest(("test-cov5k-r2-fix2", label))


def _draft() -> tuple[QualificationReceiptDraft, ReceiptExpectations]:
    runtime = RuntimeIdentityBinding("1" * 40, "cpython-3.13", "postgresql-17", _digest("container"))
    results = (
        ResultBinding("a-1", "A", _digest("a-1"), "qualification_observation", False, "accepted"),
        ResultBinding("k-1", "K", _digest("k-1"), "qualification_observation", False, "accepted"),
    )
    draft = QualificationReceiptDraft(
        "0" * 40,
        _digest("tree"),
        runtime,
        _digest("registration"),
        _digest("source"),
        _digest("policy"),
        _digest("protocol"),
        _digest("dependency"),
        _digest("executor"),
        ("a-1", "k-1"),
        results,
        (("A", True), ("K", True)),
        (GateBinding("gate-1", _digest("gate-1"), True),),
        (GateBinding("selection-1", _digest("selection-1"), True),),
        _digest("cleanup"),
        True,
        "accepted",
    )
    expected = ReceiptExpectations(
        "2" * 40,
        _digest("tree"),
        runtime,
        _digest("registration"),
        ("a-1", "k-1"),
        ("A", "K"),
        ("gate-1",),
        _digest("cleanup"),
    )
    return draft, expected


def test_closed_registry_has_only_accepted_readiness_classes() -> None:
    contracts = build_executor_registry()
    assert len(contracts) == 1_698
    assert set(readiness_counts(contracts)) == ALLOWED_READINESS
    assert sum(readiness_counts(contracts).values()) == 1_698
    assert all(contract.callgraph_reachable for contract in contracts)


def test_catalog_has_independent_identity_and_disposition_authority() -> None:
    entries = build_closed_catalog()
    assert len({entry.authority_id for entry in entries}) == 1_698
    assert len({entry.fixed_runner_id for entry in entries}) == 1_698
    assert all(entry.case_id.lower() not in entry.authority_id.lower() for entry in entries)
    assert all(not entry.product_owner_id.startswith("fix1.owner.") for entry in entries)
    assert all(not hasattr(entry, "repetition_ids") for entry in entries)
    assert {entry.expected_execution_disposition for entry in _entries("K")} == {
        "completed",
        "controlled_preflight_refusal",
    }


class _DuplicateMapping(Mapping[str, int]):
    def __getitem__(self, key: str) -> int:
        return 1

    def __iter__(self):
        return iter(("duplicate", "duplicate"))

    def __len__(self) -> int:
        return 2

    def keys(self):
        return ["duplicate", "duplicate"]


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_canonical_encoding_rejects_each_nonfinite_float(value: float) -> None:
    with pytest.raises(CanonicalEncodingError, match="non-finite"):
        canonical_digest(value)


@pytest.mark.parametrize("value", ({"set"}, frozenset({"set"}), object()))
def test_canonical_encoding_rejects_unsupported_classes(value: object) -> None:
    with pytest.raises(CanonicalEncodingError):
        canonical_digest(value)


def test_canonical_encoding_distinguishes_all_authority_types_and_order() -> None:
    values = (True, 1, "1", ("1",), ["1"], {"1": 1}, None)
    assert len({canonical_digest(value) for value in values}) == len(values)
    assert canonical_digest({"a": 1, "b": 2}) == canonical_digest({"b": 2, "a": 1})
    with pytest.raises(CanonicalEncodingError, match="duplicate"):
        canonical_digest(_DuplicateMapping())


def test_gate_cleanup_binds_explicit_outer_runner_identity(tmp_path: Path) -> None:
    outer = tmp_path / "r" / "t1111111111"
    nested = tmp_path / "r" / "t2222222222"
    outer.mkdir(parents=True)
    nested.mkdir(parents=True)
    outer.joinpath("manifest.json").write_text(
        '{"state":"passed","exit_status":0,"live_runtime_residue":false}',
        encoding="utf-8",
    )
    nested.joinpath("manifest.json").write_text(
        '{"state":"running","exit_status":null,"live_runtime_residue":null}',
        encoding="utf-8",
    )
    output = (
        "Test run: t1111111111 (suite all)\n"
        "repomap test scratch: t2222222222 (REPOMAP_TEST_RUN_ROOT)\n"
    )

    assert _cleanup_complete(
        output, {"REPOMAP_TEST_SCRATCH_ROOT": str(tmp_path)}
    ) == ("t1111111111", True)


def test_final_receipt_closes_without_commit_hash_cycle() -> None:
    draft, expected = _draft()
    receipt = finalize_receipt(draft, expected.final_qualification_commit)
    verify_final_receipt(receipt, expected)
    assert receipt.frozen_draft_digest == draft.digest
    assert expected.final_qualification_commit not in draft.digest


@pytest.mark.parametrize(
    "mutation",
    (
        "wrong_commit",
        "wrong_tree",
        "wrong_runtime",
        "missing_result",
        "extra_result",
        "wrong_group",
        "wrong_gate",
        "wrong_cleanup",
        "model_relabel",
        "rejected_result",
        "receipt_digest",
    ),
)
def test_receipt_anti_inflation_mutations_fail_for_intended_reason(mutation: str) -> None:
    with pytest.raises(QualificationReceiptError):
        draft, expected = _draft()
        receipt = finalize_receipt(draft, expected.final_qualification_commit)
        if mutation == "wrong_commit":
            expected = replace(expected, final_qualification_commit="3" * 40)
        elif mutation == "wrong_tree":
            expected = replace(expected, final_test_tree_digest=_digest("wrong-tree"))
        elif mutation == "wrong_runtime":
            expected = replace(
                expected,
                runtime_identity=replace(expected.runtime_identity, source_commit="4" * 40),
            )
        elif mutation == "missing_result":
            receipt = finalize_receipt(replace(draft, expected_result_ids=("a-1",)), "2" * 40)
        elif mutation == "extra_result":
            expected = replace(expected, expected_result_ids=("a-1",))
        elif mutation == "wrong_group":
            expected = replace(expected, required_groups=("A",))
        elif mutation == "wrong_gate":
            expected = replace(expected, required_complete_gate_ids=("gate-2",))
        elif mutation == "wrong_cleanup":
            expected = replace(expected, cleanup_digest=_digest("wrong-cleanup"))
        elif mutation == "model_relabel":
            bad = replace(draft.accepted_results[0], model_rehearsal_only=True)
            receipt = finalize_receipt(replace(draft, accepted_results=(bad, draft.accepted_results[1])), "2" * 40)
        elif mutation == "rejected_result":
            bad = replace(draft.accepted_results[0], qualification_status="rejected")
            receipt = finalize_receipt(replace(draft, accepted_results=(bad, draft.accepted_results[1])), "2" * 40)
        elif mutation == "receipt_digest":
            receipt = replace(receipt, receipt_digest=_digest("wrong-receipt"))
        verify_final_receipt(receipt, expected)
