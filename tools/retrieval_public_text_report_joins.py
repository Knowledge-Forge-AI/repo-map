"""Generation, cell and cleanup joins and evidence-context verification for the report (sections 18.4-18.5).

Structural joins need only the report bytes: census to preparation, request to
seal and preparation, seal to component, imports/indexes to seal and fences,
learned cells to decisions, seals, imports, indexes and fences, and cleanup to
the recorded inventory. Raw-evidence verification additionally needs the actual
component journal, model members and selected task objects; without them the
reader is structural only and never reasserts a stored verification flag.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import cast, Any

from retrieval_public_text_census import retained_task_sha256, task_sha256
from retrieval_public_text_contracts import PrivateMarkerScope
from retrieval_public_text_report_cells import LEARNED_ARMS
from retrieval_public_text_report_contracts import (
    GENERATION_FIELDS, RECEIPT_ROLES, PublicTextReportRefusal, arm_rows, closed, digest, require, validate_census,
    validate_component_status, validate_elapsed, validate_fences, validate_imports, validate_indexes,
    validate_preparation, validate_request, validate_seal,
)
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_tasks import SelectedTaskPins, SelectedTaskSet, registered_task_pins
from retrieval_semantic_component_dossier_contract import MAX_DOSSIER_BYTES, validate_component
from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_generator_output_parser import parse_verified_worker_response
from retrieval_semantic_generator_output_receipt import read_worker_archive_inputs
from retrieval_semantic_generator_worker_contracts import WorkerRequestError
from retrieval_semantic_pair_artifacts import JournalArtifact, PairReportRefusal, parse_json_object
from retrieval_semantic_pair_v2_cost import component_counts
from retrieval_semantic_provenance import RepresentationValidationError
from retrieval_semantic_raw_component import verify_raw_component
from retrieval_semantic_raw_component_anchors import canonical_anchors

NOT_RECORDED_COMPONENT = {
    "recorded": "not_recorded", "recorded_counts": None, "recorded_component_digests": None,
    "supplied": "not_supplied", "correspondence": "unknown", "artifact_correspondence_verified": None,
    "verified_counts": None, "verified_component_digests": None,
}


def component_evidence(journal: JournalArtifact | None, members: Mapping[str, bytes] | None,
                       *, reason: str | None = None) -> dict[str, Any]:
    """Actual raw-component correspondence, or an explicit ``not_recorded`` reason; never a synthetic success."""
    if journal is None or members is None:
        require(type(reason) is str and reason.startswith("component_"), "report_component_reason")
        return {"component_status": {"state": "not_recorded", "reason": reason},
                "component": dict(NOT_RECORDED_COMPONENT), "elapsed_seconds": {"unknown": "component_not_recorded"}}
    try:
        summary = verify_raw_component(journal, members)
        anchors = canonical_anchors(journal)
        recorded = component_counts(journal)["values"]
        report = parse_json_object(members["report.json"], code_prefix="report_component")
    except PairReportRefusal as error:
        raise PublicTextReportRefusal("report_component:" + error.code[:80]) from None
    component = {
        "recorded": "recorded" if recorded is not None else "not_recorded", "recorded_counts": recorded,
        "recorded_component_digests": dict(anchors.digests), "supplied": "supplied", "correspondence": "verified",
        "artifact_correspondence_verified": True, "verified_counts": dict(summary.counts),
        "verified_component_digests": dict(summary.component_digests),
    }
    elapsed = report.get("elapsed_seconds")
    valid = type(elapsed) in (int, float) and math.isfinite(cast(int | float, elapsed)) and cast(int | float, elapsed) >= 0
    return {"component_status": {"state": "recorded", "reason": None}, "component": component,
            "elapsed_seconds": {"value": elapsed} if valid else {"unknown": "elapsed_not_recorded"}}


def _join_component(row: Mapping[str, Any], seal: Mapping[str, Any] | None) -> None:
    component = row["component"]
    try:
        validate_component(component)
        size = len(canonical_json_bytes(component) + b"\n")
    except PairReportRefusal as error:
        raise PublicTextReportRefusal("report_component:" + error.code[:80]) from None
    require(size <= MAX_DOSSIER_BYTES, "report_component_size")
    supplied = component["supplied"] == "supplied"
    validate_component_status(row["component_status"], supplied)
    validate_elapsed(row["elapsed_seconds"], supplied)
    if seal is None:
        return
    require(supplied, "report_seal_without_component")
    verified, counts = component["verified_component_digests"], component["verified_counts"]
    require({RECEIPT_ROLES[k]: v for k, v in seal["receipt_digests"].items()} == verified, "report_seal_component_join")
    arms = seal["arms"].values()
    records, documents = sum(a["counts"]["records"] for a in arms), sum(a["counts"]["documents"] for a in arms)
    require((counts["record_count"], counts["document_count"], counts["query_count"]) == (records, documents,
                                                                                         records - documents)
            and seal["records_returned"]["value"] is (counts["embedding_count"] == counts["record_count"]),
            "report_seal_component_counts")


def _admitted(census: Mapping[str, Any], name: str) -> list[str]:
    return [t["task_id"] for t in census["tasks"] if t[name] == "admitted"]


def _join_request(row: Mapping[str, Any], census: Mapping[str, Any], preparation: Mapping[str, Any] | None,
                  request: Mapping[str, Any] | None, seal: Mapping[str, Any] | None, generation: int) -> None:
    if preparation is None:
        require(census["status"] == "preparation_absent" and request is None and seal is None, "report_preparation_join")
        return
    documents = preparation["document_count"]
    require(census["status"] != "preparation_absent" and census["document_count"] == documents
            and census["v1_verified_pair_count"] == preparation["v1_verified_pair_count"]
            and census["status"] == ("no_documents" if documents == 0 else (
                "ready" if _admitted(census, "public_text_state") else "document_only")), "report_preparation_join")
    if request is not None:
        require(request["documents"] == {ARM_V1: preparation["v1_verified_pair_count"], ARM_PTX: documents}
                and request["queries"] == {ARM_V1: len(_admitted(census, "v1_learned_state")),
                                           ARM_PTX: len(_admitted(census, "public_text_state"))}
                and (generation == 1 or request["queries"] == {ARM_V1: 0, ARM_PTX: 0}), "report_request_join")
    if seal is None:
        return
    require(request is not None and request["input_identity"] == seal["input_identity"]
            and request["request_sha256"] == seal["receipt_digests"]["request"]
            and seal["publication_identity"] == row["publication_identity"]
            and all((seal["arms"][a]["counts"]["documents"], seal["arms"][a]["counts"]["queries"])
                    == (request["documents"][a], request["queries"][a]) for a in (ARM_V1, ARM_PTX)),
            "report_seal_request_join")
    queries = {arm: [r["record_id"].split(":", 1)[1] if arm == ARM_V1 else r["record_id"][len("ptx.q."):]
                     for r in seal["arms"][arm]["records"] if r["mode"] == "query"] for arm in (ARM_V1, ARM_PTX)}
    task_digests = {item["task_id"]: item["retained_task_sha256"] for item in census["tasks"]}
    for arm in (ARM_V1, ARM_PTX):
        query_records = [item for item in seal["arms"][arm]["records"] if item["mode"] == "query"]
        require(all(record["source_identity"] == task_digests.get(task_id)
                    for record, task_id in zip(query_records, queries[arm], strict=True)),
                "report_query_task_join")
    partial = bool(preparation["exclusion_counts"]) or documents < preparation["v1_verified_pair_count"]
    require(queries[ARM_V1] == _admitted(census, "v1_learned_state")
            and queries[ARM_PTX] == _admitted(census, "public_text_state")
            and seal["arms"][ARM_PTX]["publication_coverage"] == ("partial" if partial else "complete"),
            "report_seal_census_join")


def _join_imports(imports: Sequence[Mapping[str, Any]], indexes: Sequence[Mapping[str, Any]],
                  seal: Mapping[str, Any] | None, fences: Mapping[str, Any]) -> None:
    verified = fences["creation"] == "verified" and fences["inventory"] == "verified"
    require(not imports or (seal is not None and verified), "report_imports_join")
    for item in imports:
        assert seal is not None
        arm = seal["arms"][item["arm"]]
        require(arm["capability"] == item["capability"] and arm["counts"]["documents"] == item["row_count"]
                and item["seal_identity"] == seal["seal_identity"], "report_imports_join")
    imported = {item["arm"]: item["batch_id"] for item in imports}
    require(all(imported.get(index["arm"]) == index["batch_id"] for index in indexes), "report_indexes_join")


def validate_generation(row: object, generation: int, pins: SelectedTaskPins, functional_only: bool,
                        artifact_profile_identity: str) -> Mapping[str, Any]:
    """One closed generation row and every join inside it."""
    value = closed(row, GENERATION_FIELDS, "report_generation")
    require(type(value["generation"]) is int and value["generation"] == generation
            and digest(value["publication_identity"]), "report_generation")
    census = validate_census(value["census"], generation, pins)
    preparation = None if value["preparation"] is None else validate_preparation(value["preparation"])
    request, seal = validate_request(value["request"]), validate_seal(value["seal"], generation)
    require(seal is None or seal["artifact_profile_identity"] == artifact_profile_identity, "report_source_join")
    _join_component(value, seal)
    _join_request(value, census, preparation, request, seal, generation)
    imports, indexes = validate_imports(value["imports"], generation), validate_indexes(value["indexes"])
    _join_imports(imports, indexes, seal, validate_fences(value["fences"], functional_only))
    return value


def join_cells(cells: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]) -> None:
    """Learned cells keep original decisions; a completed one needs every observed prerequisite."""
    by_task = {(g + 1, t["task_id"]): t for g, row in enumerate(rows) for t in row["census"]["tasks"]}
    for cell in cells:
        if cell["arm"] not in LEARNED_ARMS:
            continue
        kind, representation = cell["arm"].split(":", 1)
        task, row = by_task[(cell["generation"], cell["task_id"])], rows[cell["generation"] - 1]
        state, reason = ((task["v1_learned_state"], task["v1_learned_reason"]) if representation == ARM_V1
                         else (task["public_text_state"], task["public_text_reason"]))
        if state != "admitted":
            source = "v1_decision" if representation == ARM_V1 else "public_text_decision"
            require(cell["state"] in ("refused", "unavailable") and cell["reason"]["source"] == source
                    and (reason is None or cell["reason"]["code"] == reason), "report_decision_retained")
        if cell["state"] != "completed":
            continue
        seal = row["seal"]
        arm = None if seal is None else seal["arms"][representation]
        require(arm is not None and arm["capability"] in ("complete", "token_partial") and state == "admitted",
                "report_learned_completed")
        assert arm is not None
        fences, imports, indexes = row["fences"], arm_rows(row["imports"]), arm_rows(row["indexes"])
        require(representation in imports and (kind != "hnsw_vector" or representation in indexes)
                and (fences["creation"], fences["inventory"], fences["publication"]) == ("verified", "verified",
                                                                                         "current"),
                "report_learned_uncredited")
        partial = arm["capability"] == "token_partial"
        require(cell["capability"] == ("partial" if partial else "complete")
                and (not partial or (cell["incomplete"] and cell["truncated"]))
                and cell["publication_coverage"] == arm["publication_coverage"], "report_capability_join")


def join_cleanup(cleanup: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
    """Objects are exactly the recorded inventory once creation was verified; each reports its own absence."""
    kinds = Counter(item["kind"] for item in cleanup["objects"])
    if any(row["fences"]["creation"] == "verified" for row in rows):
        indexes = sum(len(row["indexes"]) for row in rows)
        expected = Counter({"batch": 1, "entry": 1, "constraint_index": 4, "index": indexes})
        require(cleanup["status"] != "not_run" and kinds == +expected, "report_cleanup_join")
    elif cleanup["status"] != "not_run":
        require(kinds == Counter({"batch": 1, "entry": 1}), "report_cleanup_join")


@dataclass(frozen=True)
class ReportEvidence:
    """Actual per-generation journal and model members, selected task objects and optional private scope."""

    components: Mapping[int, tuple[JournalArtifact, Mapping[str, bytes]] | None]
    tasks: SelectedTaskSet
    scope: PrivateMarkerScope | None = None


def _response(journal: JournalArtifact, members: Mapping[str, bytes]) -> Any:
    try:
        anchors = canonical_anchors(journal)
        inputs = read_worker_archive_inputs(members["sources.zip"])
        return parse_verified_worker_response(
            request_raw=inputs["request.json"], report_raw=members["report.json"],
            terminal_raw=members["terminal.json"], declaration_raw=members["declaration.json"],
            source_manifest_raw=members["source-manifest.json"], sources_archive_raw=members["sources.zip"],
            expected_controller_admission_sha256=anchors.admission, expected_source_closure=dict(anchors.closure))
    except (WorkerRequestError, RepresentationValidationError, PairReportRefusal, KeyError, TypeError, ValueError,
            OverflowError):
        raise PublicTextReportRefusal("report_evidence_response") from None


def _verify_seal(seal: Mapping[str, Any], response: Any) -> None:
    generation = response.generation
    embeddings = {item.record_id: item for item in generation.embeddings}
    records = [r for arm in (ARM_V1, ARM_PTX) for r in seal["arms"][arm]["records"]]
    cost = generation.cost
    require(
        seal["response_identity"] == response._sealed_identity and seal["attempt_id"] == response.attempt_id
        and all(seal[n] == getattr(response, n) for n in ("input_identity", "representation_report_identity",
                                                          "publication_identity", "artifact_profile_identity"))
        and len(records) == len(embeddings) == response.record_count
        and all(r["record_id"] in embeddings and r["mode"] == embeddings[r["record_id"]].mode.value
                and all(r[n] == getattr(embeddings[r["record_id"]], n)
                        for n in ("token_count_before_limit", "token_count_used", "overflow_chunks", "truncated"))
                for r in records)
        and (seal["global_status"], seal["global_partial"]) == (generation.status, generation.partial)
        and seal["shared_cost"] == {n: getattr(cost, n) for n in ("load_seconds", "inference_seconds", "total_seconds")},
        "report_evidence_seal")


def verify_evidence(report: Mapping[str, Any], evidence: ReportEvidence) -> None:
    """Re-verify actual components, re-parse responses and bind both task maps to the actual task objects."""
    require(type(evidence) is ReportEvidence and isinstance(evidence.components, Mapping)
            and set(evidence.components) == {1, 2}, "report_evidence")
    tasks = evidence.tasks
    require(type(tasks) is SelectedTaskSet and tasks.pins == registered_task_pins()
            and tasks.identity() == report["task_pins"]["selected_task_set_identity"], "report_evidence_tasks")
    for generation, row in enumerate(report["generations"], 1):
        actual = {task.task_id: task for task in tasks.for_generation(generation)}
        census = row["census"]["tasks"]
        require([t["task_id"] for t in census] == list(actual) and all(
            (t["retained_task_sha256"], t["v1_query_task_sha256"])
            == (retained_task_sha256(actual[t["task_id"]]), task_sha256(actual[t["task_id"]])) for t in census),
            "report_evidence_tasks")
        supplied, pair = row["component"]["supplied"] == "supplied", evidence.components[generation]
        if not supplied:
            require(pair is None, "report_evidence_component")
            continue
        require(type(pair) is tuple and len(pair) == 2, "report_evidence_component")
        assert pair is not None
        journal, members = pair
        recomputed = component_evidence(journal, members)
        require(recomputed == {k: row[k] for k in ("component_status", "component", "elapsed_seconds")},
                "report_evidence_component")
        if row["seal"] is not None:
            response = _response(journal, members)
            _verify_seal(row["seal"], response)
            request_queries = {record.record_id: record.text for record in response.request_records
                               if record.mode.value == "query"}
            for arm in (ARM_V1, ARM_PTX):
                for record in row["seal"]["arms"][arm]["records"]:
                    if record["mode"] != "query":
                        continue
                    task_id = (record["record_id"].split(":", 1)[1] if arm == ARM_V1
                               else record["record_id"][len("ptx.q."):])
                    require(task_id in actual and record["source_identity"] == retained_task_sha256(actual[task_id])
                            and request_queries.get(record["record_id"]) == actual[task_id].question,
                            "report_evidence_query_tasks")


__all__ = [
    "NOT_RECORDED_COMPONENT", "ReportEvidence", "component_evidence", "join_cells", "join_cleanup",
    "validate_generation", "verify_evidence",
]
