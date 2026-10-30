from __future__ import annotations

from copy import deepcopy
from typing import cast

from ci.python_retention_product_progress import build_product_profile_facts
from ci.retained_python_ratchets import baseline_document, compare_snapshot
from ci.retained_python_records import SnapshotDocument


def _module(module: str, path: str, tier: str) -> dict[str, str]:
    return {
        "module": module,
        "path": path,
        "ownership_class": "cross_language_contract" if tier != "T1-future" else "python_retained",
        "tier": tier,
    }


def _snapshot() -> SnapshotDocument:
    contract = "src/main/python/common_lore_index/contract.py"
    seed = "src/main/python/common_lore_index/seed.py"
    future = "src/main/python/common_lore_index/future.py"
    clean = "src/main/python/common_lore_index/clean.py"
    return cast(SnapshotDocument, {
        "ownership": {"manifest_path": "tools/ci/python_type_ownership.json", "sha256": "a" * 64},
        "tools": {"mypy": "2.1.0", "ruff": "0.16.2", "ruff_rules": ["F"], "ruff_target_version": "py312"},
        "selection": {"ownership_classes": ["cross_language_contract", "python_retained"],
                      "tiers": ["T0", "T1-future", "T1-seed"], "modules": [
                          _module("common_lore_index.clean", clean, "T1-future"),
                          _module("common_lore_index.contract", contract, "T0"),
                          _module("common_lore_index.future", future, "T1-future"),
                          _module("common_lore_index.seed", seed, "T1-seed"),
                      ]},
        "ruff": {"findings": []},
        "mypy": {"findings": []},
        "migration_direction_imports": {"edges": []},
        "file_length": {"warning_limit": 400, "failure_limit": 1000,
                        "ceilings": [], "hard_failures": []},
    })


def test_product_facts_separate_actual_and_historical_findings() -> None:
    baseline = _snapshot()
    future = "src/main/python/common_lore_index/future.py"
    baseline["ruff"]["findings"] = [{
        "path": future, "code": "F401", "message": "unused",
        "fingerprint": "b" * 64, "count": 1,
    }]
    baseline["mypy"]["findings"] = [{
        "module": "common_lore_index.future", "path": future, "error_code": "arg-type",
        "normalized_fingerprint": "c" * 64, "count": 1,
    }]
    baseline["file_length"]["ceilings"] = [{"path": future, "line_count": 450}]
    actual = deepcopy(baseline)
    contract = "src/main/python/common_lore_index/contract.py"
    actual["ruff"]["findings"].append({
        "path": contract, "code": "F821", "message": "undefined",
        "fingerprint": "d" * 64, "count": 1,
    })

    facts = build_product_profile_facts(actual, baseline)

    assert facts["profile_executed_paths"] == sorted({
        "src/main/python/common_lore_index/clean.py", contract, future,
        "src/main/python/common_lore_index/seed.py",
    })
    assert facts["actual_finding_paths"]["ruff"] == sorted([contract, future])
    assert facts["actual_finding_paths"]["mypy"] == [future]
    assert facts["actual_finding_paths"]["file_length"] == [future]
    assert facts["historical_allowed_paths"] == [future]
    assert facts["unknown_paths"] == sorted([contract, "src/main/python/common_lore_index/seed.py"])
    assert facts["clean_under_profile"] == ["src/main/python/common_lore_index/clean.py"]


def test_missing_type_evidence_keeps_blocking_tiers_unknown() -> None:
    snapshot = _snapshot()

    facts = build_product_profile_facts(snapshot, _snapshot())

    assert facts["type_evidence"]["status"] == "not-provided"
    assert facts["clean_under_profile"] == ["src/main/python/common_lore_index/clean.py", "src/main/python/common_lore_index/future.py"]
    assert facts["unknown_paths"] == [
        "src/main/python/common_lore_index/contract.py",
        "src/main/python/common_lore_index/seed.py",
    ]


def test_type_evidence_can_attest_t0_and_seed_paths() -> None:
    snapshot = _snapshot()
    required = [
        "src/main/python/common_lore_index/contract.py",
        "src/main/python/common_lore_index/seed.py",
    ]

    facts = build_product_profile_facts(
        snapshot,
        _snapshot(),
        type_evidence={"status": "passed", "blocking_targets": required,
                       "blocking_inventory": []},
    )

    assert facts["type_evidence"]["status"] == "passed"
    assert facts["unknown_paths"] == []
    assert facts["clean_under_profile"] == [
        "src/main/python/common_lore_index/clean.py",
        "src/main/python/common_lore_index/contract.py",
        "src/main/python/common_lore_index/future.py",
        "src/main/python/common_lore_index/seed.py",
    ]


def test_compare_snapshot_emits_facts_without_changing_policy_result() -> None:
    snapshot = _snapshot()
    baseline = baseline_document(snapshot)

    result = compare_snapshot(snapshot, baseline, mode="check")

    facts = result["profile_path_facts"]
    assert isinstance(facts, dict)
    summary = result["summary"]
    assert isinstance(summary, dict)
    assert "profile_path_facts" not in summary
    assert result["classification"] == "passed"
    assert facts["profile_executed_paths"] == [
        "src/main/python/common_lore_index/clean.py",
        "src/main/python/common_lore_index/contract.py",
        "src/main/python/common_lore_index/future.py",
        "src/main/python/common_lore_index/seed.py",
    ]
    assert facts["unknown_paths"] == [
        "src/main/python/common_lore_index/contract.py",
        "src/main/python/common_lore_index/seed.py",
    ]
