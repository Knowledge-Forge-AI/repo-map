"""Functional and historical diagnostic checks shared by D12 observation and exported qualification."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from common_lore_index.runtime.release import POSTGRES_RELEASE_VERSION, PSYCOPG_RELEASE_VERSION, PYTHON_RELEASE_VERSION
from repomap_test_support import d12_dynamic_linkage as linkage
from repomap_test_support.d12_image_probes import CLIENTS, NOTICES, SERVER
from tools.system.config import SystemTestError
from common_lore_index.runtime.release import DebPackage, POSTGRES_RELEASE_IMAGE, PlatformPackages
from common_lore_index.runtime.release_manifest import D12_CANDIDATE_LIBPQ_VERSION, D12_CANDIDATE_PACKAGE_MANIFEST

APPROVED_DIAGNOSTIC_STOPS = (
    "vulnerability classification of every other package and distribution is not performed (unknown)",
    "incumbent 16.14 application inventory is unavailable without an extra build or pull",
)

class D12CandidateAssessmentError(SystemTestError, ValueError):
    """Raised when D12 post-build candidate observation or assessment fails."""

def _require(condition: object, message: str) -> None:
    if not condition:
        raise D12CandidateAssessmentError(message)

def _verify_round_trip(round_trip: Mapping[str, Any]) -> None:
    src, rst = round_trip.get("source"), round_trip.get("restored")
    if not isinstance(src, Mapping) or not isinstance(rst, Mapping):
        raise D12CandidateAssessmentError(f"round-trip missing source/restored observations: {round_trip!r}")
    before, after = round_trip.get("archive_sha256_before"), round_trip.get("archive_sha256_after")
    _require(bool(before) and before == after, f"round-trip archive SHA-256 mismatch: {round_trip!r}")
    _require(src.get("fixture_md5") == rst.get("fixture_md5") and rst.get("fixture_rows") == 2000, "2000-row mismatch")
    _require((src.get("graph_schema"), rst.get("graph_schema")) == ("CURRENT", "CURRENT"), "graph_schema != CURRENT")
    _require((src.get("extensions"), rst.get("extensions")) == (["plpgsql"], ["plpgsql"]), "extensions != ['plpgsql']")
    _require((src.get("replication_slots"), rst.get("replication_slots")) == (0, 0), "replication_slots != 0")
    ams = (set(src.get("index_access_methods") or ()), set(rst.get("index_access_methods") or ()))
    _require(ams == ({"btree"}, {"btree"}), f"round-trip index_access_methods must be {{'btree'}}: {round_trip!r}")

def _verify_candidate_assessment(
    *, packaging: Mapping[str, Any], linkage_report: dict[str, Any], candidate: Mapping[str, Any],
    server_side: Mapping[str, str], round_trip: Mapping[str, Any], findings: Sequence[Mapping[str, Any]],
    libpq: Sequence[Mapping[str, Any]], critical_unknown: Sequence[Any], stops: Sequence[str],
    expected_libpq_version: int, upstream_informational: bool = False,
) -> None:
    expected_pg, versions = f"(PostgreSQL) {POSTGRES_RELEASE_VERSION}", packaging.get("versions")
    if not isinstance(versions, Mapping) or any(
            expected_pg not in str(versions.get(p, "")) for p in (SERVER, *CLIENTS)):
        raise D12CandidateAssessmentError(f"candidate PostgreSQL binary versions mismatch: {versions!r}")
    _require(bool(server_side) and all(expected_pg in str(t) for t in server_side.values()), "server binary mismatch")
    source_obs = round_trip.get("source")
    if not isinstance(source_obs, Mapping) or not str(source_obs.get("server_version", "")).startswith(
            POSTGRES_RELEASE_VERSION):
        raise D12CandidateAssessmentError(f"server process version mismatch: {source_obs!r}")
    rt_tuple = (packaging.get("python"), packaging.get("psycopg"),
                packaging.get("implementation"), packaging.get("libpq"))
    exp_tuple = (PYTHON_RELEASE_VERSION, PSYCOPG_RELEASE_VERSION, "c", expected_libpq_version)
    _require(rt_tuple == exp_tuple, f"candidate runtime tuple {rt_tuple!r} != {exp_tuple!r}")
    residue_keys = ("pip_absent", "setuptools_absent", "ensurepip_absent", "go_absent")
    _require(all(bool(packaging.get(k)) for k in residue_keys), f"build tool residue: {packaging!r}")
    _require(packaging.get("has_cancel_safe"), "product libpq must keep the bounded cancel_safe (ADR 0089 D2)")
    migs = packaging.get("migrations")
    _require(isinstance(migs, Sequence) and len(migs) == 2 and all(isinstance(m, int) and m > 0 for m in migs), "migs")
    _require(str(packaging.get("go_helper_protocol", "")).isdigit(), "go_helper_protocol invalid")
    _require(not packaging.get("bundled_libpq"), f"bundled libpq present: {packaging.get('bundled_libpq')!r}")
    if l_fail := linkage.assess(
            linkage_report, psycopg_version=PSYCOPG_RELEASE_VERSION, libpq_version=expected_libpq_version):
        raise D12CandidateAssessmentError(f"dynamic linkage assessment failed: {l_fail}")
    notices = candidate.get("notices")
    if not isinstance(notices, Mapping) or not all(notices.get(path, "absent") != "absent" for path in NOTICES[6:]):
        raise D12CandidateAssessmentError(f"missing required candidate notices: {notices!r}")
    if not upstream_informational:  # Historical v1 diagnostic policy; ADR0105 uses the delta assessor below.
        _require(not critical_unknown, f"critical unknown files or links: {critical_unknown!r}")
        if unapproved_stops := [s for s in stops if s not in APPROVED_DIAGNOSTIC_STOPS]:
            raise D12CandidateAssessmentError(f"unapproved post-build diagnostic stops: {unapproved_stops}")
    # These are PostgreSQL/PGDG component checks, separate from inherited Debian OS diagnostics.
    _require(bool(findings) and all(f.get("class") == "outside_affected_range" for f in findings), "CVE findings fail")
    _require(bool(libpq) and all(f.get("class") == "outside_affected_range" for f in libpq), "libpq findings fail")
    _verify_round_trip(round_trip)



CTX_IDENTITY_KEYS: tuple[str, str, str, str] = (
    "source_sha256",
    "recipe_sha256",
    "dockerfile_sha256",
    "context_file_count",
)


def normalize_candidate_manifest(manifest: Mapping[str, Any]) -> PlatformPackages:
    try:
        return PlatformPackages(
            str(manifest["postgres_config_digest"]),
            (str(manifest["pgdg_source"][0]), str(manifest["pgdg_source"][1])),
            (str(manifest["pgdg_keyring"][0]), str(manifest["pgdg_keyring"][1])),
            tuple(str(x) for x in manifest["key_fingerprints"]),
            str(manifest["libpq_path"]),
            str(manifest["libpq_sha256"]),
            str(manifest["libpq5_version"]),
            tuple(DebPackage(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in manifest["builder"]),
            tuple(DebPackage(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in manifest["closure"]),
            tuple(str(x) for x in manifest["lib_dynload"]),
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SystemTestError(f"malformed preflight candidate manifest: {exc}") from exc


def verify_preflight_matches_manifest(
    preflight: Mapping[str, Any],
    *,
    proof: Mapping[str, Any],
    libpq_version: int = D12_CANDIDATE_LIBPQ_VERSION,
    amd64_packages: PlatformPackages | None = None,
) -> None:
    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"] if amd64_packages is None else amd64_packages
    if pkg.closure:
        raise SystemTestError("new Debian closure needs exact delta-provenance support before a build")
    if "build" in preflight or "image_cleanup" in preflight:
        raise SystemTestError("D12 same-daemon preflight is zero-build exploration and must not claim build/image")
    if preflight.get("result") != "observed" or preflight.get("refusals") or preflight.get("failures"):
        raise SystemTestError(f"D12 same-daemon preflight exploration failed: {preflight.get('result')!r}")
    avail = preflight.get("availability")
    if not isinstance(avail, Mapping) or avail.get("execution") != "native":
        raise SystemTestError(f"D12 same-daemon preflight requires native execution: {avail!r}")
    bases = preflight.get("bases")
    pg_base = bases.get(POSTGRES_RELEASE_IMAGE) if isinstance(bases, Mapping) else None
    pg_base_id = pg_base.get("id") if isinstance(pg_base, Mapping) else None
    if not isinstance(pg_base_id, str) or not pg_base_id.startswith("sha256:"):
        raise SystemTestError(f"D12 same-daemon preflight missing verified PostgreSQL base image ID: {bases!r}")
    cleanup = preflight.get("cleanup")
    if (
        not isinstance(cleanup, Mapping) or cleanup.get("server") != "removed"
        or cleanup.get("containers") != "baseline_verified"
        or not isinstance(cleanup.get("zero_build"), Mapping)
        or any(v != 0 for v in cleanup["zero_build"].values())
    ):
        raise SystemTestError(f"D12 same-daemon preflight cleanup/zero-build custody failed: {cleanup!r}")
    ident, d12_ctx, rel_man = preflight.get("identity"), proof.get("d12_context"), proof.get("release_manifest")
    if not isinstance(ident, Mapping) or not isinstance(d12_ctx, Mapping) or not isinstance(rel_man, Mapping):
        raise SystemTestError("D12 same-daemon preflight missing identity, d12_context, or release_manifest")
    if any(ident.get(k) != d12_ctx.get(k) for k in CTX_IDENTITY_KEYS):
        raise SystemTestError(f"D12 same-daemon preflight identity mismatch against d12_context: {ident!r}")
    if (
        rel_man.get("libpq_version") != libpq_version or rel_man.get("libpq5_version") != pkg.libpq5_version
        or rel_man.get("libpq_sha256") != pkg.libpq_sha256
        or rel_man.get("postgres_config_digest") != pkg.postgres_config_digest
    ):
        raise SystemTestError("D12 same-daemon preflight proof.release_manifest mismatch against release_manifest")
    steps = preflight.get("steps")
    if not isinstance(steps, Mapping) or not isinstance(steps.get("candidate"), Mapping):
        raise SystemTestError("D12 same-daemon preflight missing steps.candidate")
    cand_step, rt_step = steps["candidate"], steps.get("libpq_runtime")
    if cand_step.get("valid") is not True or cand_step.get("written_to_source") is not False:
        raise SystemTestError("D12 same-daemon preflight steps.candidate is not a valid unwritten manifest")
    if normalize_candidate_manifest(cand_step.get("manifest") or {}) != pkg or (
        cand_step.get("libpq_version") != libpq_version
    ):
        raise SystemTestError("D12 same-daemon preflight candidate manifest mismatch against release_manifest")
    if not isinstance(rt_step, Mapping) or rt_step.get("api") != libpq_version:
        raise SystemTestError("D12 same-daemon preflight libpq_runtime.api mismatch")
    lib_blk = rt_step.get("library")
    if (
        not isinstance(lib_blk, Mapping) or lib_blk.get("path") != pkg.libpq_path
        or lib_blk.get("sha256") != pkg.libpq_sha256 or lib_blk.get("package") != "libpq5"
        or lib_blk.get("version") != pkg.libpq5_version or lib_blk.get("architecture") not in (None, "amd64")
    ):
        raise SystemTestError("D12 same-daemon preflight libpq_runtime.library mismatch")
    if not isinstance(srv_inv := preflight.get("server_inventory"), Mapping):
        raise SystemTestError("D12 same-daemon preflight missing server_inventory")
    srv_libs = {
        (f.get("resolved"), f.get("sha256")) for f in (srv_inv.get("files") or ())
        if isinstance(f, Mapping) and f.get("role") == "libpq" and f.get("owner") == "libpq5"
    }
    srv_vers = [
        tuple(map(int, m)) for r in (srv_inv.get("packages") or ())
        if isinstance(r, (list, tuple)) and len(r) >= 2 and r[0] == "libpq5"
        for m in re.findall(r"^(\d+)\.(\d+)", str(r[1]))
    ]
    if srv_libs != {(pkg.libpq_path, pkg.libpq_sha256)} or [divmod(libpq_version, 10000)] != srv_vers:
        raise SystemTestError("D12 same-daemon preflight server_inventory libpq5 oracle mismatch")
