"""Unit tests for hosted D12 canonical reports loading, counter projection, and validation."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[6]
for candidate_path in (ROOT, ROOT / "tools", ROOT / "src/main/python", ROOT / "src/test/support/python"):
    if str(candidate_path) not in sys.path:
        sys.path.insert(0, str(candidate_path))

import d12_libpq_runtime_probe
from common_lore_index.runtime import python_payload as payload
from common_lore_index.runtime.release import (
    GO_RELEASE_IMAGE, POSTGRES_RELEASE_IMAGE, PRODUCT_MINIMUM_LIBPQ_VERSION, PYTHON_RELEASE_IMAGE,
)
from repomap_test_support import d12_core_image
from src.test.unit.python.tools.ci.d12_hosted_fixtures import make_positive_amd64_closure
import test_sandbox_images

import ci.d12_hosted_reports as reports_mod
from ci.d12_hosted_reports import (
    APPLICATION_BUILD_COUNT_KEYS, CLEANUP_TOP_LEVEL_KEYS, EXPLORATION_TOP_LEVEL_KEYS,
    FREEZE_TOP_LEVEL_KEYS, RESIDUE_ZERO_KEYS, VERIFIED_AMD64_BASE_METADATA, load_safe_json_report,
    project_canonical_boundary_counts, validate_canonical_cleanup_report,
    validate_canonical_exploration_report, validate_canonical_freeze_report,
)

ADMITTED_AMD64 = payload.build_31216_exclusion("amd64", payload.AMD64_31216_NATIVE_BASELINE_IMPORTS)
FOREIGN_31215_AMD64 = ADMITTED_AMD64._replace(
    python_config="sha256:a33c10a97f11005523814c6eee013986119fe41f3122f444518117536675c8e1")
REAL_HELPER_SHA256 = hashlib.sha256((ROOT / "tools/native_apt_prerequisites.py").read_bytes()).hexdigest()
EXP_KW: dict[str, Any] = {
    "expected_source_sha256": "1" * 64,
    "expected_recipe_sha256": "2" * 64,
    "expected_dockerfile_sha256": "3" * 64,
    "expected_context_file_count": 694,
}


def make_freeze_report() -> dict[str, Any]:
    return {
        "admission": {
            "node_id": d12_core_image.NODE_ID,
            "platform": "linux/amd64",
            "source_sha256": "1" * 64,
            "recipe_sha256": "2" * 64,
            "dockerfile_sha256": "3" * 64,
            "context_file_count": 694,
        },
        "availability": {
            "platform": "linux/amd64",
            "execution": "native",
            "builder_platforms": ["linux/amd64", "linux/arm64"],
        },
        "bases": {
            POSTGRES_RELEASE_IMAGE: {
                "id": VERIFIED_AMD64_BASE_METADATA["postgres"]["config"],
                "platform": "linux/amd64",
                "config_digest_verified": True,
            },
            PYTHON_RELEASE_IMAGE: {
                "id": VERIFIED_AMD64_BASE_METADATA["python"]["config"],
                "platform": "linux/amd64",
                "config_digest_verified": False,
            },
            GO_RELEASE_IMAGE: {
                "id": VERIFIED_AMD64_BASE_METADATA["go"]["config"],
                "platform": "linux/amd64",
                "config_digest_verified": False,
            },
        },
        "budget": {k: 0 for k in (*APPLICATION_BUILD_COUNT_KEYS, *RESIDUE_ZERO_KEYS)},
        "labels": {
            "org.repomap.d12.candidate": "true",
            "org.repomap.d12.platform": "linux/amd64",
            "org.repomap.d12.recipe_sha256": "2" * 64,
            "org.repomap.d12.source_sha256": "1" * 64,
            "org.repomap.test.resource.run_id": "test-run-123",
        },
        "tag": "repomap-d12-core-candidate:test-run-123-amd64",
    }


def make_cleanup_report() -> dict[str, Any]:
    return {
        "candidate_image_id": None,
        "containers": "baseline_verified",
        "server": "removed",
        "primary": None,
        "zero_build": {k: 0 for k in APPLICATION_BUILD_COUNT_KEYS},
        "budget": {k: 0 for k in (*APPLICATION_BUILD_COUNT_KEYS, *RESIDUE_ZERO_KEYS)},
    }


def make_exploration_report(*, refused: bool = False, api: int = 180006) -> dict[str, Any]:
    ver = "18.6-1.pgdg13+2"
    pgdg_src = "/etc/apt/sources.list.d/pgdg.sources"
    pgdg_key = "/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg"
    lib_path = "/usr/lib/x86_64-linux-gnu/libpq.so.5.18"
    lib_sha = "7" * 64
    pkg_pq = {"name": "libpq5", "version": ver, "architecture": "amd64", "sha256": "4" * 64}
    pkg_dev = {"name": "libpq-dev", "version": ver, "architecture": "amd64", "sha256": "6" * 64}
    report: dict[str, Any] = {
        "mode": "exploration",
        "daemon": "disposable inner daemon, destroyed at sandbox exit",
        "build_readiness": "NOT ESTABLISHED",
        "p3": "inputs only",
        "host_forecast_substituted": False,
        "admission": {
            "node_id": d12_core_image.NODE_ID,
            "platform": "linux/amd64",
            "source_sha256": "1" * 64,
            "recipe_sha256": "2" * 64,
            "dockerfile_sha256": "3" * 64,
            "context_file_count": 694,
        },
        "bindings": {"run_id": "test-run-123", "sdk_image": "unobserved in the sandbox"},
        "availability": {
            "platform": "linux/amd64",
            "execution": "native",
            "builder_platforms": ["linux/amd64"],
        },
        "bases": make_freeze_report()["bases"],
        "result": "refused" if refused else "observed",
        "refusals": ["closure: unsupported baseline"] if refused else [],
        "steps": {
            "engine": {
                "classification": {"linux/arm64": "non_executable", "linux/amd64": "native"},
                "architecture": "x86_64",
                "buildkit": "v0.17.0",
                "builder_platforms": ["linux/amd64"],
            },
            "identity": {
                "postgres": VERIFIED_AMD64_BASE_METADATA["postgres"]["config"],
                "postgres_sealed": True,
                "python": VERIFIED_AMD64_BASE_METADATA["python"]["config"],
                "go": VERIFIED_AMD64_BASE_METADATA["go"]["config"],
                "go_expected": VERIFIED_AMD64_BASE_METADATA["go"]["config"],
                "go_run": False,
            },
            "capacity": {"free_bytes": 1000000, "role": "forecast only; no increase"},
        },
    }
    if not refused:
        report["steps"]["libpq5_version"] = ver
        report["steps"]["trust"] = {
            "sources": {pgdg_src: {"sha256": "8" * 64, "signed_by": [pgdg_key]}},
            "keyrings": {pgdg_key: "9" * 64},
            "fingerprints": {"primary": ["A" * 40], "subkeys": []},
            "pgdg_source": pgdg_src,
            "pgdg_keyring": pgdg_key,
        }
        report["steps"]["closure"] = {**make_positive_amd64_closure(ver), "packages": [["libpq5", ver, "amd64"]]}
        report["steps"]["builder"] = {
            "native": "amd64",
            "preexisting_rows": 120,
            "packages": [pkg_pq, pkg_dev],
            "trusted_targets": [],
        }
        report["steps"]["final_closure"] = {
            "native": "amd64",
            "preexisting_rows": 140,
            "packages": [pkg_pq],
            "trusted_targets": [],
        }
        srv = {"files": [{"role": "libpq", "owner": "libpq5", "resolved": lib_path, "sha256": lib_sha}]}
        exp_in, hashes = d12_libpq_runtime_probe.binding(
            report["steps"], srv, "linux/amd64", "test-run-123"
        )
        report["steps"]["libpq_runtime"] = d12_libpq_runtime_probe.record(
            exp_in,
            hashes,
            api=api,
            machine="x86_64",
            selected=[[pkg_pq["name"], pkg_pq["version"], pkg_pq["architecture"], pkg_pq["sha256"]]],
            digests=("b" * 64, "c" * 64),
        )
        report["steps"]["candidate"] = {
            "architecture": "amd64",
            "valid": True,
            "written_to_source": False,
            "libpq_version": api,
            "package_forecast": api,
            "libpq_label": "runtime PQlibVersion; forecast is equality only",
            "manifest": {
                "postgres_config_digest": VERIFIED_AMD64_BASE_METADATA["postgres"]["config"],
                "pgdg_source": [pgdg_src, "8" * 64],
                "pgdg_keyring": [pgdg_key, "9" * 64],
                "key_fingerprints": ["A" * 40],
                "libpq_path": lib_path,
                "libpq_sha256": lib_sha,
                "libpq5_version": ver,
                "builder": [
                    ["libpq5", ver, "amd64", "4" * 64],
                    ["libpq-dev", ver, "amd64", "6" * 64],
                ],
                "closure": [["libpq5", ver, "amd64", "4" * 64]],
                "lib_dynload": list(report["steps"]["closure"]["imports"]),
            },
        }
    return report


def test_schema_constants_and_shared_helper_owner_proof() -> None:
    assert "tag" in FREEZE_TOP_LEVEL_KEYS
    assert "build_readiness" in EXPLORATION_TOP_LEVEL_KEYS
    assert "zero_build" in CLEANUP_TOP_LEVEL_KEYS
    assert len(APPLICATION_BUILD_COUNT_KEYS) == 4
    assert len(RESIDUE_ZERO_KEYS) == 6
    assert set(VERIFIED_AMD64_BASE_METADATA.keys()) == {"go", "python", "postgres"}
    assert getattr(reports_mod, "MAX_SAFE_JSON_REPORT_BYTES", None) == 8 * 1024 * 1024

    canonical_helper = (ROOT / "tools/native_apt_prerequisites.py").resolve()
    probe_helper = Path(str(d12_libpq_runtime_probe.apt.__file__)).resolve()
    sandbox_helper = test_sandbox_images.SANDBOX_CONTEXT_SOURCES["apt_prerequisites.py"].resolve()
    assert probe_helper == canonical_helper
    assert sandbox_helper == canonical_helper


def test_load_safe_json_report_outcomes(tmp_path: Path) -> None:
    clean, prov, err = load_safe_json_report(tmp_path / "missing.json")
    assert clean is None and prov["status"] == "missing" and err is not None

    bad = tmp_path / "invalid.json"
    bad.write_text("{not-json", encoding="utf-8")
    clean, prov, err = load_safe_json_report(bad)
    assert clean is None and prov["status"] == "malformed_json" and err is not None

    non_utf8 = tmp_path / "non_utf8.json"
    raw_bytes = b"\xff\xfe\xfd\x80"
    non_utf8.write_bytes(raw_bytes)
    clean, prov, err = load_safe_json_report(non_utf8)
    assert clean is None and prov["status"] == "decode_error" and err is not None
    assert prov["byte_length"] == len(raw_bytes)
    assert prov["sha256"] == hashlib.sha256(raw_bytes).hexdigest()

    oversize = tmp_path / "oversize.json"
    oversize.write_bytes(b"{" + b"x" * 100 + b"}")
    clean, prov, err = load_safe_json_report(oversize, max_bytes=32)
    assert clean is None and prov["status"] == "oversize" and err is not None
    assert prov["byte_length"] == 102 and prov["sha256"] is None


def test_project_canonical_boundary_counts_partial_and_complete() -> None:
    counts, violations = project_canonical_boundary_counts(None, None)
    assert all(v is None for v in counts.values())
    assert len(violations) == 3

    f_rep, c_rep = make_freeze_report(), make_cleanup_report()
    partial_counts, partial_violations = project_canonical_boundary_counts(f_rep, None)
    assert all(v is None for v in partial_counts.values())
    assert len(partial_violations) == 2

    counts, violations = project_canonical_boundary_counts(f_rep, c_rep)
    assert violations == []
    assert counts["application_builds"] == 0
    assert counts["application_candidate_builds"] == 0
    assert all(counts[k] == 0 for k in APPLICATION_BUILD_COUNT_KEYS)

    f_nonzero = make_freeze_report()
    f_nonzero["budget"]["product_or_build_profile_build_count"] = 1
    nz_counts, nz_violations = project_canonical_boundary_counts(f_nonzero, None)
    assert nz_counts["product_or_build_profile_build_count"] == 1
    assert nz_counts["application_builds"] == 1
    assert any("must be strict 0" in v for v in nz_violations)

    c_missing_key = make_cleanup_report()
    del c_missing_key["zero_build"]["unmanaged_build_count"]
    mk_counts, mk_violations = project_canonical_boundary_counts(f_rep, c_missing_key)
    assert mk_counts["unmanaged_build_count"] is None
    assert mk_counts["application_builds"] is None
    assert any("missing required counter key" in v for v in mk_violations)


def test_validate_canonical_freeze_and_cleanup_reports() -> None:
    rep = make_freeze_report()
    assert validate_canonical_freeze_report(rep, **EXP_KW) == []
    rep["tag"] = ""
    rep["admission"]["context_file_count"] = 100
    rep["bases"][POSTGRES_RELEASE_IMAGE]["config_digest_verified"] = False
    rep["labels"]["org.repomap.d12.candidate"] = "false"
    assert len(validate_canonical_freeze_report(rep, **EXP_KW)) >= 4

    c_rep = make_cleanup_report()
    assert validate_canonical_cleanup_report(c_rep) == []
    c_rep["candidate_image_id"] = "sha256:d12candidate"
    c_rep["containers"] = "modified"
    c_rep["server"] = "running"
    c_rep["error"] = "cleanup failure"
    c_rep["zero_build"]["unmanaged_build_count"] = 1
    c_rep["budget"]["new_unattributed_images"] = 2
    assert len(validate_canonical_cleanup_report(c_rep)) >= 6


def test_validate_canonical_exploration_report_refusal_prefixes_and_unknown_stage() -> None:
    rep = make_exploration_report(refused=True)
    assert validate_canonical_exploration_report(
        rep, **EXP_KW, expected_helper_sha256=REAL_HELPER_SHA256, require_positive_observation=False
    ) == []

    final_ref = make_exploration_report(refused=False)
    final_ref["result"] = "refused"
    final_ref["refusals"] = ["final: simulated dpkg dependency mismatch"]
    final_ref["steps"]["final_closure"] = None
    del final_ref["steps"]["candidate"]
    assert validate_canonical_exploration_report(
        final_ref, **EXP_KW, expected_helper_sha256=REAL_HELPER_SHA256, require_positive_observation=False
    ) == []

    final_ref["steps"]["final_closure"] = {"native": "amd64"}
    v_final_bad = validate_canonical_exploration_report(
        final_ref, **EXP_KW, expected_helper_sha256=REAL_HELPER_SHA256, require_positive_observation=False
    )
    assert any("premature continuation after final refusal" in v for v in v_final_bad)

    unknown_ref = make_exploration_report(refused=True)
    unknown_ref["refusals"] = ["PreflightRefusal: engine or candidate failure"]
    v_unknown = validate_canonical_exploration_report(
        unknown_ref, **EXP_KW, expected_helper_sha256=REAL_HELPER_SHA256, require_positive_observation=False
    )
    assert any("ambiguous or unknown refusal stage" in v for v in v_unknown)


def test_validate_canonical_exploration_report_positive_real_consume_and_independent_manifest(monkeypatch: Any) -> None:
    pos = make_exploration_report(refused=False)
    assert payload.PYTHON_PAYLOAD_EXCLUSIONS["amd64"] == ADMITTED_AMD64, "ADR 0103 admitted default, not injected"
    assert pos["steps"]["libpq_runtime"]["verified"] == "host-rechecked builder result"
    assert pos["steps"]["libpq_runtime"]["helper_sha256"] == REAL_HELPER_SHA256
    assert validate_canonical_exploration_report(
        pos, **EXP_KW, expected_helper_sha256=REAL_HELPER_SHA256, require_positive_observation=True
    ) == []

    tampered_manifest = make_exploration_report(refused=False)
    tampered_manifest["steps"]["candidate"]["manifest"]["libpq_sha256"] = "e" * 64
    v_tampered = validate_canonical_exploration_report(
        tampered_manifest, **EXP_KW, expected_helper_sha256=REAL_HELPER_SHA256, require_positive_observation=True
    )
    assert any("libpq_runtime probe validation failed" in v for v in v_tampered)

    low_api = make_exploration_report(refused=False, api=PRODUCT_MINIMUM_LIBPQ_VERSION - 1)
    low_api["host_forecast_substituted"] = True
    low_api["steps"]["candidate"]["written_to_source"] = True
    low_api["steps"]["closure"]["elf_count"] = 0
    v_pos = validate_canonical_exploration_report(
        low_api, **EXP_KW, expected_helper_sha256=REAL_HELPER_SHA256, require_positive_observation=True
    )
    assert any("host_forecast_substituted" in v for v in v_pos)
    assert any("candidate metadata flags" in v for v in v_pos)
    assert any("closure invalid" in v for v in v_pos)
    assert any(f"below {PRODUCT_MINIMUM_LIBPQ_VERSION}" in v for v in v_pos)

    held = {k: v for k, v in payload.PYTHON_PAYLOAD_EXCLUSIONS.items() if k != "amd64"}
    for doubled in (held, {**held, "amd64": FOREIGN_31215_AMD64}):  # isolated held and foreign source maps
        monkeypatch.setattr(payload, "PYTHON_PAYLOAD_EXCLUSIONS", doubled)
        assert any("invalid trim contract or config" in v for v in validate_canonical_exploration_report(
            pos, **EXP_KW, expected_helper_sha256=REAL_HELPER_SHA256, require_positive_observation=True))


def test_validate_canonical_exploration_report_strict_amd64_trim_and_closure_mutations() -> None:
    amd = payload.PYTHON_PAYLOAD_EXCLUSIONS["amd64"]
    assert amd == ADMITTED_AMD64, "ADR 0103 admitted default, not injected"
    py_meta = VERIFIED_AMD64_BASE_METADATA["python"]
    assert (amd.python_index, amd.platform_manifest, amd.python_config) == (
        py_meta["index"], py_meta["manifest"], py_meta["config"])

    clean_legacy = make_exploration_report(refused=False)
    clean_legacy["steps"]["closure"] = {
        "unresolved": [], "baseline_failed": [], "elf_count": 42, "retained": {"preserved": True, "unresolved": []},
        "imports": list(amd.baseline_imports), "packages": [["libpq5", "18.6-1.pgdg13+2", "amd64"]],
    }
    srv = {"files": [{"role": "libpq", "owner": "libpq5", "resolved": "/usr/lib/x86_64-linux-gnu/libpq.so.5.18",
                      "sha256": "7" * 64}]}
    exp_in, hashes = d12_libpq_runtime_probe.binding(clean_legacy["steps"], srv, "linux/amd64", "test-run-123")
    clean_legacy["steps"]["libpq_runtime"] = d12_libpq_runtime_probe.record(
        exp_in, hashes, api=180006, machine="x86_64",
        selected=[["libpq5", "18.6-1.pgdg13+2", "amd64", "4" * 64]], digests=("b" * 64, "c" * 64))
    assert validate_canonical_exploration_report(
        clean_legacy, **EXP_KW, expected_helper_sha256=REAL_HELPER_SHA256, require_positive_observation=True) == []

    for mutate in (
        lambda cl: cl.update(contract=None),
        lambda cl: cl["contract"].update(exclusion_applies=False),
        lambda cl: cl["contract"].update(python_config="sha256:" + "0" * 64),
        lambda cl: cl["contract"].update(program_sha256="0" * 64),
        lambda cl: cl.update(baseline_unresolved=sorted(cl["baseline_unresolved"])),
        lambda cl: cl["retained"].update(excluded_absent=False),
        lambda cl: cl["retained"].update(expected_digest="f" * 64),
        lambda cl: cl.update(elf_count=82),
        lambda cl: cl.update(baseline={}),
    ):
        rep = make_exploration_report(refused=False)
        mutate(rep["steps"]["closure"])
        v = validate_canonical_exploration_report(
            rep, **EXP_KW, expected_helper_sha256=REAL_HELPER_SHA256, require_positive_observation=True)
        assert any("closure invalid" in item for item in v), v
