"""Strict report builder/writer/reader over parser-backed synthetic seals and real component journals.

Seals come from the unchanged parser and ``seal_dual_arm_result`` over synthetic
raw members; components are real filesystem journals joined by the unchanged
``verify_raw_component``. The data is explicitly synthetic and the report is
``functional_only: true``; it proves contracts only, never native or model
origin. The cases target gaps rather than mirror the builder: consistent
tampering that structure cannot see but evidence verification does, private
values, uncredited cells and the functional marker.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from common_lore_index.storage.semantic_candidates import digest_json
from repomap_test_support.w5_public_text_artifacts import (
    ARTIFACT_PROFILE, SyntheticStudy, component_journal, synthetic_raw_component,
)
from retrieval_public_text_contracts import PrivateMarkerScope
from retrieval_public_text_fusion import METRIC_KEYS
import retrieval_public_text_report as report_module
from retrieval_public_text_report import (
    PublicTextReportRefusal, ReportEvidence, build_report, census_summary, component_evidence, fences_summary,
    preparation_summary, read_report, read_verified_report, request_summary, seal_summary, validate_report,
    write_report,
)
import retrieval_public_text_report_joins as joins_module
from retrieval_public_text_report_cells import ARMS, HNSW_ARMS, INCUMBENT_ARMS, cell, expected_cell_keys
from retrieval_public_text_request import ARM_PTX, ARM_V1, encode_dual_arm_request
from retrieval_public_text_response import seal_dual_arm_result
from retrieval_public_text_study_schema import StudyNames
from retrieval_public_text_tasks import SELECTED_TASKS, load_selected_calibration_tasks, registered_task_pins
from retrieval_semantic_pair_artifacts import digest_bytes

CATALOG = Path(__file__).resolve().parents[3] / "fixtures" / "retrieval_evaluation" / "mixed-v1" / "tasks" / "catalog-v1.json"
D = "sha256:" + "d" * 64
NAMES = StudyNames(D)
RESULT = {"sha256": "sha256:" + "e" * 64, "length": 7}
METRICS = {name: 0.25 for name in METRIC_KEYS}
CANARY = "CANARY-PRIVATE-HOME-7731"
REASON = "unsupported_semantic_query_mode"

class _Fixture:
    def __init__(self, root: Path) -> None:
        self.tasks = load_selected_calibration_tasks(CATALOG, registered_task_pins())
        self.parts: dict[int, dict[str, Any]] = {}
        for generation in (1, 2):
            study = SyntheticStudy(root / f"study-{generation}", generation=generation, registered_tasks=self.tasks)
            value = study.build()
            raw = synthetic_raw_component(root / f"model-{generation}", encode_dual_arm_request(value))
            seal = seal_dual_arm_result(value, raw.parse(), refresh=study.build, scope=study.scope)
            journal = component_journal(root / f"journal-{generation}", raw, generation=generation, arms=ARMS,
                                        task_ids=[t for t, g, _d in SELECTED_TASKS if g == generation])
            self.parts[generation] = {"value": value, "raw": raw, "seal": seal, "journal": journal}

    def evidence(self, scope: PrivateMarkerScope | None = None) -> ReportEvidence:
        return ReportEvidence({g: (p["journal"], dict(p["raw"].members)) for g, p in self.parts.items()}, self.tasks,
                              scope)

    def census(self, generation: int) -> dict[str, Any]:
        return census_summary(self.parts[generation]["value"].census)

    def cells(self) -> list[dict[str, Any]]:
        return _cells([self.row(1), self.row(2)])

    def row(self, generation: int) -> dict[str, Any]:
        part = self.parts[generation]
        seal, value = part["seal"], part["value"]
        imports = [{"arm": arm, "batch_id": NAMES.batch_id(generation, arm), "capability": seal.arms[arm].capability,
                    "row_count": seal.arms[arm].counts["documents"], "seal_identity": seal.seal_identity}
                   for arm in (ARM_V1, ARM_PTX)]
        return {"generation": generation, "publication_identity": value.publication_identity,
                "census": self.census(generation), "preparation": preparation_summary(value.preparation),
                "request": request_summary(value, part["raw"].request_raw),
                **component_evidence(part["journal"], dict(part["raw"].members)), "seal": seal_summary(seal),
                "imports": imports, "indexes": [{"arm": i["arm"], "batch_id": i["batch_id"], "state": "created"}
                                                for i in imports],
                "fences": fences_summary(functional_only=True, creation="verified", inventory="verified",
                                         publication="current")}

    def report(self, **changes: Any) -> dict[str, Any]:
        rows = [self.row(1), self.row(2)]
        kwargs = {"study_identity": D, "selected_task_set_identity": self.tasks.identity(),
                  "source": {"q_source_closure": D, "artifact_profile_identity": ARTIFACT_PROFILE,
                             "model_revision": "synthetic-rev-1"},
                  "functional_only": True, "generations": rows, "cells": _cells(rows),
                  "cleanup": _cleanup(), **changes}
        return build_report(**kwargs)

def _cells(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_task = {(row["generation"], task["task_id"]): task for row in rows for task in row["census"]["tasks"]}
    cells = []
    for generation, task_id, digest, arm, repetition in expected_cell_keys():
        identity = {"generation": generation, "task_id": task_id, "task_sha256": digest, "arm": arm,
                    "repetition": repetition}
        source = "v1_decision" if arm.endswith(ARM_V1) else "public_text_decision"
        if arm in INCUMBENT_ARMS:
            cells.append(cell(**cast(dict[str, Any], identity), state="completed", metrics=METRICS, result=RESULT))
        elif generation == 1 and by_task[(generation, task_id)][
                "v1_learned_state" if arm.endswith(ARM_V1) else "public_text_state"] == "admitted":
            plan = {**RESULT, "index_selected": True} if arm in HNSW_ARMS else None
            cells.append(cell(**cast(dict[str, Any], identity), state="completed", capability="complete",
                              metrics=METRICS, result=RESULT,
                              plan=plan, publication_coverage=rows[generation - 1]["seal"]["arms"][
                                  ARM_V1 if arm.endswith(ARM_V1) else ARM_PTX]["publication_coverage"]))
        else:
            task = by_task[(generation, task_id)]
            prefix = "v1_learned" if arm.endswith(ARM_V1) else "public_text"
            state = "refused" if task[prefix + "_state"] == "refused" else "unavailable"
            cells.append(cell(**cast(dict[str, Any], identity), state=state,
                              reason=(source, task[prefix + "_reason"] or REASON)))
    return cells


def _cleanup(**changes: Any) -> dict[str, Any]:
    kinds = ["batch", "entry"] + ["constraint_index"] * 4 + ["index"] * 4
    return {"status": "clean", "reason": None, "objects": [{"kind": k, "absent": True} for k in kinds], **changes}


@pytest.fixture(scope="module")
def fixture(tmp_path_factory: pytest.TempPathFactory) -> _Fixture:
    return _Fixture(tmp_path_factory.mktemp("report"))


def _code(call: Any, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(PublicTextReportRefusal) as error:
        call(*args, **kwargs)
    return error.value.code


def _invalid(report: dict[str, Any], mutate: Any) -> str:
    tampered = copy.deepcopy(report)
    mutate(tampered)
    return _code(validate_report, tampered)


def _reseal(row: dict[str, Any]) -> None:
    """A self-consistent rewrite: recompute the seal identity and carry it into every import."""
    seal = row["seal"]
    seal["seal_identity"] = str(digest_json({k: v for k, v in seal.items() if k != "seal_identity"}))
    for item in row["imports"]:
        item["seal_identity"] = seal["seal_identity"]


def _write(path: Path, report: dict[str, Any]) -> Path:
    path.write_bytes(json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n")
    return path


def test_parser_backed_report_round_trips_structural_and_evidence_verified(fixture: _Fixture, tmp_path: Path) -> None:
    report = fixture.report()
    assert report["observation_status"] == "all_cells_observed" and report["functional_only"] is True
    assert all(flag is False for flag in report["acceptance"].values()) and len(report["cells"]) == 864
    assert {row["fences"]["execution_kind"] for row in report["generations"]} == {"synthetic_functional"}
    assert report["generations"][0]["elapsed_seconds"] == {"value": 3.0}
    assert report["disclosures"]["verification"].endswith("reader_structural_only_without_evidence_context")
    path = tmp_path.resolve() / "report.json"
    identity = write_report(path, report)
    assert identity == digest_bytes(path.read_bytes())
    structural = read_report(path)
    assert (structural.report, structural.identity, structural.verification) == (report, identity, "structural_only")
    verified = read_verified_report(path, fixture.evidence())
    assert verified.verification == "raw_evidence_verified"
    with pytest.raises(FileExistsError):
        write_report(path, report)
    assert _code(read_verified_report, path, None) == "report_evidence"


def test_consistent_component_tamper_passes_structure_but_fails_evidence_verification(
        fixture: _Fixture, tmp_path: Path) -> None:
    """The structural reader cannot see a self-consistent rewrite; only actual members expose it."""
    report = fixture.report()
    tampered = copy.deepcopy(report)
    row = tampered["generations"][0]
    for name in ("recorded_component_digests", "verified_component_digests"):
        row["component"][name]["report"] = D
    seal = row["seal"]
    seal["receipt_digests"]["report"] = D
    _reseal(row)
    validate_report(tampered)
    path = _write(tmp_path.resolve() / "tampered.json", tampered)
    assert read_report(path).verification == "structural_only"
    assert _code(read_verified_report, path, fixture.evidence()) == "report_evidence_component"


def test_evidence_binds_both_task_digest_schemes_to_the_actual_task_objects(fixture: _Fixture, tmp_path: Path) -> None:
    report = fixture.report()
    tampered = copy.deepcopy(report)
    row = next(t for t in tampered["generations"][0]["census"]["tasks"] if t["task_id"] == "cal-20")
    assert row["v1_query_task_sha256"] != row["retained_task_sha256"]
    row["v1_query_task_sha256"] = row["retained_task_sha256"]
    validate_report(tampered)
    path = _write(tmp_path.resolve() / "tasks.json", tampered)
    assert _code(read_verified_report, path, fixture.evidence()) == "report_evidence_tasks"
    good = write_report(tmp_path.resolve() / "good.json", report)
    assert good.startswith("sha256:")
    swapped = ReportEvidence({1: fixture.evidence().components[2], 2: fixture.evidence().components[1]}, fixture.tasks)
    assert _code(read_verified_report, tmp_path.resolve() / "good.json", swapped).startswith("report_evidence")


def test_seal_recomputation_rejects_a_consistently_resealed_response_mismatch(fixture: _Fixture, tmp_path: Path) -> None:
    report = fixture.report()
    tampered = copy.deepcopy(report)
    seal = tampered["generations"][0]["seal"]
    seal["shared_cost"]["load_seconds"] = 0.25
    _reseal(tampered["generations"][0])
    validate_report(tampered)
    path = _write(tmp_path.resolve() / "resealed.json", tampered)
    assert _code(read_verified_report, path, fixture.evidence()) == "report_evidence_seal"


def test_functional_marker_is_strict_mandatory_and_matches_every_fence(fixture: _Fixture) -> None:
    for value in ("true", 1, None):
        assert _code(fixture.report, functional_only=value) == "report_functional_only"
    assert _code(fixture.report, functional_only=False) == "report_execution_kind"
    report = fixture.report()
    assert _invalid(report, lambda r: r.pop("functional_only")) == "report_fields"
    assert _invalid(report, lambda r: r.update(functional_only=False)) == "report_execution_kind"
    assert _invalid(report, lambda r: r["generations"][1]["fences"].update(execution_kind="native")) \
        == "report_execution_kind"


def test_missing_imports_indexes_or_fences_never_credit_completed_cells(fixture: _Fixture) -> None:
    report = fixture.report()
    assert _invalid(report, lambda r: r["generations"][0]["imports"].pop(0)) in {"report_learned_uncredited",
                                                                               "report_indexes_join"}
    assert _invalid(report, lambda r: r["generations"][0]["indexes"].pop(1)) == "report_learned_uncredited"
    assert _invalid(report, lambda r: r["generations"][0]["fences"].update(publication="stale")) \
        == "report_learned_uncredited"
    assert _invalid(report, lambda r: r["generations"][0]["fences"].update(inventory="changed")) == "report_imports_join"
    assert _invalid(report, lambda r: r["generations"][0]["imports"][0].update(row_count=2)) == "report_imports_join"
    assert _invalid(report, lambda r: r["generations"][0].update(seal=None)) in {"report_imports_join",
                                                                              "report_learned_completed"}


def test_extra_fields_and_free_text_cannot_enter_any_nested_shape(fixture: _Fixture) -> None:
    report = fixture.report()
    row = "generations"
    cases = {
        "report_fields": lambda r: r.update(extra=1),
        "report_generation": lambda r: r[row][0].update(extra=1),
        "report_census_task": lambda r: r[row][0]["census"]["tasks"][0].update(question="free text"),
        "report_census": lambda r: r[row][0]["census"].update(extra=1),
        "report_preparation": lambda r: r[row][0]["preparation"].update(excerpt="body"),
        "report_request": lambda r: r[row][0]["request"].update(text="body"),
        "report_seal_record": lambda r: r[row][0]["seal"]["arms"][ARM_PTX]["records"][0].update(text="body"),
        "report_seal_arm": lambda r: r[row][0]["seal"]["arms"][ARM_V1].update(vectors=[]),
        "report_imports": lambda r: r[row][0]["imports"][0].update(rows=[]),
        "report_indexes": lambda r: r[row][0]["indexes"][0].update(plan="x"),
        "report_fences": lambda r: r[row][0]["fences"].update(note="x"),
        "report_cleanup": lambda r: r["cleanup"]["objects"][0].update(name="ptx_batch"),
        "report_source": lambda r: r["source"].update(model_revision="line\nbreak"),
    }
    for code, mutate in cases.items():
        assert _invalid(report, mutate) == code, code


def test_private_values_are_refused_by_builder_writer_and_reader(fixture: _Fixture, tmp_path: Path) -> None:
    scope = PrivateMarkerScope.create((CANARY,))
    marked = {"q_source_closure": D, "artifact_profile_identity": ARTIFACT_PROFILE, "model_revision": CANARY}
    assert _code(fixture.report, source=marked, scope=scope) == "report_private_value"
    hosted = {**marked, "model_revision": "/Users/someone/model"}
    assert _code(fixture.report, source=hosted) == "report_private_value"
    report = fixture.report(source=marked)
    path = tmp_path.resolve() / "marked.json"
    write_report(path, report)
    assert read_report(path).verification == "structural_only"
    assert _code(read_report, path, evidence=fixture.evidence(scope)) == "report_private_value"
    assert _code(write_report, tmp_path.resolve() / "m2.json", report, scope=scope) == "report_private_value"
    host = copy.deepcopy(report)
    host["source"]["model_revision"] = "/home/x"
    assert _code(read_report, _write(tmp_path.resolve() / "host.json", host)) == "report_private_value"


def test_unknown_is_never_zero_and_cleanup_must_match_the_recorded_inventory(fixture: _Fixture) -> None:
    cells = fixture.cells()
    identity = {k: cells[0][k] for k in ("generation", "task_id", "task_sha256", "arm", "repetition")}
    cells[0] = cell(**identity, state="unknown", reason=("native", "worker_response_absent"))
    report = fixture.report(cells=cells)
    assert report["observation_status"] == "incomplete" and report["counts"]["states"]["unknown"] == {"value": 1}
    assert _invalid(report, lambda r: r.update(observation_status="all_cells_observed")) == "report_observation_status"
    failed = fixture.report(cleanup=_cleanup(status="failed", reason="cleanup_failed:relation_identity_changed",
                                             objects=[{"kind": "batch", "absent": False}, {"kind": "entry", "absent": False}]
                                             + [{"kind": "constraint_index", "absent": False}] * 4
                                             + [{"kind": "index", "absent": False}] * 4))
    assert failed["observation_status"] == "incomplete"
    assert _code(fixture.report, cleanup=_cleanup(objects=[{"kind": "batch", "absent": True}])) == "report_cleanup_join"
    assert _code(fixture.report, cleanup=_cleanup(status="not_run", reason="cleanup_not_reached", objects=[])) \
        == "report_cleanup_join"


def test_report_and_component_caps(fixture: _Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = fixture.report()
    monkeypatch.setattr(report_module, "MAX_REPORT_BYTES", 4096)
    assert _code(write_report, tmp_path.resolve() / "big.json", report) == "report_size"
    monkeypatch.setattr(joins_module, "MAX_DOSSIER_BYTES", 64)
    assert _code(validate_report, report) == "report_component_size"


def test_query_digest_must_join_the_actual_census_task(fixture: _Fixture) -> None:
    report = fixture.report()
    row = report["generations"][0]
    for arm in (ARM_V1, ARM_PTX):
        tampered = copy.deepcopy(report)
        changed = tampered["generations"][0]
        query = next(record for record in changed["seal"]["arms"][arm]["records"] if record["mode"] == "query")
        query["source_identity"] = "sha256:" + "0" * 64
        _reseal(changed)
        assert _code(validate_report, tampered) == "report_query_task_join"
    assert all(part["value"].tasks is fixture.tasks for part in fixture.parts.values())
    assert row["request"]["queries"] == {ARM_V1: 4, ARM_PTX: 4}


def test_generation_bool_and_float_are_not_integer_generation(fixture: _Fixture) -> None:
    for invalid in (True, 1.0):
        report = fixture.report()
        report["generations"][0]["generation"] = invalid
        assert _code(validate_report, report) == "report_generation"
        report = fixture.report()
        report["generations"][0]["seal"]["generation"] = invalid
        _reseal(report["generations"][0])
        assert _code(validate_report, report) == "report_seal"


def test_self_consistent_raw_query_text_drift_fails_real_task_verification(
        fixture: _Fixture, tmp_path: Path) -> None:
    report = fixture.report()
    request = json.loads(fixture.parts[1]["raw"].request_raw)
    query = next(record for record in request["records"] if record["mode"] == "query")
    question = query["text"]
    query["text"] = ("X" if question[0] != "X" else "Y") + question[1:]
    request_raw = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    raw = synthetic_raw_component(tmp_path / "model", request_raw)
    journal = component_journal(tmp_path / "journal", raw, generation=1, arms=ARMS,
                                task_ids=[task.task_id for task in fixture.tasks.for_generation(1)])
    row = report["generations"][0]
    row.update(component_evidence(journal, dict(raw.members)))
    row["request"].update(request_sha256=digest_bytes(request_raw), bytes=len(request_raw))
    row["seal"]["response_identity"] = raw.parse()._sealed_identity
    roles = {"request": "request", "report": "report", "terminal": "terminal", "declaration": "declaration",
             "manifest": "source_manifest", "archive": "sources_archive", "admission": "admission"}
    row["seal"]["receipt_digests"] = {key: raw.digests[role] for key, role in roles.items()}
    _reseal(row)
    validate_report(report)
    evidence = ReportEvidence({1: (journal, dict(raw.members)), 2: fixture.evidence().components[2]}, fixture.tasks)
    path = _write(tmp_path.resolve() / "question-drift.json", report)
    assert read_report(path).verification == "structural_only"
    assert _code(read_verified_report, path, evidence) == "report_evidence_query_tasks"


def test_count_values_require_exact_int_even_when_they_compare_equal(fixture: _Fixture, tmp_path: Path) -> None:
    report = fixture.report()
    assert report["counts"]["file_grading"]["verified"]["value"] > 0
    states = [name for name, item in report["counts"]["states"].items() if item["value"] in (0, 1)] or ["x"]
    for convert in (lambda v: bool(v), lambda v: float(v)):
        tampered = copy.deepcopy(report)
        item = tampered["counts"]["states"][states[0]]
        item["value"] = convert(item["value"])
        assert _code(validate_report, tampered) == "report_counts"
        path = _write(tmp_path.resolve() / f"count-{type(item['value']).__name__}.json", tampered)
        assert _code(read_report, path) == "report_counts"
    grading = copy.deepcopy(report)
    grading["counts"]["file_grading"]["verified"]["value"] = float(grading["counts"]["file_grading"]["verified"]["value"])
    assert _code(validate_report, grading) == "report_counts"


def test_sealed_per_arm_counts_refuse_bool_even_after_a_consistent_reseal(fixture: _Fixture) -> None:
    report = fixture.report()
    tampered = copy.deepcopy(report)
    row = tampered["generations"][1]
    counts = row["seal"]["arms"][ARM_PTX]["counts"]
    assert counts["queries"] == 0
    counts["queries"] = False
    _reseal(row)
    assert _code(validate_report, tampered).startswith("report_seal")


def test_file_grading_is_separate_from_execution_state(fixture: _Fixture) -> None:
    report = fixture.report()
    incumbent = next(c for c in report["cells"] if c["arm"] in ARMS[:6] and c["state"] == "completed")
    learned = next(c for c in report["cells"] if c["arm"] not in ARMS[:6] and c["state"] == "completed")
    gap = {**incumbent, "metrics": None, "file_grading": {"state": "gap", "reason": "file_metric_provenance_unresolved"}}
    tampered = copy.deepcopy(report)
    tampered["cells"][report["cells"].index(incumbent)] = gap
    tampered["counts"] = report_module._counts(tampered["cells"])
    validate_report(tampered)
    assert tampered["counts"]["states"] == report["counts"]["states"]
    assert tampered["counts"]["file_grading"]["gap"]["value"] == report["counts"]["file_grading"]["gap"]["value"] + 1
    learned_gap = {**learned, "metrics": None, "file_grading": {"state": "gap", "reason": "file_metric_gap"}}
    assert _invalid(report, lambda r: r["cells"].__setitem__(r["cells"].index(learned), learned_gap)) \
        == "report_cell_file_grading_state"
    zeroed = {**gap, "metrics": {k: 0.0 for k in METRICS}}
    assert _invalid(report, lambda r: r["cells"].__setitem__(r["cells"].index(incumbent), zeroed)) \
        == "report_cell_metrics_state"
