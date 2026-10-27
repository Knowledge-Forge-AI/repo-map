"""Unit tests for ADR 0100 Python 3.12.16 native linux/arm64 proof helpers and refusal guards."""

from __future__ import annotations

import json
from typing import Any

import pytest

from repomap_kg.runtime import python_payload as payload
from repomap_kg.runtime import release
from repomap_kg.runtime import release_manifest as historical
from repomap_test_support import d12_python31216 as proof
from repomap_test_support.resource_docker_operation_records import DERIVED_OPERATION_FIELDS

ZERO_OPERATIONS = {field: 0 for field in DERIVED_OPERATION_FIELDS}


def _raw_report(**overrides: Any) -> dict[str, Any]:
    tk_path = proof.ARM64_TKINTER_PATH
    baseline: dict[str, Any] = {
        "machine": "aarch64",
        "entries": 4200,
        "digest": "1" * 64,
        "dynload_real": payload.DYNLOAD,
        "elves": {
            tk_path: {
                "sha256": proof.ARM64_TKINTER_SHA256,
                "size": proof.ARM64_TKINTER_SIZE,
                "ldd_exit": 0,
                "elf": [2, 1, proof.ARM64_TKINTER_ELF_MACHINE],
                "ldd": "\tlibtcl8.6.so => not found\n\tlibtk8.6.so => not found\n",
            }
        },
        "dynload": [[f"{m}.cpython-312-aarch64-linux-gnu.so", "file"]
                    for m in (*historical.ARM64_BASELINE_IMPORTS, "_tkinter")],
        "imports": list(historical.ARM64_BASELINE_IMPORTS),
        "failed": {"_tkinter": {"exit": 1, "error": "ImportError: libtk8.6.so"}},
        "targets": {"/lib/aarch64-linux-gnu/libc.so.6": ["/lib/aarch64-linux-gnu/libc.so.6", "2" * 64]},
    }
    report: dict[str, Any] = {
        "schema": payload.SCHEMA,
        "architecture": "arm64",
        "result": "refused",
        "reasons": ["PayloadRefusal: no frozen exclusion applies; unresolved or missing dynamic dependencies"],
        "baseline": baseline,
        "exclusion": None,
        "retained": None,
    }
    report.update(overrides)
    return report


def _trimmed_report(raw: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    entry = proof.build_native_arm64_exclusion_from_observation(raw)
    retained: dict[str, Any] = {
        "entries": 4199,
        "digest": "3" * 64,
        "expected_digest": "3" * 64,
        "elf_count": 78,
        "elves": {},
        "unresolved": [],
        "imports": list(entry.baseline_imports),
        "lib_dynload": list(entry.baseline_imports),
        "targets": {"/lib/aarch64-linux-gnu/libc.so.6": ["/lib/aarch64-linux-gnu/libc.so.6", "2" * 64]},
        "owners": {"/lib/aarch64-linux-gnu/libc.so.6": "libc6:arm64"},
        "excluded_absent": True,
        "preserved": True,
    }
    report: dict[str, Any] = {
        "schema": payload.SCHEMA,
        "architecture": "arm64",
        "result": "trimmed",
        "reasons": [],
        "baseline": raw["baseline"],
        "exclusion": {
            **entry._asdict(),
            "missing": list(entry.missing),
            "baseline_imports": len(entry.baseline_imports),
            "reason": "unusable Tk bridge: Tcl/Tk libraries are absent from the base",
        },
        "retained": retained,
    }
    report.update(overrides)
    return report


def test_normalize_daemon_arch_accepts_arm64_and_refuses_cross_arch() -> None:
    assert proof.normalize_daemon_arch("aarch64") == "arm64"
    assert proof.normalize_daemon_arch("ARM64") == "arm64"
    with pytest.raises(proof.Python31216ProofError, match="never infer amd64"):
        proof.normalize_daemon_arch("x86_64")
    with pytest.raises(proof.Python31216ProofError, match="never infer amd64"):
        proof.normalize_daemon_arch("amd64")
    with pytest.raises(proof.Python31216ProofError, match="unsupported daemon architecture"):
        proof.normalize_daemon_arch("riscv64")


def test_validate_native_arm64_base_provenance_and_refusals() -> None:
    valid = proof.validate_native_arm64_base_provenance(
        daemon_arch="aarch64",
        reference=release.PYTHON_RELEASE_IMAGE,
        index_digest=payload.PYTHON_31216_INDEX,
        manifest_digest=payload.PYTHON_31216_ARM64_MANIFEST,
        config_digest=payload.PYTHON_31216_ARM64_CONFIG,
        image_id=payload.PYTHON_31216_ARM64_CONFIG,
        repo_digests=(f"python@{payload.PYTHON_31216_INDEX}",),
        image_os="linux",
        image_arch="arm64",
        pulled=False,
        rootfs_layers=proof.EXPECTED_ARM64_DIFF_IDS,
    )
    assert valid["daemon_arch"] == "arm64"
    assert valid["platform"] == "linux/arm64"
    assert valid["config_digest_verified"] is True
    assert valid["manifest_registry_observed"] is False and valid["pulled_by_test_image_manager"] is False
    assert "pulled" not in valid, "a manager without a pull never implies zero phase pulls"
    assert valid["retained_manifest_verified"] is True
    assert valid["rootfs_diff_ids_verified"] is True

    # Reject corrupted retained manifest bytes or wrong RootFS diff_ids
    with pytest.raises(proof.Python31216ProofError, match="arm64 manifest digest"):
        proof.validate_native_arm64_base_provenance(
            daemon_arch="arm64",
            reference=release.PYTHON_RELEASE_IMAGE,
            index_digest=payload.PYTHON_31216_INDEX,
            manifest_digest=payload.PYTHON_31216_ARM64_MANIFEST,
            config_digest=payload.PYTHON_31216_ARM64_CONFIG,
            image_id=payload.PYTHON_31216_ARM64_CONFIG,
            repo_digests=(f"python@{payload.PYTHON_31216_INDEX}",),
            image_os="linux",
            image_arch="arm64",
            pulled=False,
            retained_manifest_bytes=b"{}",
        )
    with pytest.raises(proof.Python31216ProofError, match="RootFS.Layers"):
        proof.validate_native_arm64_base_provenance(
            daemon_arch="arm64",
            reference=release.PYTHON_RELEASE_IMAGE,
            index_digest=payload.PYTHON_31216_INDEX,
            manifest_digest=payload.PYTHON_31216_ARM64_MANIFEST,
            config_digest=payload.PYTHON_31216_ARM64_CONFIG,
            image_id=payload.PYTHON_31216_ARM64_CONFIG,
            repo_digests=(f"python@{payload.PYTHON_31216_INDEX}",),
            image_os="linux",
            image_arch="arm64",
            pulled=False,
            rootfs_layers=("sha256:" + "0" * 64,),
        )

    # Reject manifest digest substituted for image_id / config_digest
    with pytest.raises(proof.Python31216ProofError, match="never the manifest or index digest"):
        proof.validate_native_arm64_base_provenance(
            daemon_arch="arm64",
            reference=release.PYTHON_RELEASE_IMAGE,
            index_digest=payload.PYTHON_31216_INDEX,
            manifest_digest=payload.PYTHON_31216_ARM64_MANIFEST,
            config_digest=payload.PYTHON_31216_ARM64_CONFIG,
            image_id=payload.PYTHON_31216_ARM64_MANIFEST,
            repo_digests=(f"python@{payload.PYTHON_31216_INDEX}",),
            image_os="linux",
            image_arch="arm64",
            pulled=False,
        )

    # Reject historical 3.12.15 index and config digests
    with pytest.raises(proof.Python31216ProofError, match="PYTHON_31216_INDEX"):
        proof.validate_native_arm64_base_provenance(
            daemon_arch="arm64",
            reference=release.PYTHON_RELEASE_IMAGE,
            index_digest=proof.HISTORICAL_31215_INDEX,
            manifest_digest=payload.PYTHON_31216_ARM64_MANIFEST,
            config_digest=payload.PYTHON_31216_ARM64_CONFIG,
            image_id=payload.PYTHON_31216_ARM64_CONFIG,
            repo_digests=(f"python@{proof.HISTORICAL_31215_INDEX}",),
            image_os="linux",
            image_arch="arm64",
            pulled=False,
        )
    with pytest.raises(proof.Python31216ProofError, match="arm64 config digest"):
        proof.validate_native_arm64_base_provenance(
            daemon_arch="arm64",
            reference=release.PYTHON_RELEASE_IMAGE,
            index_digest=payload.PYTHON_31216_INDEX,
            manifest_digest=payload.PYTHON_31216_ARM64_MANIFEST,
            config_digest=proof.HISTORICAL_31215_ARM64_CONFIG,
            image_id=proof.HISTORICAL_31215_ARM64_CONFIG,
            repo_digests=(f"python@{payload.PYTHON_31216_INDEX}",),
            image_os="linux",
            image_arch="arm64",
            pulled=False,
        )


def test_validate_runtime_cache_cap_and_container_cleanup() -> None:
    img_id = "sha256:" + "a" * 64
    res = proof.validate_runtime_cache_cap(
        selected_image_id=img_id,
        runtime_cache_ids=[img_id],
        operation_counts={"managed_test_runtime_image_build_count": 1, "unmanaged_build_count": 0},
        manager_outcome="built",
        materialization_recorded=True,
    )
    assert res["runtime_cache_count"] == 1 and res["managed_runtime_cache_build_count"] == 1
    assert res["manager_outcome"] == "built" and res["materialization_recorded"] is True
    with pytest.raises(proof.Python31216ProofError, match="exceeds cap 1"):
        proof.validate_runtime_cache_cap(
            selected_image_id=img_id,
            runtime_cache_ids=[img_id],
            operation_counts={"managed_test_runtime_image_build_count": 2},
        )
    with pytest.raises(proof.Python31216ProofError, match="forbidden Docker operation count"):
        proof.validate_runtime_cache_cap(
            selected_image_id=img_id,
            runtime_cache_ids=[img_id],
            operation_counts={"unmanaged_build_count": 1},
        )
    with pytest.raises(proof.Python31216ProofError, match="expected exactly 1"):
        proof.validate_runtime_cache_cap(selected_image_id=img_id, runtime_cache_ids=[img_id, "sha256:" + "b" * 64])
    with pytest.raises(proof.Python31216ProofError, match="unexpected ephemeral"):
        proof.validate_runtime_cache_cap(
            selected_image_id=img_id, runtime_cache_ids=[img_id], ephemeral_ids=["sha256:" + "c" * 64]
        )

    clean = proof.validate_container_cleanup(
        container_id="cid-1", cleanup_result="removed", final_presence="absent",
        engine_absent=True, baseline_verified=True,
    )
    assert clean["owned_containers_removed"] is True and clean["baseline_verified"] is True
    with pytest.raises(proof.Python31216ProofError, match="container cleanup incomplete"):
        proof.validate_container_cleanup(
            container_id="cid-1", cleanup_result="failed", final_presence="present",
            engine_absent=False, baseline_verified=True,
        )


def test_raw_and_trimmed_proof_validation_and_formatting() -> None:
    raw = _raw_report()
    entry = proof.build_native_arm64_exclusion_from_observation(raw)
    assert entry.python_index == payload.PYTHON_31216_INDEX
    assert entry.platform_manifest == payload.PYTHON_31216_ARM64_MANIFEST
    assert entry.python_config == payload.PYTHON_31216_ARM64_CONFIG

    trimmed = _trimmed_report(raw)
    summary = proof.validate_trimmed_arm64_proof_report(
        raw_report=raw,
        trimmed_report=trimmed,
        entry_delta=-1,
        modified_survivors=(),
    )
    assert summary["entry_delta"] == -1
    assert summary["matches_predicted_arm64_imports"] is True
    assert summary["excluded_absent"] is True and summary["preserved"] is True

    prov = proof.validate_native_arm64_base_provenance(
        daemon_arch="arm64",
        reference=release.PYTHON_RELEASE_IMAGE,
        index_digest=payload.PYTHON_31216_INDEX,
        manifest_digest=payload.PYTHON_31216_ARM64_MANIFEST,
        config_digest=payload.PYTHON_31216_ARM64_CONFIG,
        image_id=payload.PYTHON_31216_ARM64_CONFIG,
        repo_digests=(f"python@{payload.PYTHON_31216_INDEX}",),
        image_os="linux",
        image_arch="arm64",
        pulled=False,
    )
    cleanup_details = proof.validate_container_cleanup(
        container_id="cid-1", cleanup_result="removed", final_presence="absent",
        engine_absent=True, baseline_verified=True,
    )
    record = proof.build_native_proof_record(
        provenance=prov,
        operations_before=ZERO_OPERATIONS,
        operations_after=ZERO_OPERATIONS,
        trimmed_summary=summary,
        default_enrolled=False,
        cleanup_details=cleanup_details,
    )
    line = proof.format_native_proof_stdout(record)
    assert line.startswith(proof.PROOF_STDOUT_PREFIX)
    parsed = json.loads(line.removeprefix(proof.PROOF_STDOUT_PREFIX))
    assert parsed["schema"] == proof.PROOF_SCHEMA
    assert parsed["amd64_qualified"] is False
    assert parsed["matches_predicted_arm64_imports"] is True
    assert parsed["dependency_runtime_cache"]["qualification"] == "unexecuted"
    assert parsed["runtime_acceptance_claimed"] is False
    assert parsed["docker_operations"] == {"before_probe": ZERO_OPERATIONS, "after_probe": ZERO_OPERATIONS}
    prior = {**ZERO_OPERATIONS, "managed_test_runtime_image_build_count": 1}
    continued = proof.build_native_proof_record(
        provenance=prov, operations_before=prior, operations_after=prior,
        trimmed_summary=summary, default_enrolled=False, cleanup_details=cleanup_details)
    assert continued["docker_operations"] == {"before_probe": prior, "after_probe": prior}
    for bad in ({**ZERO_OPERATIONS, "managed_test_runtime_image_build_count": 1}, {}):
        with pytest.raises(proof.Python31216ProofError):
            proof.build_native_proof_record(
                provenance=prov, operations_before=ZERO_OPERATIONS, operations_after=bad,
                trimmed_summary=summary, default_enrolled=False, cleanup_details=cleanup_details)
    with pytest.raises(proof.Python31216ProofError, match="container cleanup not verified"):
        proof.build_native_proof_record(
            provenance=prov, operations_before=ZERO_OPERATIONS, operations_after=ZERO_OPERATIONS,
            trimmed_summary=summary, default_enrolled=False,
            cleanup_details={**cleanup_details, "baseline_verified": False})

    script = proof.build_inner_probe_script(b"SCHEMA = 'x'\n")
    assert proof.INNER_RAW_STDOUT_PREFIX in script and proof.INNER_STDOUT_PREFIX in script
    assert script.index(proof.INNER_RAW_STDOUT_PREFIX) < script.index("assert rc_no == 1")
    assert script.index(proof.INNER_STDOUT_PREFIX) < script.index("assert rc_tr == 0")


@pytest.mark.parametrize("change", [1, -1, True, None, -2])
def test_probe_delta_refuses_new_operations_and_invalid_counts(change: Any) -> None:
    baseline = {**ZERO_OPERATIONS, "managed_test_runtime_image_build_count": 1}
    changed = dict(baseline)
    changed["managed_test_runtime_image_build_count"] = 1 + change if type(change) is int else change
    with pytest.raises(proof.Python31216ProofError):
        proof.validate_zero_docker_operations(changed, baseline=baseline)


def test_probe_delta_refuses_missing_or_changed_boundary_fields() -> None:
    with pytest.raises(proof.Python31216ProofError, match="lacks operation fields"):
        proof.validate_zero_docker_operations(ZERO_OPERATIONS, baseline={})
    with pytest.raises(proof.Python31216ProofError, match="fields changed"):
        proof.validate_zero_docker_operations({**ZERO_OPERATIONS, "unexpected_count": 0}, baseline=ZERO_OPERATIONS)


def test_raw_and_trimmed_refusal_branches() -> None:
    raw = _raw_report()
    trimmed = _trimmed_report(raw)

    with pytest.raises(proof.Python31216ProofError, match="entry count delta -1"):
        proof.validate_trimmed_arm64_proof_report(
            raw_report=raw, trimmed_report=trimmed, entry_delta=-2, modified_survivors=()
        )
    with pytest.raises(proof.Python31216ProofError, match="surviving /usr/local entries drifted"):
        proof.validate_trimmed_arm64_proof_report(
            raw_report=raw, trimmed_report=trimmed, entry_delta=-1, modified_survivors=("/usr/local/bin/python3",)
        )
    bad_raw = _raw_report()
    bad_raw["baseline"] = {**bad_raw["baseline"], "failed": {"_tkinter": {}, "math": {}}}
    with pytest.raises(proof.Python31216ProofError, match="only \\['_tkinter'\\]"):
        proof.build_native_arm64_exclusion_from_observation(bad_raw)


@pytest.mark.parametrize("field", [
    "product_or_build_profile_build_count", "managed_test_runtime_image_build_count",
    "managed_system_candidate_image_build_count", "managed_runtime_build_intermediate_created_count",
    "managed_external_base_pull_count", "unmanaged_build_count", "unmanaged_pull_count",
])
def test_zero_operation_guard_refuses_any_build_materialization_or_pull(field: str) -> None:
    assert proof.validate_zero_docker_operations({**ZERO_OPERATIONS, "new_inventory_field": 0}) == {
        **ZERO_OPERATIONS, "new_inventory_field": 0}
    with pytest.raises(proof.Python31216ProofError, match="requires zero Docker build/pull operations"):
        proof.validate_zero_docker_operations({**ZERO_OPERATIONS, field: 1})
    with pytest.raises(proof.Python31216ProofError, match="lacks operation fields"):
        proof.validate_zero_docker_operations({k: v for k, v in ZERO_OPERATIONS.items() if k != field})
    for bad in (True, "0", -1, 0.0):
        with pytest.raises(proof.Python31216ProofError, match="not a non-negative integer"):
            proof.validate_zero_docker_operations({**ZERO_OPERATIONS, field: bad})


def test_in_run_pull_refuses_and_raw_lines_are_reprefixed() -> None:
    adopted_before = payload.ARM64_31216_NATIVE_BASELINE_IMPORTS
    with pytest.raises(proof.Python31216ProofError, match="an in-run pull is refused"):
        proof.validate_native_arm64_base_provenance(
            daemon_arch="arm64", reference=release.PYTHON_RELEASE_IMAGE, index_digest=payload.PYTHON_31216_INDEX,
            manifest_digest=payload.PYTHON_31216_ARM64_MANIFEST, config_digest=payload.PYTHON_31216_ARM64_CONFIG,
            image_id=payload.PYTHON_31216_ARM64_CONFIG, repo_digests=(f"python@{payload.PYTHON_31216_INDEX}",),
            image_os="linux", image_arch="arm64", pulled=True)
    stdout = f"noise\n{proof.INNER_RAW_STDOUT_PREFIX}{{\"a\": 1}}\n{proof.INNER_STDOUT_PREFIX}{{}}\n"
    assert proof.raw_observation_lines(stdout) == [proof.RAW_OBSERVATION_STDOUT_PREFIX + '{"a": 1}']
    assert proof.raw_observation_lines("") == []
    assert proof.ARM64_31216_PREDICTED_IMPORTS_AWAITING_NATIVE_PROOF == historical.ARM64_BASELINE_IMPORTS
    assert payload.ARM64_31216_NATIVE_BASELINE_IMPORTS is adopted_before, "helpers never enroll predictions"
