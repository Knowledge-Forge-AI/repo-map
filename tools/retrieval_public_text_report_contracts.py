"""Closed nested schemas, codes, disclosures and the functional marker of the public-text report (section 18.4).

Every nested object is closed and strictly typed: counts are non-bool ``int``,
flags are ``bool``, identities are ``sha256:`` digests and reasons follow one
closed code grammar, so no free text, excerpt, vector, plan, row or extra field
can enter the serialized bytes. The public study seal is validated recursively
and every derived value in it (identity, per-arm counts and token sums,
capability, truncated lists, global partial state) is recomputed here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
from typing import cast, Any

from common_lore_index.storage.semantic_candidates import digest_json
from retrieval_public_text_census import CENSUS_STATUSES
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_tasks import SelectedTaskPins
from retrieval_semantic_generator_kernel_contracts import MODEL_MAX_TOKENS

REPORT_SCHEMA = "cloe-public-text-calibration-v1"
SEAL_SCHEMA = "cloe-public-text-study-seal-v1"
EXECUTION_KINDS = {True: "synthetic_functional", False: "native"}
TOP_FIELDS = frozenset({
    "schema", "phase", "declaration", "study_identity", "functional_only", "task_pins", "source", "arms",
    "generations", "cells", "cleanup", "acceptance", "disclosures", "counts", "observation_status",
})
GENERATION_FIELDS = frozenset({
    "generation", "publication_identity", "census", "preparation", "request", "component_status", "component",
    "elapsed_seconds", "seal", "imports", "indexes", "fences",
})
RECEIPT_ROLES = {"request": "request", "report": "report", "terminal": "terminal", "declaration": "declaration",
                 "manifest": "source_manifest", "archive": "sources_archive", "admission": "admission"}
CENSUS_FIELDS = frozenset({"census_identity", "status", "document_count", "v1_verified_pair_count", "tasks"})
CENSUS_TASK_FIELDS = frozenset({
    "task_id", "retained_task_sha256", "v1_query_task_sha256", "v1_learned_state", "v1_learned_reason",
    "public_text_state", "public_text_reason",
})
PREPARATION_FIELDS = frozenset({"preparation_identity", "document_count", "v1_verified_pair_count", "exclusion_counts"})
REQUEST_FIELDS = frozenset({"input_identity", "records", "documents", "queries", "bytes", "request_sha256"})
SEAL_FIELDS = frozenset({
    "schema", "generation", "attempt_id", "response_identity", "receipt_digests", "input_identity",
    "representation_report_identity", "publication_identity", "artifact_profile_identity", "worker_terminal",
    "records_returned", "global_status", "global_partial", "shared_cost", "arms", "seal_identity",
})
ARM_FIELDS = frozenset({
    "arm", "capability", "refusal", "token_partial", "counts", "exact_cost", "time", "io",
    "truncated_document_identities", "truncated_query_task_ids", "publication_coverage", "records",
})
RECORD_FIELDS = frozenset({
    "record_id", "mode", "source_identity", "token_count_before_limit", "token_count_used", "overflow_chunks",
    "truncated",
})
TOKEN_FIELDS = ("token_count_before_limit", "token_count_used", "overflow_chunks")
COST_FIELDS = frozenset({"records", "documents", "queries", "input_bytes", "model_input_bytes", *TOKEN_FIELDS,
                         "truncated_records"})
IMPORT_FIELDS = frozenset({"arm", "batch_id", "capability", "row_count", "seal_identity"})
INDEX_FIELDS = frozenset({"arm", "batch_id", "state"})
FENCE_STATES = {"creation": ("verified", "failed", "not_reached"), "inventory": ("verified", "changed", "not_reached"),
                "publication": ("current", "stale", "not_checked")}
CLEANUP_KINDS = ("batch", "entry", "constraint_index", "index")
SHARED_COST_FIELDS = ("load_seconds", "inference_seconds", "total_seconds")
_CODE = re.compile(r"[a-z0-9_.:-]{1,96}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TASK = r"[a-z0-9][a-z0-9_.-]{0,63}"
_ATTEMPT = re.compile(r"w5-semantic-g[12]\Z")
_BATCH = re.compile(r"ptx1-g([12])-(v1|ptx)-[0-9a-f]{16}\Z")
RECORD_PATTERNS = {
    (ARM_V1, "document"): re.compile(r"v1\.document:[0-9a-f]{64}\Z"),
    (ARM_V1, "query"): re.compile(rf"v1\.query:({_TASK})\Z"),
    (ARM_PTX, "document"): re.compile(r"ptx\.d\.[0-9]{4}\Z"),
    (ARM_PTX, "query"): re.compile(rf"ptx\.q\.({_TASK})\Z"),
}


class PublicTextReportRefusal(ValueError):
    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("report_") or len(code) > 96:
            raise ValueError("unknown public-text report code")
        super().__init__(code)
        self.code = code


def require(condition: bool, code: str) -> None:
    if not condition:
        raise PublicTextReportRefusal(code)


def digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def code_ok(value: object) -> bool:
    return type(value) is str and _CODE.fullmatch(value) is not None


def count(value: object) -> bool:
    return type(value) is int and value >= 0


def strict_equal(left: object, right: object) -> bool:
    """Structural equality that also requires identical JSON types (``True != 1``, ``1.0 != 1``)."""
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        assert isinstance(right, Mapping)
        return set(left) == set(right) and all(strict_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        assert isinstance(right, list)
        return len(left) == len(right) and all(strict_equal(a, b) for a, b in zip(left, right))
    return left == right


def closed(value: object, fields: frozenset[str], code: str) -> Mapping[str, Any]:
    require(isinstance(value, Mapping) and set(value) == fields, code)
    assert isinstance(value, Mapping)
    return value


def disclosures(functional_only: bool) -> dict[str, str]:
    """Static public disclosures; the execution line follows the strict functional marker."""
    return {
        "authority": "structural_source_and_artifact_agreement_only_not_native_science_runtime_or_adoption",
        "privacy": "hashes_offsets_counts_and_closed_reasons_only",
        "cost": "per_arm_records_bytes_tokens_exact_shared_timings_once_per_arm_time_unknown",
        "ann": "plan_observed_not_predicted_hnsw_may_remain_unselected",
        "task_digests": "cell_task_sha256_is_retained_ascii_pin_census_v1_query_digest_is_utf8_scheme",
        "verification": "builder_structural_only_reader_structural_only_without_evidence_context",
        "execution": ("functional_only_synthetic_vectors_no_model_origin_or_relevance" if functional_only
                      else "native_flag_alone_never_proves_model_origin_or_acceptance"),
    }


def validate_source(value: object) -> Mapping[str, Any]:
    source = closed(value, frozenset({"q_source_closure", "artifact_profile_identity", "model_revision"}), "report_source")
    revision = source["model_revision"]
    require(digest(source["q_source_closure"]) and digest(source["artifact_profile_identity"])
            and type(revision) is str and 0 < len(revision) <= 128 and revision.isascii() and revision.isprintable(),
            "report_source")
    return source


def validate_census(value: object, generation: int, pins: SelectedTaskPins) -> Mapping[str, Any]:
    """Closed census summary; only the retained ASCII digest joins the pins."""
    census = closed(value, CENSUS_FIELDS, "report_census")
    require(digest(census["census_identity"]) and census["status"] in CENSUS_STATUSES
            and count(census["document_count"]) and count(census["v1_verified_pair_count"])
            and type(census["tasks"]) is list, "report_census")
    for task in census["tasks"]:
        row = closed(task, CENSUS_TASK_FIELDS, "report_census_task")
        require(digest(row["retained_task_sha256"]) and digest(row["v1_query_task_sha256"])
                and code_ok(row["v1_learned_state"]) and code_ok(row["public_text_state"])
                and all(row[n] is None or code_ok(row[n]) for n in ("v1_learned_reason", "public_text_reason")),
                "report_census_task")
    expected = [(t, d) for t, g, d in pins.tasks if g == generation]
    require([(t["task_id"], t["retained_task_sha256"]) for t in census["tasks"]] == expected,
            "report_census_retained_join")
    return census


def validate_preparation(value: object) -> Mapping[str, Any]:
    preparation = closed(value, PREPARATION_FIELDS, "report_preparation")
    exclusions = preparation["exclusion_counts"]
    require(digest(preparation["preparation_identity"]) and count(preparation["document_count"])
            and count(preparation["v1_verified_pair_count"]) and isinstance(exclusions, Mapping)
            and all(code_ok(k) and type(v) is int and v > 0 for k, v in exclusions.items()), "report_preparation")
    return preparation


def _arm_counts(value: object, code: str) -> Mapping[str, Any]:
    counts = closed(value, frozenset({ARM_V1, ARM_PTX}), code)
    require(all(count(item) for item in counts.values()), code)
    return counts


def validate_request(value: object) -> Mapping[str, Any] | None:
    if value is None:
        return None
    request = closed(value, REQUEST_FIELDS, "report_request")
    documents, queries = _arm_counts(request["documents"], "report_request"), _arm_counts(request["queries"], "report_request")
    require(digest(request["input_identity"]) and digest(request["request_sha256"]) and count(request["bytes"])
            and count(request["records"]) and request["bytes"] > 0
            and request["records"] == sum(documents.values()) + sum(queries.values()), "report_request")
    return request


def _seconds(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(cast(int | float, value)) and cast(int | float, value) >= 0


def _record(value: object, arm: str) -> tuple[str, bool, str | None]:
    record = closed(value, RECORD_FIELDS, "report_seal_record")
    mode, before, used, overflow = (record["mode"], record["token_count_before_limit"], record["token_count_used"],
                                    record["overflow_chunks"])
    pattern = RECORD_PATTERNS.get((arm, mode))
    match = pattern.fullmatch(record["record_id"]) if pattern is not None and type(record["record_id"]) is str else None
    require(match is not None and digest(record["source_identity"]) and type(record["truncated"]) is bool
            and all(count(item) for item in (before, used, overflow)) and before > 0
            and used == min(before, MODEL_MAX_TOKENS)
            and record["truncated"] == (overflow > 0) == (before > MODEL_MAX_TOKENS), "report_seal_record")
    assert match is not None
    return mode, record["truncated"], (match.group(1) if mode == "query" else None)


def _seal_arm(value: object, arm: str) -> bool:
    """One arm: closed fields, per-record invariants and every derived count/sum/list recomputed."""
    seal = closed(value, ARM_FIELDS, "report_seal_arm")
    records = seal["records"]
    require(seal["arm"] == arm and type(records) is list and seal["time"] == {"unknown": "shared_worker_cost"}
            and seal["io"] == {"unknown": "not_observed"} and seal["publication_coverage"] in ("complete", "partial"),
            "report_seal_arm")
    parsed = [_record(item, arm) for item in records]
    documents = sum(1 for mode, _t, _q in parsed if mode == "document")
    truncated = any(flag for _m, flag, _q in parsed)
    counts = closed(seal["counts"], frozenset({"records", "documents", "queries"}), "report_seal_arm")
    cost = closed(seal["exact_cost"], COST_FIELDS, "report_seal_arm")
    require(strict_equal(dict(counts), {"records": len(records), "documents": documents,
                                        "queries": len(records) - documents})
            and all(cost[name] == counts[name] for name in counts) and all(count(cost[n]) for n in COST_FIELDS)
            and all(cost[name] == sum(r[name] for r in records) for name in TOKEN_FIELDS)
            and cost["truncated_records"] == sum(1 for _m, flag, _q in parsed if flag), "report_seal_arm")
    capability = (("refused" if truncated else "complete") if arm == ARM_V1
                  else ("token_partial" if truncated else "complete"))
    refusal = "v1_own_record_truncated" if arm == ARM_V1 and truncated else None
    truncated_documents = [r["source_identity"] for r, (mode, flag, _q) in zip(records, parsed) if flag and mode == "document"]
    truncated_queries = [task for mode, flag, task in parsed if flag and mode == "query"]
    require((seal["capability"], seal["refusal"], seal["token_partial"]) == (capability, refusal, truncated)
            and seal["truncated_document_identities"] == truncated_documents
            and seal["truncated_query_task_ids"] == truncated_queries, "report_seal_capability")
    return truncated


def validate_seal(value: object, generation: int) -> Mapping[str, Any] | None:
    """The verbatim public study seal, recursively closed; identity and every derived value recomputed."""
    if value is None:
        return None
    seal = closed(value, SEAL_FIELDS, "report_seal")
    require(seal["schema"] == SEAL_SCHEMA and type(seal["generation"]) is int and seal["generation"] == generation and type(seal["attempt_id"]) is str
            and _ATTEMPT.fullmatch(seal["attempt_id"]) is not None and seal["worker_terminal"] == "completed"
            and all(digest(seal[n]) for n in ("response_identity", "input_identity", "representation_report_identity",
                                              "publication_identity", "artifact_profile_identity")), "report_seal")
    receipts = closed(seal["receipt_digests"], frozenset(RECEIPT_ROLES), "report_seal")
    returned = closed(seal["records_returned"], frozenset({"value"}), "report_seal")
    shared = closed(seal["shared_cost"], frozenset(SHARED_COST_FIELDS), "report_seal")
    require(all(digest(item) for item in receipts.values()) and type(returned["value"]) is bool
            and all(_seconds(shared[n]) for n in SHARED_COST_FIELDS)
            and shared["total_seconds"] + 1e-6 >= shared["load_seconds"] + shared["inference_seconds"], "report_seal")
    arms = closed(seal["arms"], frozenset({ARM_V1, ARM_PTX}), "report_seal")
    partial = any([_seal_arm(arms[ARM_V1], ARM_V1), _seal_arm(arms[ARM_PTX], ARM_PTX)])
    require(seal["global_partial"] is partial and seal["global_status"] == ("partial" if partial else "complete"),
            "report_seal_partial")
    body = {name: item for name, item in seal.items() if name != "seal_identity"}
    require(seal["seal_identity"] == str(digest_json(body)), "report_seal_identity")
    return seal


def validate_imports(value: object, generation: int) -> list[Mapping[str, Any]]:
    require(type(value) is list and len(value) <= 2, "report_imports")
    assert isinstance(value, list)
    rows = [closed(item, IMPORT_FIELDS, "report_imports") for item in value]
    for row in rows:
        match = _BATCH.fullmatch(row["batch_id"]) if type(row["batch_id"]) is str else None
        require(row["arm"] in (ARM_V1, ARM_PTX) and match is not None and int(match.group(1)) == generation
                and match.group(2) == ("v1" if row["arm"] == ARM_V1 else "ptx")
                and row["capability"] in ("complete", "token_partial") and type(row["row_count"]) is int
                and 1 <= row["row_count"] <= 500 and digest(row["seal_identity"]), "report_imports")
    require(len({row["arm"] for row in rows}) == len(rows), "report_imports")
    return rows


def validate_indexes(value: object) -> list[Mapping[str, Any]]:
    require(type(value) is list and len(value) <= 2, "report_indexes")
    assert isinstance(value, list)
    rows = [closed(item, INDEX_FIELDS, "report_indexes") for item in value]
    require(all(row["arm"] in (ARM_V1, ARM_PTX) and row["state"] == "created" and type(row["batch_id"]) is str
                and _BATCH.fullmatch(row["batch_id"]) is not None for row in rows)
            and len({row["arm"] for row in rows}) == len(rows), "report_indexes")
    return rows


def validate_fences(value: object, functional_only: bool) -> Mapping[str, Any]:
    """Closed fences; the execution kind must match the strict top-level functional marker."""
    fences = closed(value, frozenset({"execution_kind", *FENCE_STATES}), "report_fences")
    require(all(fences[name] in states for name, states in FENCE_STATES.items()), "report_fences")
    require(fences["execution_kind"] == EXECUTION_KINDS[functional_only], "report_execution_kind")
    return fences


def validate_cleanup(value: object) -> Mapping[str, Any]:
    cleanup = closed(value, frozenset({"status", "reason", "objects"}), "report_cleanup")
    objects = cleanup["objects"]
    require(cleanup["status"] in ("clean", "failed", "not_run") and type(objects) is list
            and (cleanup["reason"] is None) == (cleanup["status"] == "clean")
            and (cleanup["reason"] is None or (code_ok(cleanup["reason"])
                                               and str(cleanup["reason"]).startswith("cleanup_")))
            and all(isinstance(o, Mapping) and set(o) == {"kind", "absent"} and o["kind"] in CLEANUP_KINDS
                    and type(o["absent"]) is bool for o in objects)
            and (cleanup["status"] != "clean" or all(o["absent"] for o in objects))
            and (cleanup["status"] != "not_run" or not objects), "report_cleanup")
    return cleanup


def validate_elapsed(value: object, supplied: bool) -> None:
    require(isinstance(value, Mapping) and len(value) == 1 and (
        ("value" in value and supplied and _seconds(value["value"]))
        or code_ok(value.get("unknown"))), "report_elapsed")


def validate_component_status(value: object, supplied: bool) -> None:
    status = closed(value, frozenset({"state", "reason"}), "report_component_status")
    require(status["state"] == ("recorded" if supplied else "not_recorded")
            and (status["reason"] is None if supplied else (code_ok(status["reason"])
                                                            and str(status["reason"]).startswith("component_"))),
            "report_component_status")


def arm_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {row["arm"]: row for row in rows}


__all__ = [
    "ARM_FIELDS", "CENSUS_FIELDS", "CENSUS_TASK_FIELDS", "CLEANUP_KINDS", "COST_FIELDS", "EXECUTION_KINDS",
    "FENCE_STATES", "GENERATION_FIELDS", "IMPORT_FIELDS", "INDEX_FIELDS", "PREPARATION_FIELDS", "RECEIPT_ROLES",
    "RECORD_FIELDS", "RECORD_PATTERNS", "REPORT_SCHEMA", "REQUEST_FIELDS", "SEAL_FIELDS", "SEAL_SCHEMA",
    "TOP_FIELDS", "PublicTextReportRefusal", "arm_rows", "closed", "code_ok", "count", "digest", "disclosures",
    "require", "strict_equal", "validate_census", "validate_cleanup", "validate_component_status", "validate_elapsed",
    "validate_fences", "validate_imports", "validate_indexes", "validate_preparation", "validate_request",
    "validate_seal", "validate_source",
]
