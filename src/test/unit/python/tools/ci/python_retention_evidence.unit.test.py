from __future__ import annotations

import copy
import json
import pytest

from ci.python_retention_evidence import (
    RetentionEvidenceError,
    canonical_json_bytes,
    compact_retention_evidence,
    create_incomplete_retention_evidence,
)
from ci.python_retention_evidence_schema import (
    COMPLETE_SCHEMA,
    INCOMPLETE_SCHEMA,
    RetentionSchemaError,
    validate_retention_evidence_schema,
)


from repomap_test_support.retention_evidence_fixture import evidence_source as _make_source


def test_canonical_json_and_reordering_determinism() -> None:
    dict1 = {"b": 2, "a": 1, "nested": {"z": 10, "y": 20}}
    dict2 = {"a": 1, "nested": {"y": 20, "z": 10}, "b": 2}
    bytes1 = canonical_json_bytes(dict1)
    bytes2 = canonical_json_bytes(dict2)
    assert bytes1 == bytes2
    assert bytes1 == b'{"a":1,"b":2,"nested":{"y":20,"z":10}}'

    set1 = {"item-b", "item-a", "item-c"}
    set2 = {"item-c", "item-b", "item-a"}
    assert canonical_json_bytes(set1) == canonical_json_bytes(set2)

    seq1 = ["alpha", "beta"]
    seq2 = ["beta", "alpha"]
    assert canonical_json_bytes(seq1) != canonical_json_bytes(seq2)

    with pytest.raises(RetentionEvidenceError, match="non-finite float"):
        canonical_json_bytes({"bad": float("nan")})
    with pytest.raises(RetentionEvidenceError, match="non-finite float"):
        canonical_json_bytes({"bad": float("inf")})


def test_compaction_non_mutation() -> None:
    source = _make_source(status="passed")
    source_copy = copy.deepcopy(source)
    compact = compact_retention_evidence(source)
    assert source == source_copy
    assert compact["schema"] == COMPLETE_SCHEMA
    assert compact["complete"] is True


def test_compact_complete_evidence_structure_and_commitments() -> None:
    source = _make_source(status="passed", file_count=5, cohort_count=3)
    compact = compact_retention_evidence(source)
    assert compact["schema"] == COMPLETE_SCHEMA
    assert compact["status"] == "passed"
    assert compact["enforcement_complete"] is True
    assert compact["totals"]["census"] == 5
    assert compact["totals"]["residual"] == 0
    assert compact["roots"]["tools"]["eligible"] == 5
    assert compact["roots"]["tools"]["residual"] == 0
    assert compact["cohorts"]["total"] == 3
    assert compact["cohorts"]["passed"] == 3

    omitted = compact["omitted_collections"]
    assert "candidate_files" in omitted
    assert omitted["candidate_files"]["count"] == 5
    assert len(omitted["candidate_files"]["sha256"]) == 64
    assert omitted["candidate_files"]["canonical_version"] == "repomap-canonical-json-v1"

    commit = compact["sanitized_source_commitment"]
    assert len(commit["sha256"]) == 64
    validate_retention_evidence_schema(compact)


def test_untruncated_regressions() -> None:
    fifty_regressions = [f"cohort_{i:04d}" for i in range(50)]
    source = _make_source(
        status="failed",
        cohort_count=60,
        file_count=60,
        regressions=fifty_regressions,
    )
    compact = compact_retention_evidence(source)
    assert compact["cohorts"]["regression_count"] == 50
    assert len(compact["cohorts"]["regressions"]) == 50
    assert compact["cohorts"]["regressions"] == sorted(fifty_regressions)
    validate_retention_evidence_schema(compact)


def test_mutation_path_fails_closed() -> None:
    source = _make_source(status="passed")
    source["eligible"]["tools"].append("tools/phantom.py")
    with pytest.raises(RetentionEvidenceError, match="eligible path not in candidate"):
        compact_retention_evidence(source)


def test_mutation_finding_index_bounds_fails_closed() -> None:
    source = _make_source(status="passed")
    source["cohort_results"]["cohort_0000"]["dependency_finding_indices"] = [999]
    with pytest.raises(RetentionEvidenceError, match="dependency finding index 999 out of bounds"):
        compact_retention_evidence(source)


def test_mutation_admission_fails_closed() -> None:
    source = _make_source(status="passed")
    source["cohorts"][0]["admission"] = "unknown_state"
    with pytest.raises(RetentionEvidenceError, match="admission invalid"):
        compact_retention_evidence(source)


def test_mutation_candidate_census_fails_closed() -> None:
    source = _make_source(status="passed")
    source["counts"]["total_files"] = 9999
    with pytest.raises(RetentionEvidenceError, match="census total_files does not match"):
        compact_retention_evidence(source)


def test_mutation_status_fails_closed() -> None:
    source = _make_source(status="passed")
    source["enforced"]["tools"] = []
    source["eligible_minus_enforced"]["tools"] = list(source["eligible"]["tools"])
    with pytest.raises(RetentionEvidenceError, match="passed status cannot have residual debt"):
        compact_retention_evidence(source)


def test_mutation_regressions_mismatch_fails_closed() -> None:
    source = _make_source(
        status="failed",
        cohort_count=4,
        regressions=["cohort_0000"],
    )
    source["cohort_regressions"] = ["cohort_0001"]
    with pytest.raises(RetentionEvidenceError, match="cohort_regressions mismatch with failed admitted cohorts"):
        compact_retention_evidence(source)


def test_root_separation_mutation_fails_closed() -> None:
    source = _make_source(status="passed")
    source["eligible"]["product"] = [source["eligible"]["tools"][0]]
    with pytest.raises(RetentionEvidenceError, match="root separation violation"):
        compact_retention_evidence(source)


def test_partition_assigned_not_subset_fails_closed() -> None:
    source = _make_source(status="passed")
    source["assigned"]["tools"].append("tools/unassigned_extra.py")
    source["candidate_sha256"]["tools/unassigned_extra.py"] = "0" * 64
    source["counts"]["total_files"] = len(source["candidate_sha256"])
    with pytest.raises(RetentionEvidenceError, match="assigned.*is not a subset of eligible"):
        compact_retention_evidence(source)


def test_malformed_evidence_schema_failure() -> None:
    valid_compact = compact_retention_evidence(_make_source(status="passed"))

    bad_schema = dict(valid_compact, schema="bad-schema-v99")
    with pytest.raises(RetentionSchemaError, match="unsupported retention evidence schema"):
        validate_retention_evidence_schema(bad_schema)

    bad_totals = copy.deepcopy(valid_compact)
    bad_totals["totals"]["census"] = -5
    with pytest.raises(RetentionSchemaError, match="totals.census must be a non-negative integer"):
        validate_retention_evidence_schema(bad_totals)

    bad_sha = copy.deepcopy(valid_compact)
    bad_sha["sanitized_source_commitment"]["sha256"] = "invalid_short_hash"
    with pytest.raises(RetentionSchemaError, match="valid 64-char hex string"):
        validate_retention_evidence_schema(bad_sha)


def test_incomplete_variant_generation_and_validation() -> None:
    incomplete = create_incomplete_retention_evidence(
        error="fatal syntax error",
        raw_output="line 1: unexpected EOF",
        classification="tool-failure",
        returncode=2,
        failure_stage="parse-non-json",
    )
    assert incomplete["schema"] == INCOMPLETE_SCHEMA
    assert incomplete["status"] == "failed"
    assert incomplete["classification"] == "tool-failure"
    assert incomplete["complete"] is False
    assert incomplete["returncode"] == 2
    validate_retention_evidence_schema(incomplete)

    tampered_pass = dict(incomplete, status="passed")
    with pytest.raises(RetentionSchemaError, match="incomplete evidence status must be 'failed'"):
        validate_retention_evidence_schema(tampered_pass)

    tampered_complete = dict(incomplete, complete=True)
    with pytest.raises(RetentionSchemaError, match="incomplete evidence complete must be False"):
        validate_retention_evidence_schema(tampered_complete)


def test_realistic_1122_cohorts_scale_under_1mib() -> None:
    """A realistic cohort inventory with 1,125 cohorts produces compact JSON well under 1 MiB."""
    cohort_total = 1125
    file_total = 1200
    source = _make_source(
        status="passed",
        cohort_count=cohort_total,
        file_count=file_total,
    )
    raw_source_bytes = len(json.dumps(source).encode("utf-8"))

    compact = compact_retention_evidence(source)
    compact_bytes = json.dumps(compact, separators=(",", ":"), sort_keys=True).encode("utf-8")
    compact_size = len(compact_bytes)

    assert compact["cohorts"]["total"] == cohort_total
    assert compact["totals"]["census"] == file_total
    assert compact_size < 1024 * 1024, f"Compact size {compact_size} bytes exceeds 1 MiB"
    # Compact size should be significantly smaller than raw
    assert compact_size < raw_source_bytes
    validate_retention_evidence_schema(compact)


def test_compact_atomic_groups_summary_counts_and_commitments() -> None:
    from ci.python_retention_atomic_source import make_atomic_group_id, make_internal_dependency_sha256
    source = _make_source(status="passed", file_count=4, cohort_count=2)
    cids = ["cohort_0000", "cohort_0001"]
    gid = make_atomic_group_id(cids)
    source["cohort_results"]["cohort_0000"]["atomic_group_id"] = gid
    source["cohort_results"]["cohort_0001"]["atomic_group_id"] = gid
    source["atomic_groups"] = {
        gid: {
            "id": gid,
            "cohort_ids": cids,
            "root": "tools",
            "governing_profile": "clean_tooling",
            "internal_dependency_count": 2,
            "internal_dependency_sha256": make_internal_dependency_sha256([["tools/tool_0.py", "tools/tool_1.py"]]),
            "external_dependency_indices": [],
            "ungoverned_dependency_indices": [],
            "dependency_blocker_indices": [],
            "status": "passed",
            "effective_enforcement": True,
        }
    }
    compact = compact_retention_evidence(source)
    assert "atomic_groups" in compact
    summary = compact["atomic_groups"]
    assert summary["total"] == 1
    assert summary["passed"] == 1
    assert summary["effective"] == 1
    assert summary["blocked"] == 0
    assert summary["examples"] == {}
    assert summary["commitment"]["element_type"] == "atomic_group"
    assert summary["commitment"]["count"] == 1
    assert len(summary["commitment"]["sha256"]) == 64
    assert compact["omitted_collections"]["atomic_groups"]["count"] == 1
    validate_retention_evidence_schema(compact)


def test_compact_atomic_groups_blocked_examples() -> None:
    from ci.python_retention_atomic_source import make_atomic_group_id, make_internal_dependency_sha256
    source = _make_source(status="failed", file_count=4, cohort_count=2, regressions=["cohort_0000", "cohort_0001"])
    cids = ["cohort_0000", "cohort_0001"]
    gid = make_atomic_group_id(cids)
    source["cohort_results"]["cohort_0000"]["atomic_group_id"] = gid
    source["cohort_results"]["cohort_0001"]["atomic_group_id"] = gid
    source["cohort_dependency_blockers"] = ["cyclic import cycle blocker"]
    source["atomic_groups"] = {
        gid: {
            "id": gid,
            "cohort_ids": cids,
            "root": "tools",
            "governing_profile": "clean_tooling",
            "internal_dependency_count": 2,
            "internal_dependency_sha256": make_internal_dependency_sha256([["tools/tool_0.py", "tools/tool_1.py"]]),
            "external_dependency_indices": [],
            "ungoverned_dependency_indices": [],
            "dependency_blocker_indices": [0],
            "status": "failed",
            "effective_enforcement": False,
        }
    }
    compact = compact_retention_evidence(source, max_examples=2)
    summary = compact["atomic_groups"]
    assert summary["total"] == 1
    assert summary["passed"] == 0
    assert summary["effective"] == 0
    assert summary["blocked"] == 1
    assert gid in summary["examples"]
    assert summary["examples"][gid] == ["cyclic import cycle blocker"]
    assert compact["bounded_examples"]["atomic_groups"] == summary["examples"]
    validate_retention_evidence_schema(compact)


def test_compact_cohort_records_indexes_atomic_group_dependencies_and_blockers() -> None:
    from ci.python_retention_cohort_checks import compact_cohort_records
    result = {
        "cohort_results": {
            "cohort_0000": {
                "governed_dependencies": ["tools/common.py"],
                "ungoverned_dependencies": [],
                "dependency_blockers": ["cohort blocker reason"],
            }
        },
        "atomic_groups": {
            "scc-v1-test": {
                "external_dependencies": ["tools/group_dep.py"],
                "ungoverned_dependencies": ["tools/unmet_dep.py"],
                "dependency_blockers": ["group blocker reason"],
            }
        },
    }
    compacted = compact_cohort_records(result)
    assert compacted["cohort_dependency_paths"] == [
        "tools/common.py",
        "tools/group_dep.py",
        "tools/unmet_dep.py",
    ]
    assert compacted["cohort_dependency_blockers"] == [
        "cohort blocker reason",
        "group blocker reason",
    ]
    g_rec = compacted["atomic_groups"]["scc-v1-test"]
    assert g_rec["external_dependency_indices"] == [1]
    assert g_rec["ungoverned_dependency_indices"] == [2]
    assert g_rec["dependency_blocker_indices"] == [1]
    assert "external_dependencies" not in g_rec
