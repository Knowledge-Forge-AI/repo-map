"""ADR 0102 native Python 3.12.16 component observer: one network-less container on the exact raw config.

A dedicated create, readback, cleanup and verify sequence; E1's action-before-cleanup helper is never reused. The
mutable record is installed before execution and stays ``refused`` until complete ledger and Engine cleanup and a
zero run-boundary operation delta are proved. Recoverable failures stay in this record, never in E1's refusals;
process-control aborts keep it, clean up exactly and propagate. Public evidence holds no container ID, private host
path or raw stderr. Nothing here qualifies an image, P3, the whole preflight or a default enrollment.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from repomap_kg.runtime import python_payload as payload
from repomap_test_support import d12_native_python_proof as proof
from repomap_test_support.resource_docker_operation_records import DERIVED_OPERATION_FIELDS

SLOT, ROLE = "python31216_component", "d12-python31216-component"
WAIT_SECONDS = 900
REPO_ROOT = Path(__file__).resolve().parents[1]


def new_record(platform: str) -> dict[str, Any]:
    """The refused-by-default slot, installed before any Docker access."""
    return {"schema": proof.COMPONENT_SCHEMA, "status": "refused", "stage": "installed", "platform": platform,
            "requested_platform_source": "admission", "reasons": [], "operations": {},
            "cleanup": {"verified": False}, "qualification": dict(proof.NON_QUALIFICATION)}


def observe_exploration(steps: MutableMapping[str, Any], client: Any, owner: Any, admission: Any, *,
                        exploration: Any, environ: Mapping[str, str] = os.environ) -> dict[str, Any] | None:
    """E1 hook after native engine facts: only the current exploration admission, never build or system mode."""
    if exploration is None or admission is not exploration:
        return None
    record = steps[SLOT] = new_record(str(admission.platform))
    record["closure_cross_check"] = {"result": "not_run", "fields": []}  # A6: replaced only after the closure step
    try:
        from repomap_test_support import d12_core_image as d12
        from repomap_test_support.resource_run import active_resource_run

        boundary, run = d12.locate_run_boundary(), active_resource_run()
        if run is None:
            raise proof.NativeComponentError("no canonical resource run is active")
    except Exception as error:
        record["reasons"].append(proof.public_reason("boundary", error))
        return record
    return observe_component(record, client=client, owner=owner, run=run, boundary=boundary,
                             platform=str(admission.platform), environ=environ, require_override=True)


def cross_check(steps: MutableMapping[str, Any]) -> None:
    """A6: a conflict with the legacy closure's raw baseline stays in the component channel."""
    record = steps.get(SLOT)
    if not isinstance(record, dict):
        return
    try:
        result = record["closure_cross_check"] = closure_cross_check(record.get("raw_report"), steps.get("closure"))
        if result["result"] == "conflict":
            record["status"] = "refused"
            record["reasons"].append(f"closure: the legacy raw baseline conflicts on {result['fields']}")
    except Exception as error:
        record["status"] = "refused"
        record["reasons"].append(proof.public_reason("closure", error))


def observe_component(record: dict[str, Any], *, client: Any, owner: Any, run: Any, boundary: Any, platform: str,
                      environ: Mapping[str, str], require_override: bool, repo_root: Path = REPO_ROOT,
                      wait_seconds: int = WAIT_SECONDS, record_limit: int = proof.RECORD_LIMIT) -> dict[str, Any]:
    """Probe once, then always clean up and verify; an abort is re-raised only after that custody."""
    state: dict[str, Any] = {"cid": None, "known": None, "before": None}
    abort: BaseException | None = None
    try:
        _stage(record, "boundary")
        state["before"] = record["operations"]["before"] = operation_counts(boundary.projection())
        if getattr(owner, "ledger", None) is not run.ledger:
            raise proof.NativeComponentError("the container owner is not bound to the live run ledger")
        state["known"] = _ledger_containers(run)
        _probe(record, state, client, owner, platform=platform, environ=environ, require_override=require_override,
               repo_root=repo_root, wait_seconds=wait_seconds)
    except Exception as error:
        record["reasons"].append(proof.public_reason(record["stage"], error))
    except BaseException as error:
        abort = error
        record["reasons"].append(proof.public_reason(f"{record['stage']} aborted", error))
    finally:
        _finish(record, state, owner, run, boundary)
        bound_record(record, limit=record_limit)
    if abort is not None:
        raise abort
    return record


def _stage(record: dict[str, Any], name: str) -> None:
    record["stage"] = name


def _ledger_containers(run: Any) -> list[Any]:
    from repomap_test_support.resource_ledger import ResourceKind

    return [item for item in run.ledger.records if item.kind is ResourceKind.DOCKER_CONTAINER]


def _probe(record: dict[str, Any], state: dict[str, Any], client: Any, owner: Any, *, platform: str,
           environ: Mapping[str, str], require_override: bool, repo_root: Path, wait_seconds: int) -> None:
    _stage(record, "daemon")
    architecture = proof.require_native(str((client.info() or {}).get("Architecture") or ""), platform)
    record["daemon"] = {"architecture": architecture, "native": True}
    _stage(record, "defaults")
    record["defaults"] = proof.held_defaults(architecture)
    _stage(record, "envelope")
    hierarchy = proof.verify_hierarchy(proof.read_envelope(repo_root), platform)
    record["envelope"] = {"path": proof.ENVELOPE_PATH, "sha256": proof.ENVELOPE_SHA256, "verified": True}
    _stage(record, "override")
    record["override"] = proof.verify_override(environ.get(proof.RAW_OVERRIDE_ENV), hierarchy,
                                               required=require_override)
    _stage(record, "image")
    record["provenance"] = proof.verify_image(client.images.get(hierarchy["config"]).attrs, hierarchy)
    source = Path(payload.__file__).read_bytes()
    record["payload_source_sha256"] = hashlib.sha256(source).hexdigest()
    script = proof.build_inner_script(source, architecture)
    _stage(record, "create")
    state["cid"] = owner.create(hierarchy["config"], ["-I", "-B", "-c", script], role=ROLE,
                                entrypoint=["python3"], network_mode="none", environment={})
    container = client.containers.get(state["cid"])
    attrs = container.attrs
    if attrs.get("Image") != hierarchy["config"] or (attrs.get("HostConfig") or {}).get("NetworkMode") != "none":
        raise proof.NativeComponentError("the created container is not the exact network-less config")
    record["container"] = {"network": "none", "readback_verified": True}
    _stage(record, "execute")
    container.start()
    status = (container.wait(timeout=wait_seconds) or {}).get("StatusCode")
    stdout = container.logs(stdout=True, stderr=False)
    stderr = container.logs(stdout=False, stderr=True)
    record["container"].update(exit_status=status, stdout=proof.integrity(stdout), stderr=proof.integrity(stderr))
    _stage(record, "capture")
    lines = proof.capture_lines(stdout)
    if (inner_error := proof.parse_error(lines)) is not None:
        record["inner_error"] = inner_error  # the redacted uncaught inner exception, kept before later checks
    raw = proof.parse_raw(lines)
    record["raw_report"] = raw["report"]  # the actual raw observation, retained before any later check can fail
    inner = proof.parse_inner(lines)
    record["trimmed_report"] = inner["trimmed_report"]
    record["inner"] = {key: value for key, value in inner.items() if key != "trimmed_report"}
    _stage(record, "validate")
    if type(status) is not int or status != 0:
        raise proof.NativeComponentError(f"the inner probe exited {status!r}")
    record["summary"] = proof.validate_observation(raw, inner, architecture)


def _finish(record: dict[str, Any], state: dict[str, Any], owner: Any, run: Any, boundary: Any) -> None:
    from repomap_test_support.resource_ledger import ResourceKind

    cleanup = record["cleanup"] = {"verified": False}
    try:
        known, cid = state["known"], state["cid"]
        fresh = [] if known is None else [item.identity for item in _ledger_containers(run)
                                          if all(item.identity != old.identity for old in known)]
        # The exact returned ID; after a create whose readback failed post-ledgering, only a sole new ledger ID.
        for identity in [cid] if cid is not None else fresh if len(fresh) == 1 else []:
            if run.ledger.get(ResourceKind.DOCKER_CONTAINER, identity).cleanup_result.value == "removed":
                continue
            if cid is None and owner.api.inspect(ResourceKind.DOCKER_CONTAINER, identity) is None:
                owner.observe_removed(identity)  # create's own exact rollback removed it; close that ledger record
            else:
                owner.cleanup(identity)
        owner.verify_baseline()
        if (cid is not None and fresh != [cid]) or len(fresh) > 1:
            raise proof.NativeComponentError(f"{len(fresh)} new ledger containers; the component owns exactly one")
        rows = [(entry.cleanup_result.value, entry.final_presence.value, entry.creation_observed) for entry in (
            run.ledger.get(ResourceKind.DOCKER_CONTAINER, identity) for identity in fresh)]
        absent = [owner.api.inspect(ResourceKind.DOCKER_CONTAINER, identity) is None for identity in fresh]
        cleanup.update(validate_cleanup(rows, absent, created=cid is not None, baseline_verified=True))
    except Exception as error:
        record["reasons"].append(proof.public_reason("cleanup", error))
    operations = record["operations"]
    try:
        operations["after"] = operation_counts(boundary.projection())
        if state["before"] is None:
            raise proof.NativeComponentError("no pre-component boundary projection was observed")
        operations["delta"] = operation_delta(state["before"], operations["after"])
    except Exception as error:
        record["reasons"].append(proof.public_reason("operations", error))
    complete = cleanup["verified"] is True and operations.get("delta") == {} and "summary" in record
    record["status"] = "observed" if complete and not record["reasons"] else "refused"


def operation_counts(projection: Any) -> dict[str, int]:
    if not isinstance(projection, Mapping) or set(DERIVED_OPERATION_FIELDS) - set(projection):
        raise proof.NativeComponentError("the run-boundary projection lacks operation fields")
    if any(not isinstance(key, str) or type(value) is not int or value < 0 for key, value in projection.items()):
        raise proof.NativeComponentError("run-boundary counts must be non-negative integers")
    return {key: value for key, value in sorted(projection.items())}


def operation_delta(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    if before.keys() != after.keys():
        raise proof.NativeComponentError("run-boundary fields changed during the component")
    if delta := {key: after[key] - before[key] for key in before if after[key] != before[key]}:
        raise proof.NativeComponentError(f"the component requires a zero Docker operation delta: {delta}")
    return {}


def validate_cleanup(entries: Sequence[tuple[str, str, bool]], engine_absent: Sequence[bool], *, created: bool,
                     baseline_verified: bool) -> dict[str, Any]:
    """Ledger readback (result, presence, observed creation) and Engine absence for every new component record."""
    rows = [tuple(item) for item in entries]
    if (created and len(rows) != 1) or len(rows) > 1 or len(engine_absent) != len(rows):
        raise proof.NativeComponentError(f"component ledger custody is ambiguous: {len(rows)} new container records")
    if any(row != ("removed", "absent", True) for row in rows) or not all(
            item is True for item in engine_absent) or baseline_verified is not True:
        raise proof.NativeComponentError(f"component cleanup is incomplete: {rows}")
    return {"verified": True, "container_created": created, "ledger_containers": len(rows), "removed": len(rows),
            "engine_absent": True, "baseline_verified": True}


def closure_cross_check(raw_report: Any, closure: Any) -> dict[str, Any]:
    """A6: the legacy closure's raw baseline against the independent component observation."""
    legacy = closure.get("baseline") if isinstance(closure, Mapping) else None
    observed = raw_report.get("baseline") if isinstance(raw_report, Mapping) else None
    if not isinstance(legacy, Mapping) or not isinstance(observed, Mapping):
        return {"result": "unavailable", "fields": []}
    conflicts = [key for key in ("entries", "digest", "imports") if legacy.get(key) != observed.get(key)]
    return {"result": "conflict" if conflicts else "consistent", "fields": conflicts}


def nested_size(record: Mapping[str, Any]) -> int:
    """Bytes as the exploration writer indents the slot (report -> steps -> component)."""
    text = json.dumps({"steps": {"component": record}}, indent=2, sort_keys=True, default=str)
    return len(text.encode("utf-8"))


def bound_record(record: dict[str, Any], *, limit: int = proof.RECORD_LIMIT) -> dict[str, Any]:
    """Keep the exploration report writable: oversized evidence becomes a compact refusal with integrity facts."""
    size = nested_size(record)
    if size <= limit:
        return record
    for key in ("raw_report", "trimmed_report", "inner", "summary"):
        if key in record:
            text = json.dumps(record[key], sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            record[key] = {"omitted": True, **proof.integrity(text)}
    record.update(status="refused", overflow={"bytes": size, "limit": limit})
    record["reasons"] = [*record.get("reasons", [])[:8], f"bound: component evidence {size} bytes exceeds {limit}"]
    if nested_size(record) > limit:
        kept = ("schema", "status", "stage", "platform", "overflow", "qualification")
        record_items = {key: record[key] for key in kept if key in record}
        record.clear()
        record.update(record_items, reasons=[f"bound: component evidence {size} bytes exceeds {limit}"])
    return record
