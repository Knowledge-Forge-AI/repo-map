"""Dual-arm request: four ordered partitions, exact v1 parity, closed identities and combined caps."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

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
from retrieval_public_text_request import (
    ARM_PTX, ARM_V1, MAX_REQUEST_BYTES, PARTITIONS, DualArmRequestRefusal, build_dual_arm_input, check_request_caps,
    encode_dual_arm_request, plan_records,
)
from retrieval_public_text_tasks import TASK_PINS_SCHEMA, load_selected_calibration_tasks, parse_task_pins
from retrieval_semantic_generator_inputs import prepare_public_generation_input
from retrieval_semantic_generator_kernel import SemanticMode, SemanticText
from retrieval_semantic_generator_worker import parse_worker_request
from retrieval_semantic_primitives import AcceptedEvidenceRecord, AcceptedNodeRecord
from retrieval_semantic_provenance import AcceptedStoreReadback, verify_publication_provenance_from_adapter
from retrieval_semantic_representation import validate_canonical_node_representations

KEY = "python.function:pkg.alpha:boundary_fn"
CANARY = "CANARY-PRIVATE-HOME-7731"
STUDY = "sha256:" + "5" * 64
PROFILE = "sha256:" + "a" * 64


class _Study:
    """Fixture-backed real preparation, census, v1 input and selected task set (no model, no DB)."""

    def __init__(self, tmp_path: Path, markers: tuple[str, ...] = (CANARY,), *, question: str | None = None) -> None:
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
        if question is not None:
            task = replace(task, question=question).validate()
        raw = json.dumps({"schema_version": TASK_CATALOG_SCHEMA_VERSION, "fixture_id": "synthetic",
                          "tasks": [task.to_dict()]}, indent=1).encode("ascii")
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

    def parts(self, *, with_preparation: bool = True, v1_tasks: Any = None) -> dict[str, Any]:
        prepared = prepare_public_text_generation(
            publication_pin=self.pin, readback_adapter=self.cell, policy=self.policy, scope=self.scope,
            read_representations=self.report, read_v1_evidence=lambda: (self.evidence,),
            read_span_rows=lambda: tuple(self.rows))
        tasks = self.tasks.for_generation(1)
        census = build_public_text_census(
            tasks, retained_task_digests=self.tasks.retained_digests(1), policy=self.policy, publication_pin=self.pin,
            observed_backend="sqlite", frozen_policy_digest=self.pin.policy_digest,
            preparation=prepared if with_preparation else None)
        v1 = prepare_public_generation_input(
            self.report(), tasks if v1_tasks is None else v1_tasks, read_current=lambda: self.pin,
            read_representations=self.report)
        return {"generation": 1, "attempt_id": "w5-semantic-g1", "study_identity": STUDY, "v1_input": v1,
                "preparation": prepared, "census": census, "tasks": self.tasks, "publication_pin": self.pin,
                "artifact_profile_identity": PROFILE}

    def build(self, **changes: Any) -> Any:
        return build_dual_arm_input(**{**self.parts(), **changes})


def test_four_ordered_partitions_keep_byte_identical_v1_texts(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    parts = study.parts()
    value = build_dual_arm_input(**parts)
    v1, prepared = parts["v1_input"], parts["preparation"]
    assert [r.partition for r in value.layout] == list(PARTITIONS)
    assert [r.record_id for r in value.layout] == [
        "v1." + v1.records[0].record_id, "ptx.d.0001", "v1.query:cal-01", "ptx.q.cal-01"]
    assert [r.arm for r in value.layout] == [ARM_V1, ARM_PTX, ARM_V1, ARM_PTX]
    v1_texts = {r.record_id: (r.text, SemanticMode(r.mode)) for r in v1.records}
    for record, layout in zip(value.records, value.layout, strict=True):
        assert record.record_id == layout.record_id and SemanticMode(record.mode) is layout.mode
        if layout.arm == ARM_V1:
            assert layout.v1_record_id == record.record_id[3:]
            assert (record.text, SemanticMode(record.mode)) == v1_texts[layout.v1_record_id]
    assert value.records[1].text == prepared.documents[0].model_text
    assert value.records[3].text.encode() == value.records[2].text.encode() == study.tasks.tasks[0].question.encode()
    assert value.layout[0].source_identity == v1.documents[0].representation.input_digest
    assert value.layout[1].source_identity == prepared.documents[0].identity
    assert value.layout[3].source_identity == value.layout[2].source_identity == task_sha256(study.tasks.tasks[0])
    assert (value.layout[2].task_id, value.layout[3].task_id, value.layout[1].task_id) == ("cal-01", "cal-01", None)


def test_request_bytes_round_trip_through_the_unchanged_worker_parser(tmp_path: Path) -> None:
    value = _Study(tmp_path).build()
    raw = encode_dual_arm_request(value)
    assert raw == json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                             allow_nan=False).encode("ascii")
    request, records = parse_worker_request(raw)
    assert records == value.records and request["attempt_id"] == "w5-semantic-g1"
    assert (request["input_identity"], request["representation_report_identity"], request["publication_identity"],
            request["artifact_profile_identity"]) == (value.input_identity, value.representation_report_identity,
                                                     value.publication_identity, PROFILE)


def test_identity_manifest_binds_every_owner_and_carries_no_text(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    parts = study.parts()
    value = build_dual_arm_input(**parts)
    manifest = value.manifest()
    assert value.input_identity == digest_json(manifest)
    prepared, census, v1 = parts["preparation"], parts["census"], parts["v1_input"]
    assert manifest["preparation_identity"] == digest_json(prepared.to_dict())
    assert manifest["census_identity"] == census.to_dict()["census_identity"]
    assert manifest["privacy_scope_id"] == prepared.privacy_scope_id == census.privacy_scope_id
    assert manifest["task_pins_identity"] == study.tasks.pins.identity()
    assert manifest["selected_task_set_identity"] == study.tasks.identity()
    assert manifest["publication_pin_identity"] == digest_json(study.pin.to_dict()) == value.publication_identity
    assert manifest["v1"] == {"input_identity": v1.input_identity,
                              "representation_report_identity": v1.representation_report_identity}
    assert manifest["partitions"] == {name: 1 for name in PARTITIONS}
    for (rid, arm, mode, text_sha, source), record, layout in zip(
            manifest["records"], value.records, value.layout, strict=True):
        assert (rid, arm, mode, source) == (layout.record_id, layout.arm, layout.mode.value, layout.source_identity)
        assert text_sha == "sha256:" + hashlib.sha256(record.text.encode("utf-8")).hexdigest()
    assert value.representation_report_identity == digest_json(
        {"v1": v1.representation_report_identity, "public_text": manifest["preparation_identity"]})
    public = json.dumps(manifest, sort_keys=True) + repr(value)
    for private in ("BOUNDARY_START_TOKEN", "Locate RetrievalPipeline", CANARY):
        assert private not in public
    assert study.build().input_identity == value.input_identity
    assert study.build(study_identity="sha256:" + "6" * 64).input_identity != value.input_identity


@pytest.mark.parametrize("change,code", [
    ({"study_identity": "not-a-digest"}, "request_input_invalid"),
    ({"attempt_id": "bad attempt"}, "request_input_invalid"),
    ({"artifact_profile_identity": "sha256:" + "A" * 64}, "request_input_invalid"),
    ({"generation": True}, "request_input_invalid"), ({"preparation": None}, "request_input_invalid"),
    ({"generation": 2}, "request_correspondence_mismatch"),
])
def test_closed_input_refusals(tmp_path: Path, change: dict[str, Any], code: str) -> None:
    with pytest.raises(DualArmRequestRefusal) as error:
        _Study(tmp_path).build(**change)
    assert error.value.code == code


@pytest.mark.parametrize("case", ["census_without_preparation", "other_scope", "v1_without_queries", "foreign_census"])
def test_correspondence_drift_refuses(tmp_path: Path, case: str) -> None:
    study = _Study(tmp_path)
    parts = study.parts()
    if case == "census_without_preparation":
        parts["census"] = study.parts(with_preparation=False)["census"]
    elif case == "other_scope":
        study.scope = PrivateMarkerScope.create((CANARY,))
        parts["preparation"] = study.parts()["preparation"]
    elif case == "v1_without_queries":
        parts["v1_input"] = study.parts(v1_tasks=())["v1_input"]
    else:
        parts["census"] = replace(parts["census"], document_count=parts["census"].document_count + 1)
    with pytest.raises(DualArmRequestRefusal) as error:
        build_dual_arm_input(**parts)
    assert error.value.code == "request_correspondence_mismatch"


def test_publication_advance_refuses_as_current_drift(tmp_path: Path) -> None:
    study = _Study(tmp_path)
    parts = study.parts()
    study.cell.advance()
    with pytest.raises(DualArmRequestRefusal) as error:
        build_dual_arm_input(**parts)
    assert error.value.code == "request_current_mismatch"


def _text(record_id: str, text: str = "t", mode: SemanticMode = SemanticMode.DOCUMENT) -> SemanticText:
    return SemanticText(record_id, text, mode)


def test_generation_two_plans_documents_only_and_refuses_any_query() -> None:
    v1 = (_text("document:a"), _text("query:cal-23", "q", SemanticMode.QUERY))
    sources = {"document:a": "sha256:" + "1" * 64}
    records, layout = plan_records(
        generation=2, v1_records=v1[:1], v1_document_sources=sources, ptx_documents=(("sha256:" + "2" * 64, "p"),),
        ptx_query_task_ids=(), task_sources={})
    assert [r.partition for r in layout] == ["v1.document", "ptx.document"] and len(records) == 2
    assert all(r.mode is SemanticMode.DOCUMENT for r in layout)
    for v1_records, ptx_queries in ((v1, ()), (v1[:1], ("cal-23",))):
        with pytest.raises(DualArmRequestRefusal) as error:
            plan_records(
                generation=2, v1_records=v1_records, v1_document_sources=sources, ptx_documents=(),
                ptx_query_task_ids=ptx_queries, task_sources={"cal-23": "sha256:" + "3" * 64})
        assert error.value.code == "request_correspondence_mismatch"


def test_a_public_text_query_requires_the_matching_admitted_v1_query_text() -> None:
    with pytest.raises(DualArmRequestRefusal) as error:
        plan_records(
            generation=1, v1_records=(_text("document:a"),), v1_document_sources={"document:a": "sha256:" + "1" * 64},
            ptx_documents=(), ptx_query_task_ids=("cal-01",), task_sources={"cal-01": "sha256:" + "3" * 64})
    assert error.value.code == "request_correspondence_mismatch"


def _cap(records: list[SemanticText], request_bytes: int = 1) -> str | None:
    try:
        check_request_caps(tuple(records), request_bytes=request_bytes)
    except DualArmRequestRefusal as error:
        return error.code
    return None


def test_every_combined_cap_holds_exactly_at_its_boundary() -> None:
    assert _cap([_text(f"r{i}") for i in range(500)]) is None
    assert _cap([_text(f"r{i}") for i in range(501)]) == "request_cap_exceeded"
    assert _cap([_text("i" * 512)]) is None and _cap([_text("i" * 513)]) == "request_cap_exceeded"
    assert _cap([_text("é" * 256)]) is None and _cap([_text("é" * 256 + "i")]) == "request_cap_exceeded"
    assert _cap([_text("i" * 511 + "é")]) == "request_cap_exceeded"
    mib = 1024 * 1024
    assert _cap([_text("a", "x" * mib)]) is None and _cap([_text("a", "x" * (mib + 1))]) == "request_cap_exceeded"
    full = [_text(f"r{i}", "x" * mib) for i in range(8)]
    assert _cap(full) is None and _cap(full + [_text("extra", "y")]) == "request_cap_exceeded"
    assert _cap([_text("a")], MAX_REQUEST_BYTES) is None
    assert _cap([_text("a")], MAX_REQUEST_BYTES + 1) == "request_cap_exceeded"
    assert _cap([]) == "request_cap_exceeded"


def test_unicode_request_binds_retained_and_original_v1_digest_maps(tmp_path: Path) -> None:
    study = _Study(tmp_path, question="Find café")
    value = study.build()
    task = study.tasks.tasks[0]
    retained, semantic = retained_task_sha256(task), task_sha256(task)
    assert retained != semantic
    assert value.census.tasks[0].retained_task_sha256 == retained
    assert value.census.tasks[0].task_sha256 == value.v1.query_decisions[0].task_sha256 == semantic
    assert all(row.source_identity == retained for row in value.layout if row.task_id == task.task_id)
    assert value.manifest()["v1_query_task_digests"] == [[task.task_id, semantic]]
    assert value.manifest()["task_digest_schemes"]["retained"] == "canonical-json-ascii-v1"


@pytest.mark.parametrize("field", ["task_sha256", "retained_task_sha256"])
def test_swapping_task_digest_schemes_refuses_correspondence(tmp_path: Path, field: str) -> None:
    study = _Study(tmp_path, question="Find café")
    parts = study.parts()
    census = parts["census"]
    task = study.tasks.tasks[0]
    wrong = retained_task_sha256(task) if field == "task_sha256" else task_sha256(task)
    parts["census"] = replace(census, tasks=(replace(census.tasks[0], **{field: wrong}),))
    with pytest.raises(DualArmRequestRefusal) as error:
        build_dual_arm_input(**parts)
    assert error.value.code == "request_correspondence_mismatch"


def test_current_adapter_runtime_error_has_only_a_closed_request_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    study = _Study(tmp_path)
    parts = study.parts()
    def unavailable(_self: Any) -> Any:
        raise RuntimeError(CANARY)
    monkeypatch.setattr(type(study.cell), "__call__", unavailable)
    with pytest.raises(DualArmRequestRefusal) as error:
        build_dual_arm_input(**parts)
    assert error.value.code == "request_current_mismatch" and CANARY not in str(error.value)


def test_publication_identity_schemes_are_named_separately(tmp_path: Path) -> None:
    from retrieval_semantic_generator_inputs import _digest as v1_utf8_digest

    value = _Study(tmp_path).build()
    manifest = value.manifest()
    assert manifest["publication_identity_schemes"] == {"study": "canonical-json-ascii-v1",
                                                         "v1_worker_request": "canonical-json-utf8-v1"}
    assert manifest["v1_publication_identity"] == v1_utf8_digest(value.v1.provenance.to_dict())
    assert value.publication_identity == str(digest_json(value.pin.to_dict()))
    unicode_pin_mapping = {"graph_id": "caf\u00e9", "run_id": 1}
    assert str(digest_json(unicode_pin_mapping)) != v1_utf8_digest(unicode_pin_mapping)
