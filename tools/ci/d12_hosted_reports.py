"""Canonical freeze, exploration, and cleanup report loading, counter projection, and validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from pathlib import Path
import sys
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):
    for _rel in ("", "src/main/python", "tools", "src/test/support/python"):
        if (_p := str((_ROOT / _rel).resolve())) not in sys.path:
            sys.path.insert(0, _p)

from ci.d12_hosted_state import MAX_SAFE_JSON_REPORT_BYTES, load_safe_json_report
import d12_libpq_runtime_probe
import d12_python_closure
from repomap_kg.runtime.release import (
    GO_RELEASE_IMAGE, POSTGRES_RELEASE_IMAGE, PRODUCT_MINIMUM_LIBPQ_VERSION, PYTHON_RELEASE_IMAGE,
    DebPackage, PlatformPackages, validate_package_manifest,
)
from repomap_test_support import d12_core_image
import test_sandbox_images

VERIFIED_AMD64_BASE_METADATA: dict[str, dict[str, str]] = {
    "go": {"reference": GO_RELEASE_IMAGE, "platform": "linux/amd64",
           "index": "sha256:632dff7351799a5a9954a48dc06670ade72ee44e8c351cdc0e5a57af2fea21af",
           "manifest": "sha256:88750ccdd0f2a77fcc00a14b1a48d6409bd8ddb5d7c2dd6ec0b4a2e916daf9d9",
           "config": "sha256:0d494ea9b5863337de0dfb4f938062bf0261a919016eb162d2be26381dbadafe"},
    "python": {"reference": PYTHON_RELEASE_IMAGE, "platform": "linux/amd64",
               "index": "sha256:962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e",
               "manifest": "sha256:6d2b0577e6d1632f077331de8e4780535f54839d163ded7abb4b7dd37b5d37ac",
               "config": "sha256:3a1b98be05abc7ac60c8712a943688620a602c3e0e6bfbc567afbeabe2085b28"},
    "postgres": {"reference": POSTGRES_RELEASE_IMAGE, "platform": "linux/amd64",
                 "index": "sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97",
                 "manifest": "sha256:f9d1e581cde3e4c8bc696b07e6f7b7aea1d41014b33a52b27990762daae61beb",
                 "config": "sha256:066167ff39c2a612402ce99b734ea1cff92a9d1f2ac52f697a5f0384f0d88d6b"},
}

APPLICATION_BUILD_COUNT_KEYS: tuple[str, ...] = (
    "managed_system_candidate_image_build_count", "product_or_build_profile_build_count",
    "unmanaged_build_count", "unmanaged_pull_count",
)
RESIDUE_ZERO_KEYS: tuple[str, ...] = (
    "current_run_ephemeral_image_residue", "current_run_image_residue", "current_run_volume_residue",
    "managed_runtime_build_intermediate_residue_count", "new_unattributed_images", "new_unattributed_volumes",
)
FREEZE_TOP_LEVEL_KEYS: frozenset[str] = frozenset({"admission", "availability", "bases", "budget", "labels", "tag"})
EXPLORATION_TOP_LEVEL_KEYS: frozenset[str] = frozenset({
    "mode", "daemon", "build_readiness", "p3", "host_forecast_substituted",
    "admission", "bindings", "availability", "bases", "steps", "refusals", "result",
})
CLEANUP_TOP_LEVEL_KEYS: frozenset[str] = frozenset({
    "budget", "candidate_image_id", "containers", "primary", "server", "zero_build",
})
KNOWN_EXPLORATION_REFUSAL_PREFIXES: tuple[str, ...] = ("libpq:", "trust:", "closure:", "builder:", "final:")

__all__ = [
    "APPLICATION_BUILD_COUNT_KEYS", "CLEANUP_TOP_LEVEL_KEYS", "EXPLORATION_TOP_LEVEL_KEYS",
    "FREEZE_TOP_LEVEL_KEYS", "KNOWN_EXPLORATION_REFUSAL_PREFIXES", "MAX_SAFE_JSON_REPORT_BYTES",
    "RESIDUE_ZERO_KEYS", "VERIFIED_AMD64_BASE_METADATA", "load_safe_json_report",
    "project_canonical_boundary_counts", "validate_canonical_cleanup_report",
    "validate_canonical_exploration_report", "validate_canonical_freeze_report",
]


def _is_strict_int(val: object) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _validate_admission(
    adm: object, *, expected_source_sha256: str, expected_recipe_sha256: str,
    expected_dockerfile_sha256: str, expected_context_file_count: int,
) -> list[str]:
    if not isinstance(adm, Mapping):
        return ["admission must be a mapping"]
    violations: list[str] = [
        f"admission {k} mismatch: {adm.get(k)!r} != {exp!r}"
        for k, exp in (("platform", "linux/amd64"), ("node_id", d12_core_image.NODE_ID),
                       ("source_sha256", expected_source_sha256), ("recipe_sha256", expected_recipe_sha256),
                       ("dockerfile_sha256", expected_dockerfile_sha256)) if adm.get(k) != exp]
    cnt = adm.get("context_file_count")
    if not _is_strict_int(cnt) or cnt != expected_context_file_count or cnt <= 0:
        violations.append(f"admission context_file_count must be {expected_context_file_count}, got {cnt!r}")
    return violations


def _validate_availability(avail: object) -> list[str]:
    if not isinstance(avail, Mapping):
        return ["availability must be a mapping"]
    violations: list[str] = []
    if avail.get("platform") != "linux/amd64" or avail.get("execution") != "native":
        violations.append(f"availability platform/exec invalid: {avail.get('platform')!r}/{avail.get('execution')!r}")
    bp = avail.get("builder_platforms")
    if not isinstance(bp, Sequence) or isinstance(bp, str) or "linux/amd64" not in bp:
        violations.append("availability builder_platforms must include 'linux/amd64'")
    return violations


def _validate_bases(bases: object) -> list[str]:
    if not isinstance(bases, Mapping):
        return ["bases must be a mapping"]
    violations: list[str] = []
    for ref, name, req_ver in ((POSTGRES_RELEASE_IMAGE, "postgres", True),
                               (PYTHON_RELEASE_IMAGE, "python", False), (GO_RELEASE_IMAGE, "go", False)):
        if not isinstance(b := bases.get(ref), Mapping):
            violations.append(f"bases missing entry for {ref}")
        else:
            if b.get("id") != VERIFIED_AMD64_BASE_METADATA[name]["config"] or b.get("platform") != "linux/amd64":
                violations.append(f"bases {name} mismatch: id={b.get('id')!r}, plat={b.get('platform')!r}")
            if not isinstance(v := b.get("config_digest_verified"), bool) or (req_ver and not v):
                violations.append(f"bases {name} config_digest_verified invalid: {v!r}")
    return violations


def project_canonical_boundary_counts(
    freeze_report: object, cleanup_report: object,
) -> tuple[dict[str, int | None], list[str]]:
    """Project canonical boundary counts without turning incomplete zero histories into final 0."""
    violations: list[str] = []
    fb = freeze_report.get("budget") if isinstance(freeze_report, Mapping) else None
    cb = cleanup_report.get("budget") if isinstance(cleanup_report, Mapping) else None
    cz = cleanup_report.get("zero_build") if isinstance(cleanup_report, Mapping) else None
    for lbl, m in (("freeze budget", fb), ("cleanup budget", cb), ("cleanup zero_build", cz)):
        if not isinstance(m, Mapping):
            violations.append(f"{lbl} missing or not a mapping")
        else:
            violations.extend(
                f"{lbl} missing required counter key: {k}" for k in APPLICATION_BUILD_COUNT_KEYS if k not in m
            )
    counts: dict[str, int | None] = {}
    for key in APPLICATION_BUILD_COUNT_KEYS:
        f_val = fb.get(key) if isinstance(fb, Mapping) and key in fb else None
        c_val = cb.get(key) if isinstance(cb, Mapping) and key in cb else None
        z_val = cz.get(key) if isinstance(cz, Mapping) and key in cz else None
        for lbl, v in (("freeze budget", f_val), ("cleanup budget", c_val), ("cleanup zero_build", z_val)):
            if v is not None and (not _is_strict_int(v) or v != 0):
                violations.append(f"{lbl} {key} must be strict 0, got {v!r}")
        if c_val is not None and z_val is not None and c_val != z_val:
            violations.append(f"cleanup budget {key} ({c_val}) mismatches zero_build ({z_val})")
        if f_val is not None and c_val is not None and f_val != c_val:
            violations.append(f"freeze budget {key} ({f_val}) mismatches cleanup budget ({c_val})")
        obs = [int(v) for v in (f_val, c_val, z_val) if _is_strict_int(v) and isinstance(v, int)]
        counts[key] = (
            max(obs) if any(x > 0 for x in obs) else (0 if len(obs) == 3 and all(x == 0 for x in obs) else None)
        )
    cand = counts.get("managed_system_candidate_image_build_count")
    counts["application_candidate_builds"] = cand
    parts = (cand, counts.get("product_or_build_profile_build_count"), counts.get("unmanaged_build_count"))
    pos_parts = [p for p in parts if isinstance(p, int) and p > 0]
    app: int | None = sum(pos_parts) if pos_parts else (0 if all(p == 0 for p in parts) else None)
    counts["application_builds"] = app
    if app is not None and app != 0:
        violations.append(f"application_builds must be 0, got {app}")
    return counts, violations


def validate_canonical_freeze_report(
    report: object, *, expected_source_sha256: str, expected_recipe_sha256: str,
    expected_dockerfile_sha256: str, expected_context_file_count: int,
) -> list[str]:
    if not isinstance(report, Mapping):
        return ["freeze report must be a mapping"]
    violations: list[str] = []
    if set(report.keys()) != FREEZE_TOP_LEVEL_KEYS:
        violations.append(f"freeze report keys must equal {sorted(FREEZE_TOP_LEVEL_KEYS)}")
    violations.extend(_validate_admission(
        report.get("admission"), expected_source_sha256=expected_source_sha256,
        expected_recipe_sha256=expected_recipe_sha256, expected_dockerfile_sha256=expected_dockerfile_sha256,
        expected_context_file_count=expected_context_file_count))
    violations.extend(_validate_availability(report.get("availability")))
    violations.extend(_validate_bases(report.get("bases")))
    if not isinstance(tag := report.get("tag"), str) or not tag:
        violations.append("freeze report tag must be a non-empty string")
    if not isinstance(lbls := report.get("labels"), Mapping):
        violations.append("freeze report labels must be a mapping")
    else:
        violations.extend(
            f"freeze labels {k} mismatch: {lbls.get(k)!r} != {exp!r}"
            for k, exp in (("org.repomap.d12.candidate", "true"), ("org.repomap.d12.platform", "linux/amd64"),
                           ("org.repomap.d12.recipe_sha256", expected_recipe_sha256),
                           ("org.repomap.d12.source_sha256", expected_source_sha256)) if lbls.get(k) != exp)
        if not isinstance(run_id := lbls.get("org.repomap.test.resource.run_id"), str) or not run_id:
            violations.append("freeze labels org.repomap.test.resource.run_id must be non-empty")
    if not isinstance(budget := report.get("budget"), Mapping):
        violations.append("freeze report budget must be a mapping")
    else:
        violations.extend(f"freeze budget {k} must be 0, got {budget.get(k)!r}" for k in APPLICATION_BUILD_COUNT_KEYS
                          if not _is_strict_int(v := budget.get(k)) or v != 0)
    return violations


def validate_canonical_cleanup_report(report: object) -> list[str]:
    if not isinstance(report, Mapping):
        return ["cleanup report must be a mapping"]
    violations: list[str] = []
    keys = set(report.keys())
    if not CLEANUP_TOP_LEVEL_KEYS.issubset(keys) or not keys.issubset(CLEANUP_TOP_LEVEL_KEYS | {"error"}):
        violations.append(f"cleanup report keys must be {sorted(CLEANUP_TOP_LEVEL_KEYS)} (optional 'error')")
    violations.extend(f"cleanup {k} must be {exp!r}, got {report.get(k)!r}"
                      for k, exp in (("candidate_image_id", None), ("containers", "baseline_verified"),
                                     ("server", "removed"), ("error", None)) if report.get(k) != exp)
    if not isinstance(zb := report.get("zero_build"), Mapping):
        violations.append("cleanup zero_build must be a mapping")
    elif set(zb.keys()) != set(APPLICATION_BUILD_COUNT_KEYS):
        violations.append(f"cleanup zero_build keys must be {sorted(APPLICATION_BUILD_COUNT_KEYS)}")
    else:
        violations.extend(f"cleanup zero_build {k} must be 0, got {zb.get(k)!r}" for k in APPLICATION_BUILD_COUNT_KEYS
                          if not _is_strict_int(v := zb.get(k)) or v != 0)
    if not isinstance(budget := report.get("budget"), Mapping):
        violations.append("cleanup budget must be a mapping")
    else:
        violations.extend(f"cleanup budget {k} must be 0, got {budget.get(k)!r}"
                          for k in (*APPLICATION_BUILD_COUNT_KEYS, *RESIDUE_ZERO_KEYS)
                          if not _is_strict_int(v := budget.get(k)) or v != 0)
    return violations


def _to_deb_tuple(rows: object) -> tuple[DebPackage, ...] | None:
    if not isinstance(rows, Sequence) or isinstance(rows, str):
        return None
    out: list[DebPackage] = []
    for p in rows:
        if isinstance(p, Sequence) and not isinstance(p, str) and len(p) == 4:
            out.append(DebPackage(str(p[0]), str(p[1]), str(p[2]), str(p[3])))
        elif isinstance(p, Mapping) and {"name", "version", "architecture", "sha256"} <= set(p):
            out.append(DebPackage(str(p["name"]), str(p["version"]), str(p["architecture"]), str(p["sha256"])))
        else:
            return None
    return tuple(out)


def _validate_candidate_manifest(manifest_raw: object, api: int) -> list[str]:
    if not isinstance(manifest_raw, Mapping):
        return ["candidate.manifest must be a mapping"]
    try:
        src, key = manifest_raw.get("pgdg_source"), manifest_raw.get("pgdg_keyring")
        fps, dyn = manifest_raw.get("key_fingerprints"), manifest_raw.get("lib_dynload")
        debs_b, debs_c = _to_deb_tuple(manifest_raw.get("builder")), _to_deb_tuple(manifest_raw.get("closure"))
        if (not isinstance(src, Sequence) or len(src) != 2 or not isinstance(key, Sequence) or len(key) != 2
                or not isinstance(fps, Sequence) or isinstance(fps, str) or not isinstance(dyn, Sequence)
                or isinstance(dyn, str) or debs_b is None or debs_c is None):
            return ["candidate.manifest sequence or DebPackage fields are malformed"]
        pkg = PlatformPackages(
            postgres_config_digest=str(manifest_raw.get("postgres_config_digest", "")),
            pgdg_source=(str(src[0]), str(src[1])), pgdg_keyring=(str(key[0]), str(key[1])),
            key_fingerprints=tuple(str(x) for x in fps), libpq_path=str(manifest_raw.get("libpq_path", "")),
            libpq_sha256=str(manifest_raw.get("libpq_sha256", "")),
            libpq5_version=str(manifest_raw.get("libpq5_version", "")),
            builder=debs_b, closure=debs_c, lib_dynload=tuple(str(x) for x in dyn))
        validate_package_manifest({"amd64": pkg}, api)
    except Exception as exc:
        return [f"candidate.manifest failed validate_package_manifest: {exc}"]
    return []


def validate_canonical_exploration_report(
    report: object, *, expected_source_sha256: str, expected_recipe_sha256: str,
    expected_dockerfile_sha256: str, expected_context_file_count: int,
    expected_helper_sha256: str, require_positive_observation: bool,
) -> list[str]:
    if not isinstance(report, Mapping):
        return ["exploration report must be a mapping"]
    violations: list[str] = []
    if set(report.keys()) != EXPLORATION_TOP_LEVEL_KEYS:
        violations.append(f"exploration report keys must equal {sorted(EXPLORATION_TOP_LEVEL_KEYS)}")
    violations.extend(
        f"exploration {fld} invalid: {report.get(fld)!r}"
        for fld, ok in (("mode", report.get("mode") == "exploration"),
                        ("daemon", isinstance(report.get("daemon"), str) and bool(report.get("daemon"))),
                        ("build_readiness", report.get("build_readiness") == "NOT ESTABLISHED"),
                        ("p3", report.get("p3") == "inputs only"),
                        ("host_forecast_substituted", report.get("host_forecast_substituted") is False)) if not ok)
    violations.extend(_validate_admission(
        report.get("admission"), expected_source_sha256=expected_source_sha256,
        expected_recipe_sha256=expected_recipe_sha256, expected_dockerfile_sha256=expected_dockerfile_sha256,
        expected_context_file_count=expected_context_file_count))
    violations.extend(_validate_availability(report.get("availability")))
    violations.extend(_validate_bases(report.get("bases")))
    run_id = None
    if not isinstance(b := report.get("bindings"), Mapping):
        violations.append("exploration bindings must be a mapping")
    else:
        run_id = b.get("run_id") if isinstance(b.get("run_id"), str) and b.get("run_id") else None
        if run_id is None or not isinstance(b.get("sdk_image"), str) or not b.get("sdk_image"):
            violations.append("exploration bindings run_id/sdk_image must be non-empty strings")
    if not isinstance(steps := report.get("steps"), Mapping):
        return [*violations, "exploration steps must be a mapping"]
    if not isinstance(eng := steps.get("engine"), Mapping):
        violations.append("exploration steps engine must be a mapping")
    else:
        cls, bk, bp = eng.get("classification"), eng.get("buildkit"), eng.get("builder_platforms")
        if not (isinstance(cls, Mapping) and cls.get("linux/amd64") == "native") or eng.get(
                "architecture") not in {"x86_64", "amd64"}:
            violations.append("engine classification or architecture invalid")
        if not isinstance(bk, str) or not bk:
            violations.append(f"engine buildkit must be non-empty version string, got {bk!r}")
        if not isinstance(bp, Sequence) or isinstance(bp, str) or "linux/amd64" not in bp:
            violations.append("engine builder_platforms must include 'linux/amd64'")

    if not isinstance(ident := steps.get("identity"), Mapping):
        violations.append("exploration steps identity must be a mapping")
    else:
        for k, meta in (("postgres", "postgres"), ("python", "python"), ("go", "go"), ("go_expected", "go")):
            if ident.get(k) != VERIFIED_AMD64_BASE_METADATA[meta]["config"]:
                violations.append(f"identity {k} mismatch")
        if ident.get("postgres_sealed") is not True or ident.get("go_run") is not False:
            violations.append("identity postgres_sealed must be True and go_run must be False")

    refusals, result = report.get("refusals"), report.get("result")
    if not require_positive_observation:
        if result != "refused":
            violations.append(f"partial refusal exploration result must be 'refused', got {result!r}")
        if not isinstance(refusals, list) or not refusals or not all(isinstance(r, str) and r for r in refusals):
            violations.append("partial refusal exploration refusals must be non-empty list[str]")
            ref_list: list[str] = []
        else:
            ref_list = refusals
        violations.extend(f"ambiguous or unknown refusal stage cannot prove first-failure boundary: {r!r}"
                          for r in ref_list if not r.startswith(KNOWN_EXPLORATION_REFUSAL_PREFIXES))
        for pfx, lbl, keys_after in (
            (("libpq:", "trust:", "closure:"), "refusal", ("builder", "libpq_runtime", "final_closure", "candidate")),
            (("builder:",), "builder refusal", ("libpq_runtime", "final_closure", "candidate")),
            (("final:",), "final refusal", ("final_closure", "candidate")),
        ):
            if any(r.startswith(pfx) for r in ref_list):
                violations.extend(f"premature continuation after {lbl}: steps.{k} present"
                                  for k in keys_after if steps.get(k) is not None)
        return violations

    if result != "observed" or refusals != []:
        violations.append(f"positive exploration requires result='observed' and refusals=[], got {result!r}")
    if not isinstance(libpq5_ver := steps.get("libpq5_version"), str) or not libpq5_ver:
        violations.append("positive exploration steps.libpq5_version must be a non-empty string")
    if not isinstance(trust := steps.get("trust"), Mapping):
        violations.append("positive exploration steps.trust must be a mapping")
    else:
        src_p, key_p = trust.get("pgdg_source"), trust.get("pgdg_keyring")
        srcs, keys, fps = trust.get("sources"), trust.get("keyrings"), trust.get("fingerprints")
        if (not isinstance(src_p, str) or not isinstance(key_p, str) or not isinstance(srcs, Mapping)
                or not isinstance(srcs.get(src_p), Mapping) or not isinstance(keys, Mapping)
                or not isinstance(keys.get(key_p), str) or not isinstance(fps, Mapping)
                or not isinstance(fps.get("primary"), list) or not fps.get("primary")):
            violations.append("positive exploration steps.trust structure invalid")
    if not isinstance(cl := steps.get("closure"), Mapping):
        violations.append("positive exploration steps.closure must be a mapping")
    else:
        violations.extend(d12_python_closure.validate_hosted_closure(
            cl, VERIFIED_AMD64_BASE_METADATA["python"]["config"]))
    for step_key, req_non_empty in (("builder", True), ("final_closure", False)):
        if not isinstance(st := steps.get(step_key), Mapping):
            violations.append(f"positive exploration steps.{step_key} must be a mapping")
        elif (st.get("native") != "amd64" or not _is_strict_int(rows := st.get("preexisting_rows"))
                or not isinstance(rows, int) or rows < 0 or not isinstance(pkgs := st.get("packages"), list)
                or (req_non_empty and not pkgs) or not all(isinstance(p, Mapping) for p in pkgs)):
            violations.append(f"positive exploration steps.{step_key} invalid")
    canonical_helper = (_ROOT / "tools/native_apt_prerequisites.py").resolve()
    probe_helper = Path(str(d12_libpq_runtime_probe.apt.__file__)).resolve()
    sandbox_helper = test_sandbox_images.SANDBOX_CONTEXT_SOURCES["apt_prerequisites.py"].resolve()
    actual_sha = hashlib.sha256(canonical_helper.read_bytes()).hexdigest()
    if probe_helper != canonical_helper or sandbox_helper != canonical_helper or actual_sha != expected_helper_sha256:
        violations.append("native_apt_prerequisites.py owner or helper_sha256 mismatch")
    cand = steps.get("candidate")
    manifest_raw = cand.get("manifest") if isinstance(cand, Mapping) else None
    manifest_map: Mapping[str, Any] = manifest_raw if isinstance(manifest_raw, Mapping) else {}
    if manifest_map.get("libpq5_version") != steps.get("libpq5_version"):
        violations.append("candidate.manifest.libpq5_version mismatch with steps.libpq5_version")
    srv = {"files": [{"role": "libpq", "owner": "libpq5", "resolved": manifest_map.get("libpq_path"),
                      "sha256": manifest_map.get("libpq_sha256")}]}
    api: int | None = None
    if not isinstance(lr := steps.get("libpq_runtime"), Mapping):
        violations.append("positive exploration steps.libpq_runtime must be a mapping")
    else:
        if lr.get("run_id") != run_id or lr.get("helper_sha256") != expected_helper_sha256:
            violations.append("libpq_runtime run_id or helper_sha256 mismatch")
        try:
            if _is_strict_int(raw_api := d12_libpq_runtime_probe.consume(lr, steps, srv, "linux/amd64")):
                api = int(raw_api)
        except Exception as exc:
            violations.append(f"libpq_runtime probe validation failed: {exc}")
        if api is not None and (api < PRODUCT_MINIMUM_LIBPQ_VERSION or lr.get("api") != api):
            violations.append(f"libpq_runtime api below {PRODUCT_MINIMUM_LIBPQ_VERSION}: {api}")
    if not isinstance(cand, Mapping):
        violations.append("positive exploration steps.candidate must be a mapping")
    else:
        if (cand.get("architecture") != "amd64" or cand.get("valid") is not True
                or cand.get("written_to_source") is not False
                or cand.get("libpq_label") != "runtime PQlibVersion; forecast is equality only"):
            violations.append("candidate metadata flags invalid")
        if api is not None:
            if cand.get("libpq_version") != api or cand.get("package_forecast") != api:
                violations.append(f"candidate libpq_version/package_forecast mismatch with {api}")
            violations.extend(_validate_candidate_manifest(manifest_raw, api))
    return violations
