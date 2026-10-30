"""Unit tests for pure hosted native D12 qualification evidence validation."""

from __future__ import annotations

import copy
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ci.d12_hosted_evidence as evidence_mod
from ci.d12_hosted_evidence import (
    HostedD12EvidenceError,
    validate_expected_candidate_record,
    validate_sealed_d12_evidence,
    validate_system_hold_refusal,
)
from ci.d12_hosted_reports import APPLICATION_BUILD_COUNT_KEYS
from src.test.unit.python.tools.ci.d12_hosted_fixtures import (
    SYNTHETIC_SDK_RECIPE_SHA256,
    make_expected_candidate_record,
    make_sealed_evidence,
    make_system_hold_refusal_report,
)
from common_lore_index.runtime import python_payload as payload


def test_private_hash_literals_absent_and_expected_candidate_record_domains_distinct() -> None:
    assert not hasattr(evidence_mod, "ARM64_PRIVATE_E4_SOURCE_SHA256")
    assert not hasattr(evidence_mod, "R39_RESULT_MANIFEST_SHA256")
    record = make_expected_candidate_record()
    validated = validate_expected_candidate_record(record)
    assert validated["platform"] == "linux/amd64"
    assert validated["d12_context"]["context_file_count"] == 694


def test_expected_candidate_record_rejects_conflated_or_self_referential_fields() -> None:
    with_commit = make_expected_candidate_record()
    with_commit["commit_sha"] = "1" * 40
    with pytest.raises(HostedD12EvidenceError, match="commit|keys"):
        validate_expected_candidate_record(with_commit)

    duplicate_domain = make_expected_candidate_record()
    duplicate_domain["sdk_sandbox"]["sdk_recipe_sha256"] = (
        duplicate_domain["d12_context"]["source_sha256"]
    )
    with pytest.raises(HostedD12EvidenceError, match="distinct"):
        validate_expected_candidate_record(duplicate_domain)

    bad_count = make_expected_candidate_record()
    bad_count["d12_context"]["context_file_count"] = True
    with pytest.raises(HostedD12EvidenceError, match="context_file_count"):
        validate_expected_candidate_record(bad_count)


def test_sealed_evidence_accepts_partial_refusal_only_as_unqualified() -> None:
    refused = make_sealed_evidence(positive=False)
    sdk_mat = refused["sdk_materialization"]
    assert sdk_mat.get("sdk_image_id") == "sha256:" + "01" * 32
    assert sdk_mat.get("sdk_architecture") == "amd64"
    assert sdk_mat.get("sdk_recipe_sha256") == SYNTHETIC_SDK_RECIPE_SHA256
    assert sdk_mat.get("added_sdk_images") == ["sha256:" + "01" * 32]
    assert sdk_mat.get("removed_sdk_images") == []
    assert validate_sealed_d12_evidence(refused) == []
    pos_violations = validate_sealed_d12_evidence(
        refused, require_positive_qualification=True
    )
    assert any("positive" in item or "qualified" in item for item in pos_violations)

    falsely_qualified = copy.deepcopy(refused)
    falsely_qualified["qualified"] = True
    assert validate_sealed_d12_evidence(falsely_qualified) != []

    falsely_passed = copy.deepcopy(refused)
    falsely_passed["result"] = "passed"
    assert validate_sealed_d12_evidence(falsely_passed) != []


def test_sealed_evidence_accepts_positive_record_without_raw_dpkg_lines_nb4(monkeypatch: pytest.MonkeyPatch) -> None:
    positive = make_sealed_evidence(positive=True)
    assert validate_sealed_d12_evidence(positive) == []
    assert (
        validate_sealed_d12_evidence(positive, require_positive_qualification=True)
        == []
    )
    extra_nb4 = copy.deepcopy(positive)
    extra_nb4["inner_reports"]["exploration"]["steps"]["libpq_runtime"][
        "raw_filtered_lines"
    ] = ["??5?????? c /etc/dpkg/dpkg.cfg"]
    violations = validate_sealed_d12_evidence(
        extra_nb4, require_positive_qualification=True
    )
    assert any("libpq_runtime" in item for item in violations)
    admitted = payload.PYTHON_PAYLOAD_EXCLUSIONS["amd64"]
    assert admitted == payload.build_31216_exclusion("amd64", payload.AMD64_31216_NATIVE_BASELINE_IMPORTS)
    held = {k: v for k, v in payload.PYTHON_PAYLOAD_EXCLUSIONS.items() if k != "amd64"}
    foreign = admitted._replace(python_config="sha256:a33c10a97f11005523814c6eee013986119fe41f3122f444518117536675c8e1")
    for doubled in (held, {**held, "amd64": foreign}):  # isolated held and foreign (3.12.15) source maps
        monkeypatch.setattr(payload, "PYTHON_PAYLOAD_EXCLUSIONS", doubled)
        assert any("invalid trim contract or config" in item
                   for item in validate_sealed_d12_evidence(positive, require_positive_qualification=True))


def test_sealed_evidence_rejects_pr_attempt_and_parent_binding_violations() -> None:
    base = make_sealed_evidence(positive=False)

    attempt2 = copy.deepcopy(base)
    attempt2["pr_binding"]["run_attempt"] = 2
    assert any("run_attempt" in v for v in validate_sealed_d12_evidence(attempt2))

    bool_attempt = copy.deepcopy(base)
    bool_attempt["pr_binding"]["run_attempt"] = True
    assert any("run_attempt" in v for v in validate_sealed_d12_evidence(bool_attempt))

    fork_pr = copy.deepcopy(base)
    fork_pr["pr_binding"]["head_repo"] = "attacker/repo-map"
    assert any("head_repo" in v or "repository" in v for v in validate_sealed_d12_evidence(fork_pr))

    wrong_head_ref = copy.deepcopy(base)
    wrong_head_ref["pr_binding"]["head_ref"] = "feature"
    assert any("head_ref" in v for v in validate_sealed_d12_evidence(wrong_head_ref))

    parent_mismatch = copy.deepcopy(base)
    parent_mismatch["pr_binding"]["candidate_head_parent"] = "9" * 40
    assert any(
        "candidate_head_parent" in v
        for v in validate_sealed_d12_evidence(parent_mismatch)
    )


def test_sealed_evidence_rejects_outer_seal_errors_validation_violations_and_app_builds() -> None:
    for positive in (False, True):
        base = make_sealed_evidence(positive=positive)
        with_seal_err = copy.deepcopy(base)
        with_seal_err["seal_errors"] = ["prepare refused at sdk_materialization: inspect failed"]
        assert any(
            "seal_errors" in v
            for v in validate_sealed_d12_evidence(
                with_seal_err, require_positive_qualification=positive
            )
        )

        malformed_seal_err = copy.deepcopy(base)
        malformed_seal_err["seal_errors"] = [""]
        assert any(
            "seal_errors" in v
            for v in validate_sealed_d12_evidence(
                malformed_seal_err, require_positive_qualification=positive
            )
        )

        with_val_viol = copy.deepcopy(base)
        with_val_viol["validation_violations"] = ["freeze missing"]
        assert any(
            "validation_violations" in v
            for v in validate_sealed_d12_evidence(
                with_val_viol, require_positive_qualification=positive
            )
        )

        all_six_keys = (
            "application_builds",
            "application_candidate_builds",
            *APPLICATION_BUILD_COUNT_KEYS,
        )
        for key in all_six_keys:
            for bad_val in (None, 1, False):
                bad_app = copy.deepcopy(base)
                bad_app["application_builds"][key] = bad_val
                assert any(
                    key in v or "application_builds" in v
                    for v in validate_sealed_d12_evidence(
                        bad_app, require_positive_qualification=positive
                    )
                )

        inner_mismatch = copy.deepcopy(base)
        inner_mismatch["inner_reports"]["freeze"]["budget"]["unmanaged_build_count"] = 1
        assert any(
            "unmanaged_build_count" in v or "application_builds" in v
            for v in validate_sealed_d12_evidence(
                inner_mismatch, require_positive_qualification=positive
            )
        )


def test_sealed_evidence_warm_and_cold_sdk_materialization_and_residue_checks() -> None:
    base = make_sealed_evidence(positive=False)

    warm = copy.deepcopy(base)
    warm["sdk_materialization"]["sdk_build_attempts"] = 0
    warm["sdk_materialization"]["intent_recorded_before_build"] = False
    warm["sdk_materialization"]["intent_receipt_sha256"] = None
    warm["sdk_materialization"]["sdk_cache_cold_built"] = False
    warm["sdk_materialization"]["added_sdk_images"] = []
    warm["sdk_materialization"]["removed_sdk_images"] = []
    warm["sdk_materialization"]["entry_baseline"]["images"] = ["sha256:" + "01" * 32]
    warm["sdk_materialization"]["post_sdk_baseline"]["images"] = ["sha256:" + "01" * 32]
    assert validate_sealed_d12_evidence(warm) == []

    warm_bad_intent = copy.deepcopy(warm)
    warm_bad_intent["sdk_materialization"]["intent_recorded_before_build"] = True
    assert any("sdk_materialization" in v for v in validate_sealed_d12_evidence(warm_bad_intent))

    bad_arch = copy.deepcopy(base)
    bad_arch["sdk_materialization"]["sdk_architecture"] = "arm64"
    assert any("sdk_architecture" in v for v in validate_sealed_d12_evidence(bad_arch))

    bad_recipe = copy.deepcopy(base)
    bad_recipe["sdk_materialization"]["sdk_recipe_sha256"] = "f" * 64
    assert any("sdk_recipe_sha256" in v for v in validate_sealed_d12_evidence(bad_recipe))

    bad_removed = copy.deepcopy(base)
    bad_removed["sdk_materialization"]["removed_sdk_images"] = ["sha256:" + "99" * 32]
    assert any("removed_sdk_images" in v for v in validate_sealed_d12_evidence(bad_removed))

    emulated = copy.deepcopy(base)
    emulated["native_environment"]["emulated"] = True
    assert any("emulated" in v for v in validate_sealed_d12_evidence(emulated))

    retry = copy.deepcopy(base)
    retry["sdk_materialization"]["sdk_build_attempts"] = 2
    assert any("sdk_build_attempts" in v for v in validate_sealed_d12_evidence(retry))

    false_parity = copy.deepcopy(base)
    false_parity["sdk_materialization"]["whole_job_image_parity_claimed"] = True
    assert any(
        "whole_job_image_parity_claimed" in v
        for v in validate_sealed_d12_evidence(false_parity)
    )

    outer_added = copy.deepcopy(base)
    outer_added["sdk_materialization"]["post_sdk_cleanup"]["images_added"] = [
        "sha256:" + "ab" * 32
    ]
    assert any("post_sdk_cleanup" in v for v in validate_sealed_d12_evidence(outer_added))

    outer_removed = copy.deepcopy(base)
    outer_removed["sdk_materialization"]["post_sdk_cleanup"]["images_removed"] = [
        "sha256:" + "01" * 32
    ]
    assert any("post_sdk_cleanup" in v for v in validate_sealed_d12_evidence(outer_removed))


def test_sealed_evidence_rejects_unverified_amd_base_or_premature_continuation() -> None:
    base = make_sealed_evidence(positive=False)

    bad_go = copy.deepcopy(base)
    bad_go["inner_reports"]["exploration"]["steps"]["identity"]["go"] = (
        "sha256:" + "0" * 64
    )
    assert any("go" in v for v in validate_sealed_d12_evidence(bad_go))

    premature = copy.deepcopy(base)
    premature["inner_reports"]["exploration"]["steps"]["builder"] = {
        "native": "amd64",
        "preexisting_rows": 120,
        "packages": [],
    }
    assert any(
        "builder" in v or "premature" in v
        for v in validate_sealed_d12_evidence(premature)
    )

    unredacted = copy.deepcopy(base)
    unredacted["inner_reports"]["exploration"]["refusals"] = [
        "closure: failed at /" + "Users/alice/private/repo"
    ]
    assert any("redact" in v or "private" in v for v in validate_sealed_d12_evidence(unredacted))


def test_system_hold_refusal_validation_enforces_zero_builds_and_bindings() -> None:
    report = make_system_hold_refusal_report()
    assert validate_system_hold_refusal(report) == []

    bad_build_count = copy.deepcopy(report)
    bad_build_count["application_candidate_builds_started"] = 1
    assert any(
        "application_candidate_builds_started" in v
        for v in validate_system_hold_refusal(bad_build_count)
    )

    bad_qualified = copy.deepcopy(report)
    bad_qualified["qualified"] = True
    assert any("qualified" in v for v in validate_system_hold_refusal(bad_qualified))
