"""Generation, cell and cleanup joins and the evidence-context boundary over parser-backed generation rows."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.storage.semantic_candidates import digest_json
from repomap_test_support.w5_public_text_artifacts import (
    ARTIFACT_PROFILE, SyntheticStudy, component_journal, synthetic_raw_component,
)
from retrieval_public_text_report import census_summary, fences_summary, preparation_summary, request_summary, seal_summary
from retrieval_public_text_report_cells import ARMS, LEARNED_ARMS, cell
from retrieval_public_text_report_contracts import PublicTextReportRefusal
from retrieval_public_text_report_joins import (
    ReportEvidence, component_evidence, join_cells, join_cleanup, validate_generation, verify_evidence,
)
from retrieval_public_text_request import ARM_PTX, ARM_V1, encode_dual_arm_request
from retrieval_public_text_response import seal_dual_arm_result
from retrieval_public_text_study_schema import StudyNames
from retrieval_public_text_tasks import SELECTED_TASKS, load_selected_calibration_tasks, registered_task_pins

D = "sha256:" + "d" * 64
NAMES = StudyNames(D)
PINS = registered_task_pins()
CATALOG = Path(__file__).resolve().parents[3] / "fixtures" / "retrieval_evaluation" / "mixed-v1" / "tasks" / "catalog-v1.json"
REASON = "unsupported_semantic_query_mode"
METRICS = {name: 0.5 for name in ("file_recall@1", "file_mrr@1", "file_ndcg@1", "file_recall@3", "file_mrr@3",
                                  "file_ndcg@3", "file_recall@5", "file_mrr@5", "file_ndcg@5", "file_recall@10",
                                  "file_mrr@10", "file_ndcg@10")}
RESULT = {"sha256": "sha256:" + "e" * 64, "length": 3}


def _row(root: Path) -> tuple[dict[str, Any], Any, Any]:
    tasks = load_selected_calibration_tasks(CATALOG, PINS)
    study = SyntheticStudy(root, registered_tasks=tasks)
    value = study.build()
    raw = synthetic_raw_component(root / "model", encode_dual_arm_request(value))
    seal = seal_dual_arm_result(value, raw.parse(), refresh=study.build, scope=study.scope)
    journal = component_journal(root / "journal", raw, generation=1, arms=ARMS,
                                task_ids=[t for t, g, _d in SELECTED_TASKS if g == 1])
    prep = preparation_summary(value.preparation)
    imports = [{"arm": arm, "batch_id": NAMES.batch_id(1, arm), "capability": seal.arms[arm].capability,
                "row_count": seal.arms[arm].counts["documents"],
                "seal_identity": seal.seal_identity} for arm in (ARM_V1, ARM_PTX)]
    row = {"generation": 1, "publication_identity": value.publication_identity,
           "census": census_summary(value.census),
           "preparation": prep, "request": request_summary(value, raw.request_raw),
           **component_evidence(journal, dict(raw.members)), "seal": seal_summary(seal), "imports": imports,
           "indexes": [{"arm": i["arm"], "batch_id": i["batch_id"], "state": "created"} for i in imports],
           "fences": fences_summary(functional_only=True, creation="verified", inventory="verified",
                                    publication="current")}
    return row, journal, raw


@pytest.fixture(scope="module")
def generation(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], Any, Any]:
    return _row(tmp_path_factory.mktemp("joins"))


def _code(call: Any, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(PublicTextReportRefusal) as error:
        call(*args, **kwargs)
    return error.value.code


def _validate(row: dict[str, Any], *, functional_only: bool = True) -> Any:
    return validate_generation(row, 1, PINS, functional_only, ARTIFACT_PROFILE)


def _reseal(row: dict[str, Any]) -> None:
    seal = row["seal"]
    seal["seal_identity"] = str(digest_json({k: v for k, v in seal.items() if k != "seal_identity"}))
    for item in row["imports"]:
        item["seal_identity"] = seal["seal_identity"]


def test_actual_generation_row_satisfies_every_join(generation: tuple[dict[str, Any], Any, Any]) -> None:
    row = generation[0]
    assert _validate(copy.deepcopy(row)) == row
    assert _code(validate_generation, copy.deepcopy(row), 1, PINS, True, D) == "report_source_join"


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda r: r["census"].update(document_count=r["census"]["document_count"] + 1), "report_preparation_join"),
    (lambda r: r["census"].update(status="document_only"), "report_preparation_join"),
    (lambda r: r["census"].update(status="preparation_absent"), "report_preparation_join"),
    (lambda r: r.update(preparation=None), "report_preparation_join"),
    (lambda r: r["request"]["documents"].update({ARM_PTX: r["request"]["documents"][ARM_PTX] + 1})
     or r["request"].update(records=r["request"]["records"] + 1), "report_request_join"),
    (lambda r: r["request"].update(input_identity=D), "report_seal_request_join"),
    (lambda r: r["request"].update(request_sha256=D), "report_seal_request_join"),
    (lambda r: r.update(publication_identity=D), "report_seal_request_join"),
    (lambda r: [t.update(public_text_state="unavailable", public_text_reason=REASON) for t in r["census"]["tasks"]]
     and r["census"].update(status="document_only"), "report_request_join"),
    (lambda r: r["imports"][1].update(capability="token_partial"), "report_imports_join"),
    (lambda r: r["imports"][0].update(seal_identity=D), "report_imports_join"),
    (lambda r: r["indexes"][0].update(batch_id=NAMES.batch_id(1, ARM_PTX)), "report_indexes_join"),
    (lambda r: r["fences"].update(creation="failed"), "report_imports_join"),
    (lambda r: r["component"]["verified_counts"].update(record_count=99), "report_component:dossier_count_algebra"),
    (lambda r: r.update(component_status={"state": "recorded", "reason": "component_x"}), "report_component_status"),
    (lambda r: r.update(elapsed_seconds={"value": 1.0, "unknown": "x"}), "report_elapsed"),
])
def test_each_generation_join_refuses(generation: tuple[dict[str, Any], Any, Any], mutate: Any, code: str) -> None:
    row = copy.deepcopy(generation[0])
    mutate(row)
    assert _code(_validate, row) == code


def test_seal_census_and_component_joins_survive_only_consistent_values(
        generation: tuple[dict[str, Any], Any, Any]) -> None:
    row = copy.deepcopy(generation[0])
    row["seal"]["records_returned"]["value"] = False
    _reseal(row)
    assert _code(_validate, row) == "report_seal_component_counts"
    row = copy.deepcopy(generation[0])
    row["seal"]["arms"][ARM_PTX]["publication_coverage"] = "partial"
    _reseal(row)
    assert _code(_validate, row) == "report_seal_census_join"
    row = copy.deepcopy(generation[0])
    row["census"]["tasks"][0]["task_id"] = "cal-99"
    assert _code(_validate, row) == "report_census_retained_join"
    assert _code(_validate, copy.deepcopy(generation[0]), functional_only=False) == "report_execution_kind"


def _cells(row: dict[str, Any], state: str = "completed", **changes: Any) -> list[dict[str, Any]]:
    task = row["census"]["tasks"][0]
    base = {"generation": 1, "task_id": task["task_id"], "task_sha256": task["retained_task_sha256"], "repetition": 1}
    out = []
    for arm in LEARNED_ARMS:
        plan = {**RESULT, "index_selected": True} if arm.startswith("hnsw_vector:") else None
        out.append(cell(**base, arm=arm, state=state, capability="complete", metrics=METRICS, result=RESULT,
                        plan=plan, publication_coverage="complete", **changes))
    return out


def test_completed_learned_cells_need_decision_seal_import_index_and_fences(
        generation: tuple[dict[str, Any], Any, Any]) -> None:
    row = generation[0]
    join_cells(_cells(row), [row])
    cases = [
        (lambda r: r["imports"].pop(0), "report_learned_uncredited"),
        (lambda r: r["indexes"].pop(1), "report_learned_uncredited"),
        (lambda r: r["fences"].update(publication="stale"), "report_learned_uncredited"),
        (lambda r: r["fences"].update(inventory="changed"), "report_learned_uncredited"),
        (lambda r: r.update(seal=None), "report_learned_completed"),
        (lambda r: r["census"]["tasks"][0].update(public_text_state="refused", public_text_reason="x"),
         "report_decision_retained"),
        (lambda r: r["seal"]["arms"][ARM_V1].update(capability="refused"), "report_learned_completed"),
        (lambda r: r["seal"]["arms"][ARM_PTX].update(publication_coverage="partial"), "report_capability_join"),
    ]
    for mutate, code in cases:
        mutated = copy.deepcopy(row)
        mutate(mutated)
        assert _code(join_cells, _cells(row), [mutated]) == code


def test_original_decisions_are_retained_for_non_admitted_tasks(generation: tuple[dict[str, Any], Any, Any]) -> None:
    row = generation[0]
    task = next(t for t in row["census"]["tasks"] if t["v1_learned_state"] == "unavailable")
    base = {"generation": 1, "task_id": task["task_id"], "task_sha256": task["retained_task_sha256"], "repetition": 1,
            "arm": LEARNED_ARMS[0]}
    retained_reason = task["v1_learned_reason"]
    join_cells([cell(**base, state="unavailable", reason=("v1_decision", retained_reason))], [row])
    for reason in (("v1_decision", "other_reason"), ("public_text_decision", retained_reason),
                   ("study", "study_not_reached")):
        assert _code(join_cells, [cell(**base, state="unavailable", reason=reason)], [row]) == "report_decision_retained"


def test_cleanup_objects_equal_the_recorded_inventory(generation: tuple[dict[str, Any], Any, Any]) -> None:
    row = generation[0]
    objects: list[dict[str, object]] = [{"kind": k, "absent": True} for k in (
        "batch", "entry", "constraint_index", "constraint_index", "constraint_index", "constraint_index", "index",
        "index")]
    full = {"status": "clean", "reason": None, "objects": objects}
    join_cleanup(full, [row])
    for changed_objects in (objects[:-1], objects + [{"kind": "index", "absent": True}], objects[:2]):
        assert _code(join_cleanup, {**full, "objects": changed_objects}, [row]) == "report_cleanup_join"
    assert _code(join_cleanup, {"status": "not_run", "reason": "cleanup_not_reached", "objects": []}, [row]) \
        == "report_cleanup_join"
    unreached = copy.deepcopy(row)
    unreached.update(imports=[], indexes=[])
    unreached["fences"]["creation"] = "not_reached"
    join_cleanup({"status": "clean", "reason": None, "objects": objects[:2]}, [unreached])
    join_cleanup({"status": "not_run", "reason": "cleanup_not_reached", "objects": []}, [unreached])


def test_evidence_context_is_closed_and_bound_to_registered_tasks(
        generation: tuple[dict[str, Any], Any, Any], tmp_path: Path) -> None:
    row, journal, raw = generation
    study = SyntheticStudy(tmp_path)
    report = {"task_pins": {"selected_task_set_identity": study.tasks.identity()}, "generations": [row, row]}
    pair = (journal, dict(raw.members))
    assert _code(verify_evidence, report, ReportEvidence({1: pair}, study.tasks)) == "report_evidence"
    assert _code(verify_evidence, report, {"components": {1: pair, 2: pair}}) == "report_evidence"
    assert _code(verify_evidence, report, ReportEvidence({1: pair, 2: pair}, study.tasks)) == "report_evidence_tasks"
    assert component_evidence(journal, dict(raw.members))["component"] == row["component"]
    assert _code(component_evidence, None, None) == "report_component_reason"
    with pytest.raises(PublicTextReportRefusal) as error:
        component_evidence(journal, {**raw.members, "report.json": raw.members["report.json"] + b" "})
    assert error.value.code.startswith("report_component:")
