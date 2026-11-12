"""Study-only seal over a real VerifiedWorkerResponse.

Responses are produced by the unchanged ``parse_verified_worker_response`` from
synthetic raw worker artifacts. They prove parser/sealer contracts only, never
native or model origin. Only negative tamper cases replace a real parsed response;
no fabricated response is ever accepted as valid.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
from collections.abc import Collection
from typing import Any
import zipfile

import pytest

from common_lore_index.storage.semantic_candidates import digest_json
from repomap_test_support.retrieval_evaluation_query_fixture import build_fixture_projection
from repomap_test_support.w5_semantic_support import (
    InMemoryStoreReadbackCell, make_w5_accepted_pub_mapping, make_w5_calibration_task,
)
from retrieval_evaluation_schema import TASK_CATALOG_SCHEMA_VERSION
from retrieval_public_text_census import build_public_text_census, retained_task_sha256, task_sha256
from retrieval_public_text_contracts import PrivateMarkerScope, SpanRow
from retrieval_public_text_descriptors import prepare_public_text_generation
from retrieval_public_text_request import ARM_PTX, ARM_V1, build_dual_arm_input, encode_dual_arm_request
from retrieval_public_text_response import (
    StudySealRefusal, check_embedding, check_generation_cost, seal_dual_arm_result,
)
from retrieval_public_text_tasks import TASK_PINS_SCHEMA, TaskSelectionRefusal, load_selected_calibration_tasks, parse_task_pins
from retrieval_semantic_generator_inputs import prepare_public_generation_input
from retrieval_semantic_generator_kernel import QUERY_PREFIX, SemanticCost, SemanticEmbedding, SemanticMode, SemanticText
from retrieval_semantic_generator_output import parse_verified_worker_response
from retrieval_semantic_generator_worker import REQUEST_SCHEMA, RESPONSE_SCHEMA
from retrieval_semantic_primitives import AcceptedEvidenceRecord, AcceptedNodeRecord
from retrieval_semantic_provenance import (
    AcceptedStoreReadback, RepresentationValidationError, verify_publication_provenance_from_adapter,
)
from retrieval_semantic_representation import validate_canonical_node_representations

KEY = "python.function:pkg.alpha:boundary_fn"
CANARY = "CANARY-PRIVATE-HOME-7731"
_CLAIM = "fixed CPU component only; no learned quality, native ANN or production acceptance"

class _Study:
    def __init__(self, tmp_path: Path, markers: tuple[str, ...] = (CANARY,)) -> None:
        inputs, self.policy = build_fixture_projection(spool_dir=tmp_path / "spool")
        publication = make_w5_accepted_pub_mapping(inputs.receipt, run_id=1, generation=1)
        self.cell = InMemoryStoreReadbackCell(
            AcceptedStoreReadback("mixed-v1", "repo1:mixed-v1", "sqlite", publication, inputs.receipt, inputs))
        self.pin = verify_publication_provenance_from_adapter(self.cell, policy=self.policy)
        core = min(self.policy.bindings)
        meta = {"binding_id": core, "snapshot_id": self.pin.snapshot_by_binding()[core][1],
                "source_relative_path": "pkg/alpha.py"}
        self.node = AcceptedNodeRecord(KEY, "Function", "boundary_fn", 1, 1)
        self.evidence = AcceptedEvidenceRecord(KEY, "ev1:alpha80", 1, 1, "core/pkg/alpha.py", meta, "defined_by")
        self.rows = [SpanRow(KEY, "ev1:alpha80", 1, 1, "core/pkg/alpha.py", meta, "defined_by", 80, 81)]
        self.scope = PrivateMarkerScope.create(markers)
        task = make_w5_calibration_task(task_id="cal-01", graph_id="mixed-v1", selected_bindings=(core,))
        raw = json.dumps({"schema_version": TASK_CATALOG_SCHEMA_VERSION, "fixture_id": "synthetic",
                          "tasks": [task.to_dict()]}).encode("ascii")
        (tmp_path / "catalog.json").write_bytes(raw)
        pins = parse_task_pins(json.dumps({
            "catalog_file_sha256": hashlib.sha256(raw).hexdigest(), "held_out_decoded": False,
            "historical_semantic_catalog_identity": "sha256:" + "8" * 64, "original_manifest_sha256": "3" * 64,
            "schema": TASK_PINS_SCHEMA,
            "tasks": [{"generation": 1, "task_id": "cal-01", "task_sha256": retained_task_sha256(task)}],
        }).encode("utf-8"))
        self.tasks = load_selected_calibration_tasks(tmp_path / "catalog.json", pins)

    def report(self) -> Any:
        return validate_canonical_node_representations(
            self.pin, accepted_nodes=(self.node,), accepted_evidence=(self.evidence,))

    def build(self, attempt_id: str = "w5-semantic-g1") -> Any:
        prepared = prepare_public_text_generation(
            publication_pin=self.pin, readback_adapter=self.cell, policy=self.policy, scope=self.scope,
            read_representations=self.report, read_v1_evidence=lambda: (self.evidence,),
            read_span_rows=lambda: tuple(self.rows))
        tasks = self.tasks.for_generation(1)
        census = build_public_text_census(
            tasks, retained_task_digests=self.tasks.retained_digests(1), policy=self.policy, publication_pin=self.pin,
            observed_backend="sqlite", frozen_policy_digest=self.pin.policy_digest, preparation=prepared)
        v1 = prepare_public_generation_input(self.report(), tasks, read_current=lambda: self.pin,
                                             read_representations=self.report)
        return build_dual_arm_input(
            generation=1, attempt_id=attempt_id, study_identity="sha256:" + "5" * 64, v1_input=v1,
            preparation=prepared, census=census, tasks=self.tasks, publication_pin=self.pin,
            artifact_profile_identity="sha256:" + "a" * 64)


def _canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode() + b"\n"


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _unit(index: int) -> list[float]:
    vector = [0.0] * 384
    vector[index % 384] = 1.0
    return vector


def _rows(records: tuple[SemanticText, ...], truncated: set[int]) -> list[dict[str, Any]]:
    rows = []
    for i, record in enumerate(records):
        before = 600 if i in truncated else 20 + i
        rows.append({"record_id": record.record_id, "mode": SemanticMode(record.mode).value, "vector": _unit(i),
                     "token_count_before_limit": before, "token_count_used": min(before, 512),
                     "overflow_chunks": 1 if before > 512 else 0, "truncated": before > 512})
    return rows


def _cost(records: tuple[SemanticText, ...], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "input_records": len(records),
        "input_bytes": sum(len(r.record_id.encode()) + len(r.text.encode()) for r in records),
        "model_input_bytes": sum(len(((QUERY_PREFIX if SemanticMode(r.mode) is SemanticMode.QUERY else "")
                                      + r.text).encode()) for r in records),
        "token_count_before_limit": sum(r["token_count_before_limit"] for r in rows),
        "token_count_used": sum(r["token_count_used"] for r in rows),
        "overflow_chunks": sum(r["overflow_chunks"] for r in rows),
        "truncated_records": sum(1 for r in rows if r["truncated"]),
        "load_seconds": 0.5, "inference_seconds": 1.25, "total_seconds": 2.0,
    }


def _respond(value: Any, *, truncated: Collection[int] = frozenset(), mutate: Any = None) -> Any:
    """Build synthetic raw worker artifacts and parse them with the unchanged parser."""
    request_raw = encode_dual_arm_request(value)
    request = json.loads(request_raw)
    rows = _rows(value.records, set(truncated))
    partial = any(r["truncated"] for r in rows)
    report: dict[str, Any] = {
        "schema": RESPONSE_SCHEMA, "status": "partial" if partial else "complete", "partial": partial,
        "record_count": len(rows), "embedding_count": len(rows),
        "document_count": sum(r["mode"] == "document" for r in rows),
        "query_count": sum(r["mode"] == "query" for r in rows), "embeddings": rows,
        "cost": _cost(value.records, rows), "elapsed_seconds": 3.0, "claim": _CLAIM,
    }
    if mutate is not None:
        mutate(report)
    admission = b'{"synthetic":"controller admission"}'
    sources = {"retrieval_semantic_generator_worker.py": b"# synthetic source closure member\n"}
    closure = {name: _sha(data) for name, data in sources.items()}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, data in sources.items():
            archive.writestr("sources/" + name, data)
        archive.writestr("inputs/request.json", request_raw)
        archive.writestr("inputs/admission.json", admission)
    archive_raw = buffer.getvalue()
    ids = {k: request[k] for k in ("input_identity", "representation_report_identity", "publication_identity",
                                   "artifact_profile_identity")}
    common = {"request_sha256": _sha(request_raw), "controller_admission_sha256": _sha(admission), **ids}
    report_raw = _canon({**report, **common})
    declaration_raw = _canon({**common, "attempt_id": request["attempt_id"], "schema": REQUEST_SCHEMA,
                              "candidate_closure_digests": closure,
                              "public_input_trust": "external evaluator current-store admission required"})
    manifest_raw = _canon({
        "archive_sha256": _sha(archive_raw), "schema_version": "cloe-retrieval-attempt-source-manifest-v1",
        "input_files": {"request.json": _sha(request_raw), "admission.json": _sha(admission)},
        "source_files": closure})
    terminal_raw = _canon({
        "declaration_sha256": _sha(declaration_raw), "journal_sha256": _sha(b""), "observation_count": 0,
        "report_sha256": _sha(report_raw), "source_manifest_sha256": _sha(manifest_raw),
        "sources_archive_sha256": _sha(archive_raw), "status": "completed"})
    return parse_verified_worker_response(
        request_raw=request_raw, report_raw=report_raw, terminal_raw=terminal_raw, declaration_raw=declaration_raw,
        source_manifest_raw=manifest_raw, sources_archive_raw=archive_raw,
        expected_controller_admission_sha256=_sha(admission), expected_source_closure=closure)


def _seal(study: _Study, value: Any, response: Any, refresh: Any = None) -> Any:
    return seal_dual_arm_result(value, response, refresh=refresh or study.build, scope=study.scope)


def _code(study: _Study, value: Any, response: Any, refresh: Any = None) -> str:
    with pytest.raises(StudySealRefusal) as error:
        _seal(study, value, response, refresh)
    return error.value.code


def test_complete_generation_seals_both_arms_with_exact_per_arm_cost(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    value = study.build()
    response = _respond(value)
    seal = _seal(study, value, response)
    assert (seal.global_status, seal.global_partial) == ("complete", False)
    assert {arm: s.capability for arm, s in seal.arms.items()} == {ARM_V1: "complete", ARM_PTX: "complete"}
    cost = response.generation.cost
    for field in ("input_bytes", "model_input_bytes", "token_count_before_limit", "token_count_used",
                  "overflow_chunks", "truncated_records"):
        assert sum(s.exact_cost[field] for s in seal.arms.values()) == getattr(cost, field)
    assert sum(s.exact_cost["records"] for s in seal.arms.values()) == cost.input_records == 4
    public = seal.to_dict()
    assert public["shared_cost"] == {"load_seconds": 0.5, "inference_seconds": 1.25, "total_seconds": 2.0}
    for arm in (ARM_V1, ARM_PTX):
        assert public["arms"][arm]["time"] == {"unknown": "shared_worker_cost"}
        assert public["arms"][arm]["io"] == {"unknown": "not_observed"}
        assert public["arms"][arm]["counts"] == {"records": 2, "documents": 1, "queries": 1}
    assert public["worker_terminal"] == "completed" and public["records_returned"] == {"value": True}
    assert seal.seal_identity == digest_json({k: v for k, v in public.items() if k != "seal_identity"})
    assert public["receipt_digests"]["request"] == response.request_sha256 and seal.response_identity
    text = json.dumps(public, sort_keys=True) + repr(seal)
    for private in ("BOUNDARY_START_TOKEN", "Locate RetrievalPipeline", CANARY, "0.0, 0.0"):
        assert private not in text
    assert len(seal.arms[ARM_PTX].records[0].vector) == 384


def test_v1_own_truncation_refuses_only_v1_and_keeps_flags(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    value = study.build()
    seal = _seal(study, value, _respond(value, truncated={0}))
    v1, ptx = seal.arms[ARM_V1], seal.arms[ARM_PTX]
    assert (v1.capability, v1.refusal) == ("refused", "v1_own_record_truncated")
    assert ptx.capability == "complete" and ptx.refusal is None
    assert [r.truncated for r in v1.records] == [True, False] and seal.global_partial is True
    assert v1.truncated_document_identities == (value.layout[0].source_identity,)


@pytest.mark.parametrize("index,documents,queries", [(1, True, False), (3, False, True)])
def test_v2_truncation_is_token_partial_and_keeps_every_vector(
        tmp_path: Path, index: int, documents: bool, queries: bool) -> None:
    study = _Study(tmp_path)
    value = study.build()
    seal = _seal(study, value, _respond(value, truncated={index}))
    ptx = seal.arms[ARM_PTX]
    assert (ptx.capability, seal.arms[ARM_V1].capability) == ("token_partial", "complete")
    assert len(ptx.records) == 2 and all(len(r.vector) == 384 for r in ptx.records)
    assert ptx.truncated_document_identities == ((value.layout[1].source_identity,) if documents else ())
    assert ptx.truncated_query_task_ids == (("cal-01",) if queries else ())
    assert (seal.global_status, seal.global_partial) == ("partial", True)


def test_five_completeness_facts_are_independent(tmp_path: Path) -> None:
    study = _Study(tmp_path, markers=("BOUNDARY_END_TOKEN",))
    value = study.build()
    assert len(value.preparation.documents) == 0 and value.preparation.exclusions
    public = _seal(study, value, _respond(value)).to_dict()
    assert public["worker_terminal"] == "completed" and public["records_returned"] == {"value": True}
    assert public["arms"][ARM_PTX]["token_partial"] is False and public["arms"][ARM_V1]["token_partial"] is False
    assert public["arms"][ARM_PTX]["publication_coverage"] == "partial"
    assert public["arms"][ARM_V1]["publication_coverage"] == "complete"
    assert public["arms"][ARM_PTX]["capability"] == "complete"


@pytest.mark.parametrize("field,code", [
    ("token_count_before_limit", "study_cost_tokens"), ("token_count_used", "study_cost_tokens"),
    ("overflow_chunks", "study_cost_tokens"), ("truncated_records", "study_cost_tokens"),
])
def test_aggregate_token_mutations_the_parser_accepts_are_refused(tmp_path: Path, field: str, code: str) -> None:
    study = _Study(tmp_path)
    value = study.build()
    response = _respond(value, mutate=lambda report: report["cost"].update({field: report["cost"][field] + 1}))
    assert _code(study, value, response) == code


def test_partial_state_lie_and_non_unit_vectors_are_refused(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    value = study.build()

    def lie(report: dict[str, Any]) -> None:
        report.update(status="partial", partial=True)

    assert _code(study, value, _respond(value, mutate=lie)) == "study_partial_state"

    def scale(report: dict[str, Any]) -> None:
        report["embeddings"][2]["vector"] = [0.5] + [0.0] * 383

    assert _code(study, value, _respond(value, mutate=scale)) == "study_vector_invalid"


@pytest.mark.parametrize("field", ["input_records", "input_bytes", "model_input_bytes", "load_seconds"])
def test_count_byte_and_second_mutations_are_already_refused_by_the_parser(tmp_path: Path, field: str) -> None:
    value = _Study(tmp_path).build()
    with pytest.raises(RepresentationValidationError):
        _respond(value, mutate=lambda report: report["cost"].update({field: -1 if "seconds" in field else 10**6}))


def test_response_identity_request_and_layout_refusals(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    value = study.build()
    response = _respond(value)
    assert _code(study, value, replace(response, status="failed")) == "study_response_identity"
    assert _code(study, value, object()) == "study_response_identity"
    assert _code(study, value, _respond(study.build(attempt_id="w5-semantic-g2"))) == "study_request_mismatch"
    swapped = (replace(value.layout[0], arm=ARM_PTX), replace(value.layout[1], arm=ARM_V1)) + value.layout[2:]
    assert _code(study, replace(value, layout=swapped), response) == "study_current_revalidation_failed"


def test_current_revalidation_and_descriptor_drift_refuse(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    value = study.build()
    response = _respond(value)
    assert _code(study, value, response, refresh=lambda: None) == "study_current_revalidation_failed"
    study.rows[0] = replace(study.rows[0], end_line=80)
    assert _code(study, value, response) == "study_descriptor_set_changed"
    study.cell.advance()
    assert _code(study, value, response) == "study_current_revalidation_failed"


def _embedding(**changes: Any) -> SemanticEmbedding:
    base = {"record_id": "r", "mode": SemanticMode.DOCUMENT, "vector": tuple(_unit(0)),
            "token_count_before_limit": 20, "token_count_used": 20, "overflow_chunks": 0, "truncated": False}
    return SemanticEmbedding(**{**base, **changes})


@pytest.mark.parametrize("changes,code", [
    ({}, None), ({"token_count_before_limit": True}, "study_token_invariant"),
    ({"token_count_used": True, "token_count_before_limit": 1}, "study_token_invariant"),
    ({"overflow_chunks": False}, "study_token_invariant"), ({"truncated": 0}, "study_token_invariant"),
    ({"token_count_used": 19}, "study_token_invariant"), ({"token_count_before_limit": 0}, "study_token_invariant"),
    ({"truncated": True}, "study_token_invariant"), ({"vector": tuple([0.6, 0.8] + [0.0] * 382)}, None),
    ({"vector": tuple([0.6] + [0.0] * 383)}, "study_vector_invalid"), ({"vector": (1.0,)}, "study_vector_invalid"),
    ({"record_id": "other"}, "study_record_identity_mismatch"),
    ({"mode": "document"}, "study_record_identity_mismatch"),
])
def test_per_record_checks_cover_bool_tokens_and_non_unit_vectors(changes: dict[str, Any], code: str | None) -> None:
    expected = SemanticText("r", "text", SemanticMode.DOCUMENT)
    if code is None:
        assert len(check_embedding(expected, _embedding(**changes))) == 384
    else:
        with pytest.raises(StudySealRefusal) as error:
            check_embedding(expected, _embedding(**changes))
        assert error.value.code == code


@pytest.mark.parametrize("field,value,code", [
    ("input_records", True, "study_cost_records"), ("input_records", 2, "study_cost_records"),
    ("input_bytes", 1, "study_cost_bytes"), ("model_input_bytes", True, "study_cost_bytes"),
    ("token_count_used", 21, "study_cost_tokens"), ("truncated_records", False, "study_cost_tokens"),
    ("load_seconds", float("nan"), "study_cost_seconds"), ("total_seconds", 0.1, "study_cost_seconds"),
    ("inference_seconds", True, "study_cost_seconds"), ("load_seconds", -0.5, "study_cost_seconds"),
])
def test_every_aggregate_cost_field_is_reconciled(field: str, value: Any, code: str) -> None:
    records = (SemanticText("r", "text", SemanticMode.DOCUMENT),)
    embeddings = (_embedding(),)
    good = SemanticCost(1, 5, 4, 20, 20, 0, 0, 0.5, 1.0, 1.5)
    check_generation_cost(good, records, embeddings, status="complete", partial=False)
    with pytest.raises(StudySealRefusal) as error:
        check_generation_cost(replace(good, **{field: value}), records, embeddings, status="complete", partial=False)
    assert error.value.code == code
    with pytest.raises(StudySealRefusal) as state:
        check_generation_cost(good, records, embeddings, status="partial", partial=True)
    assert state.value.code == "study_partial_state"


def test_stored_v1_source_layout_cannot_reuse_an_unchanged_input_identity(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    value = study.build()
    response = _respond(value)
    changed = (replace(value.layout[0], source_identity="sha256:" + "0" * 64),) + value.layout[1:]
    forged = replace(value, layout=changed)
    assert _code(study, forged, response, refresh=lambda: forged) == "study_current_revalidation_failed"


def test_external_refresh_error_has_only_a_closed_code(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    value = study.build()
    def unavailable() -> Any:
        raise RuntimeError(CANARY)
    assert _code(study, value, _respond(value), refresh=unavailable) == "study_current_revalidation_failed"


def test_malformed_fresh_owners_yield_only_the_closed_generation_code(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    value = study.build()
    for broken in (replace(value, pin=object()), replace(value, tasks=None), replace(value, census="census")):
        assert _code(study, value, _respond(value), refresh=lambda b=broken: b) == "study_current_revalidation_failed"


def test_unicode_task_keeps_retained_and_v1_digests_distinct_and_refuses_substitution(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    task = replace(study.tasks.tasks[0], question=study.tasks.tasks[0].question + " caf\u00e9 \u2192 x").validate()
    retained, utf8 = retained_task_sha256(task), task_sha256(task)
    raw = json.dumps({"schema_version": TASK_CATALOG_SCHEMA_VERSION, "fixture_id": "u", "tasks": [task.to_dict()]}).encode()
    (tmp_path / "unicode.json").write_bytes(raw)
    def load(digest: str) -> Any:
        return load_selected_calibration_tasks(tmp_path / "unicode.json", parse_task_pins(json.dumps({
            "catalog_file_sha256": hashlib.sha256(raw).hexdigest(), "held_out_decoded": False, "schema": TASK_PINS_SCHEMA,
            "historical_semantic_catalog_identity": "sha256:" + "8" * 64, "original_manifest_sha256": "3" * 64,
            "tasks": [{"generation": 1, "task_id": "cal-01", "task_sha256": digest}]}).encode()))
    with pytest.raises(TaskSelectionRefusal, match="task_digest_mismatch"):
        load(utf8)
    study.tasks = load(retained)
    value = study.build()
    assert retained != utf8 and {r.source_identity for r in value.layout if r.mode is SemanticMode.QUERY} == {retained}
    assert dict(value.manifest()["v1_query_task_digests"]) == {"cal-01": utf8}
    assert _seal(study, value, _respond(value)).generation == 1
    forged = replace(value, layout=tuple(replace(r, source_identity=utf8) if r.mode is SemanticMode.QUERY else r
                                         for r in value.layout))
    assert _code(study, forged, _respond(forged), refresh=lambda: forged) == "study_current_revalidation_failed"
