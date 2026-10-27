"""Post-build D12 candidate image probes, disposable round-trip, and bounded sidecar writer."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import inspect, json, secrets
from pathlib import Path
from typing import Any

from ci.d12_system_grant import EXPECTED_PHASE_ID
import d12_dependency_preflight as inner
from repomap_kg.runtime.release import (
    POSTGRES_RELEASE_IMAGE, POSTGRES_RELEASE_VERSION, PSYCOPG_RELEASE_VERSION,
    PYTHON_RELEASE_IMAGE, PYTHON_RELEASE_VERSION,
)
from repomap_kg.runtime.release_manifest import D12_CANDIDATE_LIBPQ_VERSION
from repomap_test_support import d12_core_image as d12, d12_dynamic_linkage as linkage
from repomap_test_support.d12_image_probes import (
    ADVISORIES, CLIENTS, NOTICES, PACKAGING_PY, ROUND_TRIP_PY, SERVER,
    _classify, _create, _hashes, _inventory, _libpq_findings, _run_once, _start_server, _version,
)
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_run import active_resource_run
from tools.system import d12_glibc_risk as glibc_risk
from tools.system.config import SystemTestConfig, SystemTestError
from tools.system.d12_exec import wrap_create_with_bounded_exec
from tools.system.d12_system_reports import (
    encode_sorted_json_bytes, redact_public_text as _redact_public_text,
    write_bounded_json_atomic, write_bounded_json_to_targets,
)
from tools.system.d12_system_session import (
    D12SystemSession, LABEL_D12_GRANT_ID, LABEL_D12_RECIPE_SHA256, LABEL_D12_SOURCE_SHA256,
)
SYSTEM_CANDIDATE_EVIDENCE_SCHEMA = "repomap-d12-system-candidate-evidence-v1"
SYSTEM_CANDIDATE_EVIDENCE_FILENAME = "d12-system-candidate-evidence.json"
MAX_SYSTEM_CANDIDATE_EVIDENCE_BYTES = d12.REPORT_PART_LIMIT
APPROVED_DIAGNOSTIC_STOPS: tuple[str, str] = (
    "vulnerability classification of every other package and distribution is not performed (unknown)",
    "incumbent 16.14 application inventory is unavailable without an extra build or pull",
)

class D12CandidateAssessmentError(SystemTestError, ValueError):
    """Raised when D12 post-build candidate observation or assessment fails."""

def _require(condition: object, message: str) -> None:
    if not condition:
        raise D12CandidateAssessmentError(message)
def _check_deadline(deadline: Any | None, operation: str) -> None:
    if deadline is not None and hasattr(deadline, "check_test_budget"):
        deadline.check_test_budget(operation)
    elif deadline is not None and hasattr(deadline, "check_budget"):
        deadline.check_budget()
def _finish_probe_owner(owner: Any, server_id: str | None, primary: BaseException | None) -> None:
    steps = ((f"server {server_id} cleanup", lambda: owner.cleanup(server_id)),) if server_id else ()
    for step_name, fn in (*steps, ("baseline verification", owner.verify_baseline)):
        try:
            fn()
        except BaseException as exc:
            if primary is None:
                raise
            primary.add_note(f"D12 {step_name} also failed ({type(exc).__name__}: {exc})")
def _invoke_with_optional_bounds(
    fn: Callable[..., Any], *args: Any, deadline: Any | None = None,
    create_fn: Callable[..., tuple[str, Any]] | None = None, **kwargs: Any,
) -> Any:
    try:
        params: Mapping[str, inspect.Parameter] = inspect.signature(fn).parameters
        var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    except (ValueError, TypeError) as exc:
        if deadline is not None or create_fn is not None:
            raise SystemTestError(f"D12 bounded probe callback {fn!r} has uninspectable signature") from exc
        params, var_kw = {}, False
    call_kwargs = {k: v for k, v in kwargs.items() if k != "run_once_fn" or k in params or var_kw}
    for key, val in (("deadline", deadline), ("create_fn", create_fn)):
        if val is not None and key not in params and not var_kw:
            raise SystemTestError(f"D12 bounded probe callback {fn!r} must accept {key!r}")
        if val is not None:
            call_kwargs[key] = val
    return fn(*args, **call_kwargs)
def _resolve_owner_client(owner: Any | None, client: Any | None) -> tuple[Any, Any]:
    if owner is not None and client is not None:
        return owner, client
    boundary, run = d12.locate_run_boundary(), active_resource_run()
    if run is None:
        raise SystemTestError("D12 post-build probes require an active canonical resource run")
    resolved_client = boundary.client if client is None else client
    return (CurrentRunDockerContainers(run, resolved_client) if owner is None else owner), resolved_client
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
    expected_libpq_version: int,
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
    _require(not critical_unknown, f"critical unknown files or links: {critical_unknown!r}")
    _require(bool(findings) and all(f.get("class") == "outside_affected_range" for f in findings), "CVE findings fail")
    _require(bool(libpq) and all(f.get("class") == "outside_affected_range" for f in libpq), "libpq findings fail")
    if unapproved_stops := [s for s in stops if s not in APPROVED_DIAGNOSTIC_STOPS]:
        raise D12CandidateAssessmentError(f"unapproved post-build diagnostic stops: {unapproved_stops}")
    _verify_round_trip(round_trip)

def observe_and_assess_candidate(
    owner: Any, client: Any, *, image_id: str, platform: str, server_id: str,
    server_env: Mapping[str, str], server_side: Mapping[str, str], server_inventory: Mapping[str, Any],
    availability: Mapping[str, Any], expected_libpq_version: int | None = D12_CANDIDATE_LIBPQ_VERSION,
    tls_header: tuple[str, str, str] = inner.HEADER,
    write_report: Callable[[str, dict[str, Any]], object] | None = None,
    run_once_fn: Callable[..., str] = _run_once, inventory_fn: Callable[..., dict[str, Any]] = _inventory,
    hashes_fn: Callable[..., dict[str, str]] = _hashes, deadline: Any | None = None,
    create_fn: Callable[..., tuple[str, Any]] | None = None, server_image_id: str | None,
) -> dict[str, Any]:
    """Run candidate-image probes, stage attribution, 2000-row archive round-trip, and D2/P3 assessment."""
    if isinstance(expected_libpq_version, bool) or not isinstance(expected_libpq_version, int):
        raise D12CandidateAssessmentError("expected_libpq_version must be an explicit integer, not None")
    _check_deadline(deadline, "d12 candidate assessment")
    pkg_env = {"D12_PATHS": json.dumps([SERVER, *CLIENTS]), "D12_LIBRARY_FILE": linkage.LIBRARY_FILE.pattern}
    packaging = json.loads(_invoke_with_optional_bounds(
        run_once_fn, owner, client, image_id, ["-c", PACKAGING_PY], role="d12-packaging",
        entrypoint=["python"], environment=pkg_env, platform=platform, deadline=deadline, create_fn=create_fn,
    ).splitlines()[-1])
    linkage_report = json.loads(_invoke_with_optional_bounds(
        run_once_fn, owner, client, image_id, ["-I", "-c", linkage.probe_source(), "probe"],
        role="d12-linkage", entrypoint=["python"], platform=platform, deadline=deadline, create_fn=create_fn,
    ).splitlines()[-1])
    candidate = _invoke_with_optional_bounds(
        inventory_fn, owner, client, image_id, platform, "d12-inventory-candidate",
        deadline=deadline, create_fn=create_fn, run_once_fn=run_once_fn)
    resolved = sorted({f["resolved"] for f in candidate["files"] if f["kind"] != "missing"})
    stages = {name: _invoke_with_optional_bounds(
        hashes_fn, owner, client, ref, resolved, platform, f"d12-hash-{name}",
        deadline=deadline, create_fn=create_fn, run_once_fn=run_once_fn)
        for name, ref in (("postgres", POSTGRES_RELEASE_IMAGE), ("python", PYTHON_RELEASE_IMAGE))}
    for item in candidate["files"]:
        matches = [n for n, hashes in stages.items() if hashes.get(item["resolved"]) == item["sha256"]]
        pip = "/site-packages/" in item["resolved"] or ".libs/" in item["resolved"]
        item["stage"] = "+".join(matches) or ("python-runtime-pip" if pip else "unattributed")
    inventory_report: dict[str, Any] = {
        "candidate": candidate, "server": dict(server_inventory), "packaging": packaging, "linkage": linkage_report}
    if write_report is not None:
        write_report("inventory", inventory_report)
    rt_env = {"PGPASSWORD": server_env["POSTGRES_PASSWORD"], "PGUSER": server_env["POSTGRES_USER"],
              "PGDATABASE": server_env["POSTGRES_DB"]}
    round_trip = json.loads(_invoke_with_optional_bounds(
        run_once_fn, owner, client, image_id, ["-c", ROUND_TRIP_PY], role="d12-round-trip",
        entrypoint=["python"], environment=rt_env, network=f"container:{server_id}", platform=platform,
        deadline=deadline, create_fn=create_fn).splitlines()[-1])
    observed = {"candidate": packaging["versions"], "server_image": dict(server_side),
                "server_process": round_trip["source"]["server_version"]}
    findings = [{"advisory": cve, "image": image, "path": path, "observed": text, "class": _classify(_version(text))}
                for cve, path in ADVISORIES.items()
                for image, text in (("candidate", packaging["versions"].get(path)), ("server", server_side.get(path)))]
    critical_unknown = [f for f in candidate["files"] if f["kind"] == "missing"] + [
        link for link in candidate["links"] if link[-1] == "not"]
    libpq = _libpq_findings(packaging, candidate)
    stops = [f"{f['advisory']} {f['copy']} {f['class']}" for f in libpq if f["class"] != "outside_affected_range"]
    stops += [*APPROVED_DIAGNOSTIC_STOPS, *[
        f"unattributed bytes: {f['resolved']}" for f in candidate["files"] if f["stage"] == "unattributed"]]
    stops += [] if availability.get("execution") == "native" else [f"{platform} ran under existing emulation"]
    tls = {name: [r for r in inv["packages"] if r[:1] == [tls_header[0]]]
           for name, inv in (("server", server_inventory), ("candidate", candidate))}
    stops += [f"{name} TLS runtime is not exactly {tls_header[0]}={tls_header[2]} (ADR 0091): {rows}"
              for name, rows in tls.items() if [r[1] for r in rows] != [tls_header[2]]]
    glibc = glibc_risk.evaluate_d12_post_build(candidate_image_id=image_id, candidate_inventory=candidate,
        server_image_id=server_image_id, server_inventory=server_inventory, base_reference=POSTGRES_RELEASE_IMAGE,
        platform=platform, availability=availability)
    result_report: dict[str, Any] = {
        "observed_versions": observed, "server_side": dict(server_side), "tls_runtime": tls, "round_trip": round_trip,
        "findings": findings, "libpq_findings": libpq, "critical_unknown": critical_unknown, "glibc_disposition": glibc,
        "availability": dict(availability), "qualification": "stop_pending_disposition", "stops": stops}
    if write_report is not None:
        write_report("result", result_report)
    _verify_candidate_assessment(
        packaging=packaging, linkage_report=linkage_report, candidate=candidate, server_side=server_side,
        round_trip=round_trip, findings=findings, libpq=libpq, critical_unknown=critical_unknown, stops=stops,
        expected_libpq_version=expected_libpq_version)
    _require(glibc["status"] == glibc_risk.ACCEPTED, f"glibc disposition refused: {glibc.get('refusal')}")
    return {"inventory": inventory_report, "result": result_report}

def _store_session_probe_report(session: D12SystemSession, name: str, payload: dict[str, Any]) -> None:
    if (report_dir := session.config.report_dir) is None:
        raise SystemTestError("D12SystemSession requires config.report_dir")
    try:
        digest = write_bounded_json_atomic(
            report_dir / f"d12-post-build-{name}.json", payload, part_limit=d12.REPORT_PART_LIMIT,
            total_limit=d12.REPORT_TOTAL_LIMIT, cleanup_reserve=d12.REPORT_CLEANUP_RESERVE)
    except ValueError as exc:
        raise SystemTestError(str(exc)) from exc
    if name == "inventory":
        pkg, cand = payload.get("packaging") or {}, payload.get("candidate") or {}
        c_map = cand if isinstance(cand, Mapping) else {}
        session.post_build_probes = {
            "inventory_sha256": digest, "packaging": dict(pkg) if isinstance(pkg, Mapping) else {},
            "linkage": payload.get("linkage"), "notices": c_map.get("notices"),
            "verify_count": c_map.get("verify_count"), "unowned_count": c_map.get("unowned_count")}
    elif name == "result":
        keys = ("observed_versions", "tls_runtime", "findings", "libpq_findings",
                "critical_unknown", "availability", "qualification", "stops", "glibc_disposition")
        session.post_build_assessments = {"result_sha256": digest, **{k: payload.get(k) for k in keys}}
        if isinstance(payload.get("round_trip"), Mapping):
            session.roundtrip_evidence = dict(payload["round_trip"])

def run_post_build_candidate_probes(
    session: D12SystemSession, *, image_id: str, image_labels: Mapping[str, str], timeout_seconds: float = 120.0,
    deadline: Any | None = None, owner: Any | None = None, client: Any | None = None,
    observe_fn: Callable[..., dict[str, Any]] = observe_and_assess_candidate,
    start_server_fn: Callable[..., tuple[str, Any]] = _start_server,
    inventory_fn: Callable[..., dict[str, Any]] = _inventory, hashes_fn: Callable[..., dict[str, str]] = _hashes,
    run_once_fn: Callable[..., str] = _run_once, expected_libpq_version: int | None = None,
) -> dict[str, Any]:
    _check_deadline(deadline, "d12 post-build probes")
    if expected_libpq_version is None:
        rel_m = session.proof.get("release_manifest")
        expected_libpq_version = rel_m.get("libpq_version") if isinstance(rel_m, Mapping) else None
    if isinstance(expected_libpq_version, bool) or not isinstance(expected_libpq_version, int):
        raise SystemTestError("D12 post-build probes require integer release_manifest.libpq_version")
    if not isinstance(raw_av := (session.preflight_report or {}).get("availability"), Mapping) or (
        raw_av.get("execution") != "native"):
        raise SystemTestError("D12 post-build probes require native preflight availability")
    bases = (session.preflight_report or {}).get("bases")
    pg_b = bases.get(POSTGRES_RELEASE_IMAGE) if isinstance(bases, Mapping) else None
    expected_pg_id = pg_b.get("id") if isinstance(pg_b, Mapping) else None
    if not isinstance(expected_pg_id, str) or not expected_pg_id.startswith("sha256:"):
        raise SystemTestError("D12 post-build probes require observed PostgreSQL base image ID in preflight report")
    for lbl_key, expected_val in session.candidate_d12_labels().items():
        if image_labels.get(lbl_key) != expected_val:
            raise SystemTestError(f"candidate image D12 label {lbl_key} mismatch")
    owner, client = _resolve_owner_client(owner, client)
    b_create = wrap_create_with_bounded_exec(_create, deadline=deadline, default_timeout_seconds=timeout_seconds)
    platform, server_id, avail = "linux/amd64", None, dict(raw_av)
    server_env = {"POSTGRES_USER": "d12", "POSTGRES_DB": "d12", "POSTGRES_PASSWORD": secrets.token_hex(16)}
    rec = lambda n, p: _store_session_probe_report(session, n, p)
    primary: BaseException | None = None
    try:
        server_id, srv = _invoke_with_optional_bounds(
            start_server_fn, owner, client, server_env, platform, deadline=deadline, create_fn=b_create)
        srv_attrs = getattr(srv, "attrs", None)
        if not isinstance(srv_attrs, Mapping) or srv_attrs.get("Image") != expected_pg_id:
            raise SystemTestError("D12 post-build server container image digest mismatch")
        srv_side = {p: (srv.exec_run([p, "--version"]).output or b"").decode("utf-8", "replace").strip()
                    for p in (SERVER, *CLIENTS)}
        srv_inv = _invoke_with_optional_bounds(
            inventory_fn, owner, client, expected_pg_id, platform, "d12-inventory-server",
            deadline=deadline, create_fn=b_create, run_once_fn=run_once_fn)
        assessed = _invoke_with_optional_bounds(
            observe_fn, owner, client, image_id=image_id, platform=platform, server_id=server_id,
            server_env=server_env, server_side=srv_side, server_inventory=srv_inv, availability=avail,
            expected_libpq_version=expected_libpq_version, tls_header=inner.HEADER, write_report=rec,
            run_once_fn=run_once_fn, inventory_fn=inventory_fn, hashes_fn=hashes_fn, deadline=deadline,
            create_fn=b_create, server_image_id=expected_pg_id)
        if session.post_build_probes is None and isinstance(assessed.get("inventory"), Mapping):
            rec("inventory", dict(assessed["inventory"]))
        if session.post_build_assessments is None and isinstance(assessed.get("result"), Mapping):
            rec("result", dict(assessed["result"]))
        return dict(session.post_build_probes or assessed)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        _finish_probe_owner(owner, server_id, primary)

def run_disposable_roundtrip_probe(
    session: D12SystemSession, *, image_id: str, timeout_seconds: float = 120.0, deadline: Any | None = None,
    owner: Any | None = None, client: Any | None = None,
    start_server_fn: Callable[..., tuple[str, Any]] | None = None, run_once_fn: Callable[..., str] | None = None,
) -> dict[str, Any]:
    _check_deadline(deadline, "d12 disposable round-trip")
    if session.roundtrip_evidence is not None and all(x is None for x in (owner, client, start_server_fn, run_once_fn)):
        _verify_round_trip(session.roundtrip_evidence)
        return dict(session.roundtrip_evidence)
    owner, client = _resolve_owner_client(owner, client)
    b_create = wrap_create_with_bounded_exec(_create, deadline=deadline, default_timeout_seconds=timeout_seconds)
    platform, server_id, primary = "linux/amd64", None, None
    server_env = {"POSTGRES_USER": "d12", "POSTGRES_DB": "d12", "POSTGRES_PASSWORD": secrets.token_hex(16)}
    try:
        server_id, _ = _invoke_with_optional_bounds(
            start_server_fn or _start_server, owner, client, server_env, platform, deadline=deadline,
            create_fn=b_create)
        rt_env = {"PGPASSWORD": server_env["POSTGRES_PASSWORD"], "PGUSER": server_env["POSTGRES_USER"],
                  "PGDATABASE": server_env["POSTGRES_DB"]}
        round_trip = json.loads(_invoke_with_optional_bounds(
            run_once_fn or _run_once, owner, client, image_id, ["-c", ROUND_TRIP_PY], role="d12-round-trip",
            entrypoint=["python"], environment=rt_env, network=f"container:{server_id}", platform=platform,
            deadline=deadline, create_fn=b_create).splitlines()[-1])
        _verify_round_trip(round_trip)
        session.roundtrip_evidence = dict(round_trip)
        return dict(round_trip)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        _finish_probe_owner(owner, server_id, primary)

def validate_d12_system_candidate_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("schema") != SYSTEM_CANDIDATE_EVIDENCE_SCHEMA:
        raise SystemTestError("invalid D12 system candidate evidence schema")
    if payload.get("phase") != EXPECTED_PHASE_ID or payload.get("route") != "B":
        raise SystemTestError("invalid D12 system candidate evidence phase or route")
    for flag in ("image_accepted", "p3_accepted", "merge_authorized", "qualified"):
        if payload.get(flag) is not False:
            raise SystemTestError(f"D12 system candidate evidence {flag} must remain False while P3 is unaccepted")
    if len(encode_sorted_json_bytes(payload)) > d12.REPORT_PART_LIMIT:
        raise SystemTestError(f"D12 system candidate evidence exceeds {d12.REPORT_PART_LIMIT} bytes")
    return dict(payload)

def build_and_write_d12_system_candidate_evidence(
    session: D12SystemSession, *, config: SystemTestConfig, candidate_image_id: str | None,
    candidate_image_digest: str, candidate_image_labels: Mapping[str, str], step_results: Sequence[Any],
    mcp_readback_digest: str, cleanup_status: Mapping[str, Any], temp_cleanup_errors: Sequence[str],
    diagnostic_steps_passed: bool, error_message: str, evidence_dir: Path | None = None,
) -> Path | None:
    raw_errs = ([error_message] if error_message else []) + list(temp_cleanup_errors)
    failures = [_redact_public_text(msg, repo_root=session.repo_root) for msg in raw_errs]
    cleanup_ok = bool(cleanup_status.get("success", False)) and not temp_cleanup_errors
    preflight_rep, preflight_summary = session.preflight_report, None
    if isinstance(preflight_rep, Mapping):
        steps = preflight_rep.get("steps")
        c_step = steps.get("candidate") if isinstance(steps, Mapping) else None
        preflight_summary = {
            "result": preflight_rep.get("result", "unknown"), "sha256": session.preflight_sha256,
            "refusals": list(preflight_rep.get("refusals") or []), "availability": preflight_rep.get("availability"),
            "candidate_libpq_version": c_step.get("libpq_version") if isinstance(c_step, Mapping) else None,
            "cleanup": preflight_rep.get("cleanup")}
    steps_summary = [{"step_name": str(getattr(s, "step_name", "")), "status": str(getattr(s, "status", "")),
                      "duration_seconds": round(float(getattr(s, "duration_seconds", 0.0)), 3)} for s in step_results]
    req_labels = [LABEL_D12_GRANT_ID, LABEL_D12_SOURCE_SHA256, LABEL_D12_RECIPE_SHA256]
    cand_id = {"candidate_sha": config.candidate_commit_sha, "candidate_tree": config.candidate_tree_sha,
               "candidate_base_parent": config.candidate_base_parent,
               "candidate_head_parent": config.candidate_head_parent, "pr_number": config.pr_number,
               "approval_id": config.approval_id, "repository": config.repository}
    cand_img = {"image_id": candidate_image_id or session.image_id, "image_tag": config.candidate_tag,
                "image_digest": candidate_image_digest or None, "required_d12_labels": req_labels,
                "labels": dict(candidate_image_labels) if candidate_image_labels else None}
    p_ass = dict(session.post_build_assessments) if session.post_build_assessments is not None else None
    p_prb = dict(session.post_build_probes) if session.post_build_probes is not None else None
    p_rt = dict(session.roundtrip_evidence) if session.roundtrip_evidence is not None else None
    payload: dict[str, Any] = {
        "schema": SYSTEM_CANDIDATE_EVIDENCE_SCHEMA, "phase": EXPECTED_PHASE_ID, "route": "B",
        "gate_kind": config.gate_kind, "execution_mode": config.execution_mode, "run_id": config.run_id,
        "grant_id": session.grant_id, "reservation_id": session.grant_id,
        "reservation_sha256": str(session.grant.get("reservation_sha256", "")), "grant_sha256": session.grant_sha256,
        "proof_sha256": session.proof_sha256, "expected_candidate_sha256": session.expected_candidate_sha256,
        "preflight_sha256": session.preflight_sha256, "intent_sha256": session.intent_sha256,
        "intent": dict(session.intent_payload) if session.intent_payload is not None else None,
        "candidate_identity": cand_id, "d12_context": dict(session.proof.get("d12_context") or {}),
        "sdk_sandbox": dict(session.expected_candidate.get("sdk_sandbox") or {}),
        "release_manifest": dict(session.proof.get("release_manifest") or {}),
        "candidate_image": cand_img, "same_daemon_preflight": preflight_summary,
        "post_build_probes": p_prb, "post_build_assessments": p_ass, "disposable_roundtrip": p_rt,
        "scenario_summary": {"diagnostic_steps_passed": bool(diagnostic_steps_passed), "step_count": len(step_results),
                             "steps": steps_summary, "mcp_readback_digest": mcp_readback_digest or None},
        "cleanup_evidence": {"cleanup_succeeded": cleanup_ok, "cleanup_status": dict(cleanup_status),
                             "temp_container_cleanup_errors": list(temp_cleanup_errors)},
        "failures": failures, "diagnostic_steps_passed": bool(diagnostic_steps_passed), "cleanup_succeeded": cleanup_ok,
        "image_accepted": False, "p3_accepted": False, "merge_authorized": False, "qualified": False,
    }
    validated = validate_d12_system_candidate_evidence(payload)
    target_dirs = [t for t in (config.report_dir, evidence_dir) if t is not None]
    try:
        return write_bounded_json_to_targets(
            target_dirs, SYSTEM_CANDIDATE_EVIDENCE_FILENAME, validated, part_limit=d12.REPORT_PART_LIMIT,
            total_limit=d12.REPORT_TOTAL_LIMIT, cleanup_reserve=d12.REPORT_CLEANUP_RESERVE)
    except ValueError as exc:
        raise SystemTestError(str(exc)) from exc
