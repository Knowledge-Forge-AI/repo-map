"""Pure evidence validation for hosted native D12 qualification and early system hold."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
import sys
from typing import Any, TypeGuard

_ROOT = Path(__file__).resolve().parents[2]
for _rel in ("", "src/main/python", "tools", "src/test/support/python"):
    _p = str((_ROOT / _rel).resolve())
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ci.d12_hosted_reports import (
    APPLICATION_BUILD_COUNT_KEYS,
    project_canonical_boundary_counts,
    validate_canonical_cleanup_report,
    validate_canonical_exploration_report,
    validate_canonical_freeze_report,
)

SEALED_EVIDENCE_SCHEMA = "repomap-d12-hosted-sealed-evidence-v1"
SYSTEM_HOLD_REFUSAL_SCHEMA = "repomap-d12-system-hold-refusal-v1"
EXPECTED_CANDIDATE_SCHEMA = "repomap-d12-hosted-candidate-v1"
SDK_BUILD_INTENT_SCHEMA = "repomap-d12-sdk-build-intent-v1"

EXPECTED_PLATFORM = "linux/amd64"
EXPECTED_HOST_ARCH = "x86_64"
EXPECTED_RUNNER_ARCH = "X64"
EXPECTED_RUNNER_OS = "Linux"
EXPECTED_SDK_IMAGE_TAG = "repomap-test-sandbox:py313-go125-docker294-v1"
EXPECTED_SDK_DOCKERFILE_SHA256 = "f8a8be96ac78ff32b8f2b4f6372f3d9203750a56f75ff49e0af722f5f75e3786"
EXPECTED_SDK_HELPER_SHA256 = "df616a151d062b4ade001bbd029007b2f414aa22422de63c520895663b850c5f"
ALL_APPLICATION_BUILD_KEYS: tuple[str, ...] = (
    "application_builds",
    "application_candidate_builds",
    *APPLICATION_BUILD_COUNT_KEYS,
)

_HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_COMMIT_KEYS = ("commit", "commit_sha", "candidate_sha", "head_sha", "base_sha")
_REDACT_PATTERNS = ("/" + "Users/", "/home/", "PRIVATE_KEY", "ghp_")


class HostedD12EvidenceError(ValueError):
    """Raised when hosted D12 candidate or evidence records violate contract bounds."""


def _is_strict_int(val: object) -> TypeGuard[int]:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_hex(val: object, length: int) -> bool:
    if not isinstance(val, str) or len(val) != length:
        return False
    return (_HEX_40_RE if length == 40 else _HEX_64_RE).match(val) is not None if length in (40, 64) else False


def _is_empty_res(m: Mapping[str, object]) -> bool:
    return all(
        m.get(f"{k}_added") == [] and m.get(f"{k}_removed", []) == []
        for k in ("containers", "images", "volumes", "networks")
    )


def validate_expected_candidate_record(record: object) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise HostedD12EvidenceError("candidate record must be a mapping")
    if any("commit" in str(k) or str(k) in _FORBIDDEN_COMMIT_KEYS for k in record):
        raise HostedD12EvidenceError("self-referential commit field forbidden in expected candidate record")
    if record.get("schema") != EXPECTED_CANDIDATE_SCHEMA or record.get("platform") != EXPECTED_PLATFORM:
        raise HostedD12EvidenceError("invalid schema or platform")

    d12_ctx, sdk = record.get("d12_context"), record.get("sdk_sandbox")
    if not isinstance(d12_ctx, Mapping) or not isinstance(sdk, Mapping):
        raise HostedD12EvidenceError("missing or invalid d12_context or sdk_sandbox")

    source_sha = d12_ctx.get("source_sha256")
    recipe_sha = d12_ctx.get("recipe_sha256")
    dockerfile_sha = d12_ctx.get("dockerfile_sha256")
    for name, val in (
        ("source_sha256", source_sha),
        ("recipe_sha256", recipe_sha),
        ("dockerfile_sha256", dockerfile_sha),
    ):
        if not _is_hex(val, 64):
            raise HostedD12EvidenceError(f"invalid {name}: must be 64-hex lowercase")

    file_count = d12_ctx.get("context_file_count")
    if not _is_strict_int(file_count) or file_count <= 0:
        raise HostedD12EvidenceError("invalid context_file_count")

    if (
        sdk.get("image_tag") != EXPECTED_SDK_IMAGE_TAG
        or sdk.get("sdk_dockerfile_sha256") != EXPECTED_SDK_DOCKERFILE_SHA256
        or sdk.get("sdk_helper_sha256") != EXPECTED_SDK_HELPER_SHA256
        or not _is_hex(sdk.get("sdk_recipe_sha256"), 64)
    ):
        raise HostedD12EvidenceError("sdk_sandbox metadata mismatch")

    digests = [
        source_sha, recipe_sha, dockerfile_sha,
        sdk.get("sdk_dockerfile_sha256"), sdk.get("sdk_helper_sha256"), sdk.get("sdk_recipe_sha256"),
    ]
    if len(set(digests)) != len(digests):
        raise HostedD12EvidenceError("hash domains must be distinct")

    return {**dict(record), "d12_context": dict(d12_ctx), "sdk_sandbox": dict(sdk)}


def _validate_sdk_materialization(sdk_mat: object, expected_sdk_recipe: str) -> list[str]:
    if not isinstance(sdk_mat, Mapping):
        return ["sdk_materialization missing or invalid"]
    violations: list[str] = []
    att = sdk_mat.get("sdk_build_attempts")
    if not _is_strict_int(att) or att not in (0, 1):
        violations.append("sdk_materialization sdk_build_attempts must be strict int 0 or 1")
    elif att == 0:
        if (
            sdk_mat.get("intent_recorded_before_build") is not False
            or sdk_mat.get("intent_receipt_sha256") is not None
            or sdk_mat.get("sdk_cache_cold_built") is not False
        ):
            violations.append("sdk_materialization warm cache hit intent fields invalid")
    else:
        if sdk_mat.get("intent_recorded_before_build") is not True:
            violations.append("sdk_materialization intent_recorded_before_build must be True")
        if not _is_hex(sdk_mat.get("intent_receipt_sha256"), 64):
            violations.append("sdk_materialization intent_receipt_sha256 must be 64-hex")
        if sdk_mat.get("sdk_cache_cold_built") is not True:
            violations.append("sdk_materialization sdk_cache_cold_built must be True for cold build")
    sdk_img_id = sdk_mat.get("sdk_image_id")
    if sdk_img_id is None or not (
        isinstance(sdk_img_id, str) and sdk_img_id.startswith("sha256:") and _is_hex(sdk_img_id[7:], 64)
    ):
        violations.append("sdk_materialization sdk_image_id must be exact sha256:<64-hex>")
    if (sdk_arch := sdk_mat.get("sdk_architecture")) != "amd64":
        violations.append(f"sdk_materialization sdk_architecture must be 'amd64', got {sdk_arch!r}")
    sdk_rec = sdk_mat.get("sdk_recipe_sha256")
    if not _is_hex(sdk_rec, 64) or (expected_sdk_recipe and sdk_rec != expected_sdk_recipe):
        violations.append("sdk_materialization sdk_recipe_sha256 invalid or mismatch")
    if sdk_mat.get("whole_job_image_parity_claimed") is not False:
        violations.append("sdk_materialization whole_job_image_parity_claimed must be False")
    added, removed = sdk_mat.get("added_sdk_images"), sdk_mat.get("removed_sdk_images")
    if not isinstance(added, list) or not all(isinstance(x, str) for x in added):
        violations.append("sdk_materialization added_sdk_images must be list[str]")
    if not isinstance(removed, list) or not all(isinstance(x, str) for x in removed):
        violations.append("sdk_materialization removed_sdk_images must be list[str]")
    entry_b, post_b = sdk_mat.get("entry_baseline"), sdk_mat.get("post_sdk_baseline")
    if isinstance(entry_b, Mapping) and isinstance(post_b, Mapping):
        e_imgs, p_imgs = entry_b.get("images"), post_b.get("images")
        if isinstance(e_imgs, list) and isinstance(p_imgs, list):
            if added != sorted(set(p_imgs) - set(e_imgs)):
                violations.append("sdk_materialization added_sdk_images mismatch with baselines")
            if removed != sorted(set(e_imgs) - set(p_imgs)):
                violations.append("sdk_materialization removed_sdk_images mismatch with baselines")
    post_clean = sdk_mat.get("post_sdk_cleanup")
    if (
        not isinstance(post_clean, Mapping)
        or not _is_empty_res(post_clean)
        or post_clean.get("clean_against_post_sdk_baseline") is not True
    ):
        violations.append("sdk_materialization post_sdk_cleanup detected residue against baseline")
    return violations


def validate_sealed_d12_evidence(
    evidence: object,
    *,
    require_positive_qualification: bool = False,
) -> list[str]:
    violations: list[str] = []
    if not isinstance(evidence, Mapping):
        return ["sealed evidence must be a mapping"]

    for fld, exp in (("schema", SEALED_EVIDENCE_SCHEMA), ("platform", EXPECTED_PLATFORM)):
        if evidence.get(fld) != exp:
            violations.append(f"invalid {fld}: {evidence.get(fld)}")
    if evidence.get("result") not in {"passed", "refused", "failed"}:
        violations.append(f"invalid result: {evidence.get('result')}")
    if not isinstance(evidence.get("qualified"), bool):
        violations.append("qualified must be a boolean")
    if not _is_strict_int(evidence.get("runner_exit_code")):
        violations.append("runner_exit_code must be a strict integer")

    for list_fld in ("seal_errors", "validation_violations"):
        raw_list = evidence.get(list_fld)
        if not isinstance(raw_list, list) or not all(
            isinstance(item, str) and bool(item.strip()) for item in raw_list
        ):
            violations.append(f"{list_fld} must be a list of non-empty strings")
        elif raw_list:
            violations.append(f"{list_fld} must be empty for valid sealed evidence, got {raw_list!r}")

    pr = evidence.get("pr_binding")
    if not isinstance(pr, Mapping):
        violations.append("pr_binding missing or invalid")
    else:
        if pr.get("event_name") != "pull_request":
            violations.append(f"invalid event_name: {pr.get('event_name')}")
        if not isinstance(pr.get("run_id"), str) or not pr.get("run_id"):
            violations.append("invalid run_id")
        run_attempt = pr.get("run_attempt")
        if not _is_strict_int(run_attempt) or run_attempt != 1:
            violations.append(f"invalid pr_binding run_attempt: {run_attempt}, must be 1")
        repo, base_repo, head_repo = pr.get("repository"), pr.get("base_repo"), pr.get("head_repo")
        if not isinstance(repo, str) or not repo:
            violations.append("invalid pr_binding repository")
        if base_repo != repo or head_repo != repo:
            violations.append(f"pr_binding repo mismatch: head_repo={head_repo}, repository={repo}")
        if pr.get("base_ref") != "main":
            violations.append(f"pr_binding base_ref must be 'main', got {pr.get('base_ref')}")
        if pr.get("head_ref") != "staging":
            violations.append(f"pr_binding head_ref must be 'staging', got {pr.get('head_ref')}")
        cand, gh, hc = pr.get("candidate_sha"), pr.get("github_sha"), pr.get("head_commit_sha")
        if not (_is_hex(cand, 40) and _is_hex(gh, 40) and _is_hex(hc, 40) and cand == gh == hc):
            violations.append("pr_binding candidate_sha mismatch with github_sha / head_commit_sha")
        bp, ebp = pr.get("candidate_base_parent"), pr.get("event_base_sha")
        if not (_is_hex(bp, 40) and _is_hex(ebp, 40) and bp == ebp):
            violations.append("pr_binding candidate_base_parent mismatch with event_base_sha")
        hp, ehp = pr.get("candidate_head_parent"), pr.get("event_head_sha")
        if not (_is_hex(hp, 40) and _is_hex(ehp, 40) and hp == ehp):
            violations.append("pr_binding candidate_head_parent mismatch with event_head_sha")
        if not _is_hex(pr.get("candidate_tree"), 40):
            violations.append("pr_binding candidate_tree must be 40-hex")

    id_bind = evidence.get("identity_binding")
    d12_ctx: Mapping[str, object] = {}
    expected_sdk_recipe = ""
    if not isinstance(id_bind, Mapping):
        violations.append("identity_binding missing or invalid")
    else:
        if not _is_hex(id_bind.get("expected_candidate_sha256"), 64):
            violations.append("invalid identity_binding expected_candidate_sha256")
        raw_d12, raw_sdk = id_bind.get("d12_context"), id_bind.get("sdk_sandbox")
        if not isinstance(raw_d12, Mapping) or raw_d12.get("matches_expected") is not True:
            violations.append("identity_binding d12_context invalid or matches_expected not True")
        else:
            d12_ctx = raw_d12
        if not isinstance(raw_sdk, Mapping) or raw_sdk.get("matches_expected") is not True:
            violations.append("identity_binding sdk_sandbox invalid or matches_expected not True")
        else:
            expected_sdk_recipe = str(raw_sdk.get("sdk_recipe_sha256", ""))
        if isinstance(raw_d12, Mapping) and isinstance(raw_sdk, Mapping):
            try:
                validate_expected_candidate_record({
                    "schema": EXPECTED_CANDIDATE_SCHEMA,
                    "platform": evidence.get("platform"),
                    "d12_context": raw_d12,
                    "sdk_sandbox": raw_sdk,
                })
            except HostedD12EvidenceError as exc:
                violations.append(f"identity_binding failed candidate validation: {exc}")

    env_sec = evidence.get("native_environment")
    if not isinstance(env_sec, Mapping):
        violations.append("native_environment missing or invalid")
    else:
        for fld, exp in (
            ("runner_os", EXPECTED_RUNNER_OS), ("runner_arch", EXPECTED_RUNNER_ARCH), ("host_kernel", "Linux"),
            ("host_arch", EXPECTED_HOST_ARCH), ("docker_daemon_arch", EXPECTED_HOST_ARCH),
        ):
            if env_sec.get(fld) != exp:
                violations.append(f"invalid {fld}: {env_sec.get(fld)}")
        if env_sec.get("emulated") is not False:
            violations.append("native_environment emulated must be False")

    violations.extend(_validate_sdk_materialization(evidence.get("sdk_materialization"), expected_sdk_recipe))

    app_builds = evidence.get("application_builds")
    if not isinstance(app_builds, Mapping) or set(app_builds.keys()) != set(ALL_APPLICATION_BUILD_KEYS):
        violations.append("application_builds must be a mapping with all 6 canonical keys")
    else:
        for key in ALL_APPLICATION_BUILD_KEYS:
            val = app_builds.get(key)
            if not _is_strict_int(val) or val != 0:
                violations.append(f"application_builds.{key} must be strict int 0, got {val!r}")

    prov_map = evidence.get("report_provenance")
    if isinstance(prov_map, Mapping):
        for rname in ("freeze", "exploration", "cleanup"):
            p = prov_map.get(rname)
            red = p.get("redacted", p.get("redacted_modified")) if isinstance(p, Mapping) else None
            if not isinstance(p, Mapping) or p.get("status") not in {"valid", "ok"} or red is not False:
                violations.append(f"report_provenance.{rname} invalid or redacted_unqualified")

    in_reports = evidence.get("inner_reports")
    if not isinstance(in_reports, Mapping):
        violations.append("inner_reports missing or invalid")
        return violations

    freeze, cleanup, expl = in_reports.get("freeze"), in_reports.get("cleanup"), in_reports.get("exploration")
    src_sha = str(d12_ctx.get("source_sha256", ""))
    rec_sha = str(d12_ctx.get("recipe_sha256", ""))
    doc_sha = str(d12_ctx.get("dockerfile_sha256", ""))
    raw_cnt = d12_ctx.get("context_file_count")
    ctx_cnt = int(raw_cnt) if _is_strict_int(raw_cnt) else 0

    violations.extend(
        validate_canonical_freeze_report(
            freeze,
            expected_source_sha256=src_sha,
            expected_recipe_sha256=rec_sha,
            expected_dockerfile_sha256=doc_sha,
            expected_context_file_count=ctx_cnt,
        )
    )
    violations.extend(validate_canonical_cleanup_report(cleanup))
    canonical_counts, count_violations = project_canonical_boundary_counts(freeze, cleanup)
    violations.extend(count_violations)
    if isinstance(app_builds, Mapping):
        for key in ALL_APPLICATION_BUILD_KEYS:
            if (actual_c := app_builds.get(key)) != (exp_c := canonical_counts.get(key)):
                violations.append(f"application_builds.{key} ({actual_c!r}) mismatches canonical ({exp_c!r})")

    if not isinstance(expl, Mapping):
        violations.append("inner_reports.exploration missing or not a mapping")
        return violations

    refusals = expl.get("refusals")
    if not isinstance(refusals, list) or not all(isinstance(r, str) for r in refusals):
        violations.append("exploration refusals must be a list of strings")
        return violations

    for r in refusals:
        if any(tok in r for tok in _REDACT_PATTERNS):
            violations.append(f"refusals contain unredacted private host path or credential: {r}")

    violations.extend(
        validate_canonical_exploration_report(
            expl,
            expected_source_sha256=src_sha,
            expected_recipe_sha256=rec_sha,
            expected_dockerfile_sha256=doc_sha,
            expected_context_file_count=ctx_cnt,
            expected_helper_sha256=EXPECTED_SDK_HELPER_SHA256,
            require_positive_observation=(not refusals),
        )
    )

    if refusals:
        if evidence.get("qualified") is not False:
            violations.append("evidence with refusals must not be qualified")
        if evidence.get("result") != "refused":
            violations.append(f"evidence with refusals must have result 'refused', got {evidence.get('result')}")
        exit_code = evidence.get("runner_exit_code")
        if not _is_strict_int(exit_code) or exit_code == 0:
            violations.append("evidence with refusals must have nonzero runner_exit_code")
        if require_positive_qualification:
            violations.append("positive qualification required but evidence was refused / not qualified")
    else:
        if (
            evidence.get("result") != "passed"
            or evidence.get("qualified") is not True
            or evidence.get("runner_exit_code") != 0
        ):
            violations.append("positive evidence must have result 'passed', qualified True, and exit code 0")
    return violations


def validate_system_hold_refusal(report: object) -> list[str]:
    if not isinstance(report, Mapping):
        return ["system hold refusal report must be a mapping"]
    violations: list[str] = []
    for fld, exp in (("schema", SYSTEM_HOLD_REFUSAL_SCHEMA), ("gate_kind", "main-system")):
        if report.get(fld) != exp:
            violations.append(f"invalid {fld}: {report.get(fld)}")
    if report.get("target_arch") not in {"amd64", "arm64"}:
        violations.append(f"invalid target_arch: {report.get('target_arch')}")
    if report.get("result") != "refused_release_prerequisites_unresolved":
        violations.append(f"invalid result: {report.get('result')}")
    if report.get("qualified") is not False:
        violations.append("system hold refusal qualified must be False")
    for fld in (
        "sdk_builds_started", "application_candidate_builds_started", "managed_system_candidate_image_build_count",
    ):
        if report.get(fld) != 0:
            violations.append(f"system hold {fld} must be 0")

    for fld in ("candidate_sha", "candidate_tree", "candidate_base_parent", "candidate_head_parent"):
        if not _is_hex(report.get(fld), 40):
            violations.append(f"invalid {fld}: must be 40-hex")
    for fld in ("d12_source_sha256", "d12_recipe_sha256", "d12_dockerfile_sha256"):
        if not _is_hex(report.get(fld), 64):
            violations.append(f"invalid {fld}: must be 64-hex")

    reasons = report.get("reasons")
    if not isinstance(reasons, list) or not reasons or not all(isinstance(r, str) for r in reasons):
        violations.append("reasons must be a non-empty list of strings")

    return violations
