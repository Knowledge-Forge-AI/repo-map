"""Native adapter using current controller, audit, discovery and boundary contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
import shutil
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from common_lore_index.extractors.rust_pilot.controller import RustPilotController
PLATFORM_FACTS = {"linux/amd64": ("x86_64", "amd64"), "linux/arm64": ("aarch64", "arm64")}


class RuntimeGap(RuntimeError):
    def __init__(self, code: str, evidence: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code, self.evidence = code, dict(evidence or {})


def _value(item: object, name: str, default: Any = None) -> Any:
    return getattr(item, name, default)


def _claim(item: object) -> dict[str, Any]:
    metadata = dict(_value(item, "metadata", {}))
    return {"end_byte": metadata["end_byte"], "end_line": _value(item, "end_line"),
            "item_kind": metadata["item_kind"], "name": _value(item, "name"),
            "namespace": metadata["namespace"], "pointer": metadata["pointer"],
            "start_byte": metadata["start_byte"], "start_line": _value(item, "start_line"),
            "usable_scope": metadata["usable_scope"]}


def _document(relative: str, data: bytes, observations: Sequence[object],
              fallback: str, scenario: str) -> dict[str, Any]:
    parse = next((item for item in observations if _value(item, "kind") == "rust.parse"), None)
    metadata = dict(_value(parse, "metadata", {})) if parse is not None else {}
    unsupported = []
    for item in observations:
        if _value(item, "kind") == "rust.unsupported":
            details = dict(_value(item, "metadata", {}))
            unsupported.append({key: details[key] for key in ("construct", "count", "scope_pointer")})
    return {
        "build_script_name": relative.rsplit("/", 1)[-1] == "build.rs",
        "completeness": metadata.get("completeness", "none"), "fixture": relative,
        "input_bytes": len(data), "input_sha256": hashlib.sha256(data).hexdigest(),
        "item_list": metadata.get("item_list"),
        "items": [_claim(item) for item in observations if _value(item, "kind") == "rust.item"],
        "line_count": metadata.get("line_count", data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)),
        "outcome": metadata.get("outcome", fallback), "scenarios": [scenario],
        "schema": "cloe-rust-pilot-gold-v1", "unsupported": unsupported,
    }


def compare_gold_claims(controller: RustPilotController, summary: object, fixture_root: Path,
                        source_paths: Sequence[str], manifest: Mapping[str, Any]) -> dict[str, Any]:
    outcomes = dict(getattr(summary, "file_outcomes", ()))
    fixture, files = manifest["fixture"], manifest["fixture"]["files"]
    result, claims = [], 0
    for relative in source_paths:
        entry = files[relative]
        try:
            data = (fixture_root / relative).read_bytes()
            gold_path = fixture_root / entry["gold"]
            gold_bytes = gold_path.read_bytes()
            gold = json.loads(gold_bytes.decode("utf-8"))
            admission = controller.admit(relative)
        except (OSError, UnicodeDecodeError, ValueError):
            raise RuntimeGap("gold_read_failed") from None
        required = {"build_script_name", "completeness", "fixture", "input_bytes", "input_sha256",
                    "item_list", "items", "line_count", "outcome", "scenarios", "schema", "unsupported"}
        if set(gold) != required or gold.get("schema") != "cloe-rust-pilot-gold-v1":
            raise RuntimeGap("gold_schema")
        if gold.get("input_sha256") != entry["sha256"] or gold.get("scenarios") != [entry["scenario"]]:
            raise RuntimeGap("gold_binding")
        actual = _document(relative, data, tuple(getattr(admission, "observations", ())),
                           outcomes.get(relative, "not_executed"), entry["scenario"])
        if actual != gold:
            mismatched = tuple(sorted(key for key in required if actual.get(key) != gold.get(key)))
            actual_bytes = json.dumps(actual, sort_keys=True, separators=(",", ":")).encode("utf-8")
            expected_bytes = json.dumps(gold, sort_keys=True, separators=(",", ":")).encode("utf-8")
            raise RuntimeGap("gold_mismatch", {
                "fixture": relative, "gold": entry["gold"],
                "gold_file_sha256": hashlib.sha256(gold_bytes).hexdigest(),
                "gold_document_sha256": hashlib.sha256(expected_bytes).hexdigest(),
                "actual_document_sha256": hashlib.sha256(actual_bytes).hexdigest(),
                "mismatched_fields": list(mismatched)})
        if gold["outcome"] == "input_not_utf8":
            if getattr(admission, "observations", ()):
                raise RuntimeGap("invalid_utf8_was_executed")
        elif not getattr(admission, "observations", ()):
            raise RuntimeGap("admission_missing")
        claims += len(actual["items"])
        result.append({"fixture": relative, "outcome": actual["outcome"], "item_claims": len(actual["items"])})
    if claims != fixture["expected_item_claims"]:
        raise RuntimeGap("gold_claim_count")
    return {"files": result, "item_claims": claims, "source": "native_controller_admissions"}


def _audit(controller: RustPilotController, source_paths: Sequence[str],
           fixture: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from ci.qualification_rust_scenarios import AuditGap, audit_snapshot
    try:
        return audit_snapshot(controller, source_paths, fixture)
    except AuditGap as error:
        raise RuntimeGap(error.code, error.evidence) from None


def _legacy_measure(root: Path, source_paths: Sequence[str],
                    tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    from common_lore_index.canonicalization.main import canonicalize_observations
    from common_lore_index.graph.discovery import discover_repository, extract_observations_from_repository_files
    from common_lore_index.graph.keys import file_key, parse_key

    started = time.monotonic()
    source_set = set(source_paths)
    infos = [info for info in discover_repository(root) if info.path in source_set]
    observations = extract_observations_from_repository_files(root, infos)
    elapsed_ms = round((time.monotonic() - started) * 1000)
    result = canonicalize_observations(observations, repository_scope="rust-pilot-qualified")
    if not result.ok:
        raise RuntimeGap("legacy_canonicalization_failed")
    nodes = [node for node in result.graph.nodes
             if node.kind == "file" and node.display_name in source_set]
    if {node.display_name for node in nodes} != source_set:
        raise RuntimeGap("legacy_file_only_mismatch")

    def matches(node: object, task: Mapping[str, Any]) -> bool:
        if (getattr(node, "kind", None) != task.get("namespace")
                or getattr(node, "display_name", None) != task.get("name")):
            return False
        try:
            key = parse_key(getattr(node, "canonical_key"))
        except (TypeError, ValueError):
            return False
        return bool(key.segments) and key.segments[0] == file_key(str(task["fixture"]))

    navigation = {str(task["incumbent_key"]): any(matches(node, task)
                                                   for node in result.graph.nodes)
                  for task in tasks}
    digests = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in source_paths}
    file_nodes = {path: sum(1 for node in nodes if node.display_name == path) for path in source_paths}
    item_nodes = {path: sum(1 for node in result.graph.nodes
                            if node.kind.startswith("rust.") and node.kind != "rust.source_file"
                            and matches(node, {"fixture": path,
                                                                                 "name": node.display_name,
                                                                                 "namespace": node.kind}))
                  for path in source_paths}
    graph = result.graph
    return {"schema": "cloe-rust-pilot-actual-file-only-v1", "discovery_ms": elapsed_ms,
            "input_digests": digests, "file_nodes": file_nodes, "item_nodes": item_nodes,
            "navigation": navigation, "composition_limitation": "legacy .rs is file-only",
            "graph_quality": {"raw_observations": graph.raw_observation_count,
                              "nodes": len(graph.nodes), "edges": len(graph.edges),
                              "evidence": len(graph.evidence)},
            "_observations": tuple(observations), "_result": result}


def _incumbent(repo_root: Path, source_paths: Sequence[str],
               descriptor: Mapping[str, Any], measured: Mapping[str, Any]) -> dict[str, Any]:
    try:
        data = (repo_root / descriptor["report_path"]).read_bytes()
        report = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise RuntimeGap("incumbent_evidence_unavailable") from None
    if hashlib.sha256(data).hexdigest() != descriptor["sha256"] or report.get("schema") != descriptor["schema"]:
        raise RuntimeGap("incumbent_digest_or_schema")
    if report.get(descriptor["input_digests_key"]) != measured["input_digests"]:
        raise RuntimeGap("incumbent_input_mismatch")
    if report.get(descriptor["files_key"]) != measured["file_nodes"]:
        raise RuntimeGap("incumbent_file_measurement_mismatch")
    if report.get(descriptor["items_key"]) != measured["item_nodes"]:
        raise RuntimeGap("incumbent_measurement_mismatch")
    if report.get(descriptor["navigation_key"]) != measured["navigation"]:
        raise RuntimeGap("incumbent_navigation_mismatch")
    if report.get(descriptor["graph_quality_key"]) != measured["graph_quality"]:
        raise RuntimeGap("incumbent_graph_quality_mismatch")
    discovery_ms = report.get(descriptor["discovery_ms_key"])
    if not isinstance(discovery_ms, (int, float)) or isinstance(discovery_ms, bool) or discovery_ms < 0:
        raise RuntimeGap("incumbent_discovery_time_missing")
    return {"source": "actual_incumbent_report", "report": report,
            "discovery_ms": discovery_ms, "observed_discovery_ms": measured["discovery_ms"],
            "files": len(source_paths), "item_claims": sum(measured["item_nodes"].values())}


def _navigation(candidate_graph: object, source_paths: Sequence[str], tasks: Sequence[Mapping[str, Any]],
                measured: Mapping[str, Any]) -> dict[str, Any]:
    from common_lore_index.graph.keys import file_key, parse_key

    if len(tasks) != 5:
        raise RuntimeGap("navigation_task_count")
    nodes = tuple(getattr(candidate_graph, "nodes", ()))
    answers = []
    for task in tasks:
        fixture, name, namespace, key = (task.get(field) for field in
                                         ("fixture", "name", "namespace", "incumbent_key"))
        if fixture not in source_paths:
            raise RuntimeGap("navigation_fixture")
        candidate = False
        for node in nodes:
            if (getattr(node, "kind", None) != namespace
                    or getattr(node, "display_name", None) != name):
                continue
            try:
                parsed = parse_key(getattr(node, "canonical_key"))
            except (TypeError, ValueError):
                continue
            if parsed.segments and parsed.segments[0] == file_key(str(fixture)):
                candidate = True
                break
        incumbent = measured.get("navigation", {}).get(key, False)
        if not isinstance(incumbent, bool):
            raise RuntimeGap("navigation_value")
        answers.append({"key": key, "fixture": fixture, "candidate": candidate, "incumbent": incumbent,
                        "delta": candidate != incumbent})
    return {"task_count": len(answers), "tasks": answers, "claim": "curated-navigation-only"}


def _graph_quality(candidate_graph: object, measured: Mapping[str, Any]) -> dict[str, Any]:
    incumbent = measured.get("graph_quality")
    if not isinstance(incumbent, Mapping):
        raise RuntimeGap("incumbent_graph_quality_missing")
    graph = candidate_graph
    candidate = {"raw_observations": int(getattr(graph, "raw_observation_count", -1)),
                 "nodes": len(getattr(graph, "nodes", ())), "edges": len(getattr(graph, "edges", ())),
                 "evidence": len(getattr(graph, "evidence", ())),
                 "rust_nodes": sum(1 for node in getattr(graph, "nodes", ())
                                    if getattr(node, "kind", "").startswith("rust."))}
    if any(not isinstance(incumbent.get(key), int) for key in ("raw_observations", "nodes", "edges", "evidence")):
        raise RuntimeGap("incumbent_graph_quality_shape")
    def legacy_rows(value: object) -> dict[str, Any]:
        graph_value = value
        rust_keys = {node.canonical_key for node in getattr(graph_value, "nodes", ())
                     if getattr(node, "kind", "").startswith("rust.")}
        edges = tuple(edge for edge in getattr(graph_value, "edges", ())
                      if edge.source_key not in rust_keys and edge.target_key not in rust_keys)
        edge_keys = {edge.edge_key for edge in edges}
        return {
            "nodes": sorted((node.to_dict() for node in getattr(graph_value, "nodes", ())
                             if node.canonical_key not in rust_keys), key=lambda row: row["canonical_key"]),
            "edges": sorted((edge.to_dict() for edge in edges), key=lambda row: row["edge_key"]),
            "evidence": sorted((item.to_dict() for item in getattr(graph_value, "evidence", ())
                                if not item.raw_kind.startswith("rust.")),
                               key=lambda row: row["evidence_key"]),
            "node_evidence_links": sorted((item.to_dict() for item in getattr(graph_value, "node_evidence_links", ())
                                           if item.canonical_key not in rust_keys),
                                          key=lambda row: (row["canonical_key"], row["evidence_key"], row["link_kind"])),
            "edge_evidence_links": sorted((item.to_dict() for item in getattr(graph_value, "edge_evidence_links", ())
                                           if item.edge_key in edge_keys),
                                          key=lambda row: (row["edge_key"], row["evidence_key"], row["link_kind"])),
        }
    legacy = legacy_rows(measured["_result"].graph)
    witnessed_legacy = legacy_rows(graph)
    legacy_bytes = json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    witnessed_bytes = json.dumps(witnessed_legacy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if legacy_bytes != witnessed_bytes:
        raise RuntimeGap("legacy_rows_changed", {
            "legacy_sha256": hashlib.sha256(legacy_bytes).hexdigest(),
            "witnessed_sha256": hashlib.sha256(witnessed_bytes).hexdigest()})
    return {"incumbent": dict(incumbent), "witnessed_candidate": candidate,
            "delta": {key: candidate[key] - incumbent[key] for key in ("raw_observations", "nodes", "edges", "evidence")},
            "legacy_invariance": {"schema": "rust-pilot-legacy-family-rows-v1", "byte_identical": True,
                                  "sha256": hashlib.sha256(legacy_bytes).hexdigest(),
                                  "row_counts": {key: len(value) for key, value in legacy.items()}}}


def _public_measurement(measured: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in measured.items() if not key.startswith("_")}


def _containment(docker_cli: str, image_id: str, profile_dir: Path, *, platform: str,
                 work_deadline: float | None = None) -> dict[str, Any]:
    from ci.qualification_rust_scenarios import native_containment
    return native_containment(docker_cli, image_id, profile_dir, platform=platform,
                              work_deadline=work_deadline)


def run_native_component(repo_root: Path, fixture_root: Path, profile_dir: Path, image_id: str,
                         audit_dir: Path, manifest: Mapping[str, Any], *,
                         platform: str = "linux/amd64", cross_cpu_profile: Path | None = None,
                         work_deadline: float | None = None) -> dict[str, Any]:
    from ci.qualification_rust_import_guard import host_import_guard
    from ci.qualification_rust_shape import source_digests
    from ci.qualification_rust_shape import command_work_deadline, require_work_deadline
    work_deadline = command_work_deadline(work_deadline)
    require_work_deadline(work_deadline)
    with host_import_guard(repo_root, source_digests(manifest["closure"])):
        return _run_native_component(repo_root, fixture_root, profile_dir, image_id, audit_dir, manifest,
                                      platform=platform, cross_cpu_profile=cross_cpu_profile, work_deadline=work_deadline)


def _run_native_component(repo_root: Path, fixture_root: Path, profile_dir: Path, image_id: str,
                          audit_dir: Path, manifest: Mapping[str, Any], *, platform: str,
                          cross_cpu_profile: Path | None, work_deadline: float) -> dict[str, Any]:
    from ci.qualification_rust_shape import require_work_deadline
    require_work_deadline(work_deadline)
    profile_cpu, docker_arch = PLATFORM_FACTS.get(platform, (None, None))
    if profile_cpu is None or docker_arch is None:
        raise RuntimeGap("unsupported_platform")
    from common_lore_index.extractors.contracts.vocabulary import ContractError
    from common_lore_index.extractors.rust_pilot.prepared_profile import load_profile
    try:
        expected_profile = manifest["closure"]["profile_digests"][docker_arch]
    except (KeyError, TypeError):
        raise RuntimeGap("profile_binding_missing") from None
    try:
        profile = load_profile(profile_dir, server_cpu=profile_cpu)
    except (ContractError, OSError, ValueError):
        raise RuntimeGap("profile_unavailable") from None
    if profile.profile_sha256 != expected_profile:
        raise RuntimeGap("profile_digest_mismatch")
    docker_cli = shutil.which("docker")
    if not docker_cli:
        raise RuntimeGap("docker_unavailable")
    from common_lore_index.extractors.rust_pilot.controller import RustPilotController
    from common_lore_index.graph.discovery_records import FileInfo
    from common_lore_index.canonicalization.rust_pilot_family import canonicalize_rust_pilot
    from ci.qualification_rust_cleanup import close_native_controller, native_failure
    from ci.qualification_rust_accounting import require_component_accounting
    from ci.qualification_rust_scenarios import preflight_scenarios
    source_paths = tuple(path for path in manifest["fixture"]["files"] if not path.startswith("golds/"))
    infos = [FileInfo(path, "unknown", "source", manifest["fixture"]["files"][path]["sha256"], False, False)
             for path in source_paths]
    preflights = preflight_scenarios(fixture_root, infos, docker_cli=docker_cli, image_id=image_id,
                                     profile_dir=profile_dir, audit_dir=audit_dir, platform=platform,
                                     cross_cpu_profile=cross_cpu_profile, work_deadline=work_deadline)
    require_work_deadline(work_deadline)
    if (not isinstance(preflights, Mapping)
            or any(not isinstance(item, Mapping) or item.get("passed") is not True
                   for item in preflights.values())):
        raise RuntimeGap("scenario_refusal_not_proven", {"preflights": preflights})
    containment = _containment(docker_cli, image_id, profile_dir, platform=platform, work_deadline=work_deadline)
    require_work_deadline(work_deadline)
    controller = RustPilotController(docker_cli=docker_cli, sdk_image_id=image_id,
                                     profile_dir=profile_dir, platform=platform, audit_dir=audit_dir)
    controller._boundary.limit_work_deadline(work_deadline)
    original_gap: RuntimeGap | None = None
    audited: dict[str, Any] | None = None
    try:
        summary = controller.process(fixture_root, infos)
        require_work_deadline(work_deadline)
        if summary.run_outcome != "processed" or not controller.verify_live():
            raise RuntimeGap("controller_not_processed", {"audit": controller.audit_snapshot(),
                                                         "run_outcome": summary.run_outcome})
        snapshot, audited = _audit(controller, source_paths, manifest["fixture"])
        if controller.helper_closure_sha256 != manifest["closure"]["helper_closure_sha256"]:
            raise RuntimeGap("helper_closure_mismatch", snapshot)
        gold = compare_gold_claims(controller, summary, fixture_root, source_paths, manifest)
        require_work_deadline(work_deadline)
        measured = _legacy_measure(fixture_root, source_paths, manifest["navigation"]["tasks"])
        require_work_deadline(work_deadline)
        incumbent = _incumbent(repo_root, source_paths, manifest["incumbent"], measured)
        require_work_deadline(work_deadline)
        witnessed = canonicalize_rust_pilot(controller, measured["_observations"],
                                            repository_scope="rust-pilot-qualified")
        if not witnessed.verify_live():
            raise RuntimeGap("witnessed_graph_live_check_failed")
        candidate_graph = witnessed.result.graph
        navigation = _navigation(candidate_graph, source_paths, manifest["navigation"]["tasks"], measured)
        graph_quality = _graph_quality(candidate_graph, measured)
        if not controller.verify_live():
            raise RuntimeGap("controller_live_recheck_failed", snapshot)
        result = {"run_id": snapshot["run_id"], "audit": snapshot, "gold": gold, "preflights": preflights,
                "incumbent": incumbent, "incumbent_measurement": _public_measurement(measured),
                "navigation": navigation, "graph_quality": graph_quality, "containment": containment,
                "costs": audited["costs"], "counters": audited["counters"],
                "evidence_source": "native_controller_audit"}
        require_work_deadline(work_deadline)
        result["accounting"] = require_component_accounting(result)
        require_work_deadline(work_deadline)
        return result
    except Exception as error:
        original_gap = native_failure(controller, error, audited, preflights, containment)
        raise original_gap from None
    finally:
        close_native_controller(controller, original_gap)
