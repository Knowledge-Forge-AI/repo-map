"""Recursive closed report schemas, strict types and digests, seal recomputation and the functional marker.

Seals are real: synthetic raw members parsed by the unchanged parser and sealed
by ``seal_dual_arm_result``. Each tamper re-derives ``seal_identity`` so that the
recomputed per-arm values, not the identity digest, must catch it.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.storage.semantic_candidates import digest_json
from repomap_test_support.w5_public_text_artifacts import SyntheticStudy, synthetic_raw_component
from retrieval_public_text_report_contracts import (
    PublicTextReportRefusal, disclosures, validate_census, validate_cleanup, validate_fences, validate_imports,
    validate_indexes, validate_preparation, validate_request, validate_seal, validate_source,
)
from retrieval_public_text_request import ARM_PTX, ARM_V1, encode_dual_arm_request
from retrieval_public_text_response import seal_dual_arm_result
from retrieval_public_text_tasks import registered_task_pins
from retrieval_semantic_generator_kernel import SemanticMode

D = "sha256:" + "d" * 64


def _seals(root: Path) -> dict[str, dict[str, Any]]:
    study = SyntheticStudy(root)
    value = study.build()
    layout = value.layout
    first = {(row.arm, row.mode): i for i, row in reversed(list(enumerate(layout)))}
    variants = {"complete": frozenset(), "v1_truncated": frozenset({first[(ARM_V1, SemanticMode.DOCUMENT)]}),
                "ptx_query": frozenset({first[(ARM_PTX, SemanticMode.QUERY)]}),
                "ptx_document": frozenset({first[(ARM_PTX, SemanticMode.DOCUMENT)]})}
    seals = {}
    for name, truncated in variants.items():
        raw = synthetic_raw_component(root / name, encode_dual_arm_request(value), truncated=truncated)
        seals[name] = seal_dual_arm_result(value, raw.parse(), refresh=study.build, scope=study.scope).to_dict()
    return seals


@pytest.fixture(scope="module")
def seals(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    return _seals(tmp_path_factory.mktemp("seals"))


def _code(call: Any, *args: Any) -> str:
    with pytest.raises(PublicTextReportRefusal) as error:
        call(*args)
    return error.value.code


def _resealed(seal: dict[str, Any], mutate: Any) -> dict[str, Any]:
    value = copy.deepcopy(seal)
    mutate(value)
    value["seal_identity"] = str(digest_json({k: v for k, v in value.items() if k != "seal_identity"}))
    return value


def test_real_seals_validate_with_their_recomputed_capabilities(seals: dict[str, dict[str, Any]]) -> None:
    for seal in seals.values():
        assert validate_seal(seal, 1) is seal
    assert (seals["v1_truncated"]["arms"][ARM_V1]["capability"], seals["v1_truncated"]["arms"][ARM_V1]["refusal"]) \
        == ("refused", "v1_own_record_truncated")
    assert seals["ptx_query"]["arms"][ARM_PTX]["truncated_query_task_ids"] == ["cal-01"]
    assert seals["ptx_document"]["arms"][ARM_PTX]["truncated_document_identities"] != []
    assert validate_seal(None, 1) is None and _code(validate_seal, seals["complete"], 2) == "report_seal"


@pytest.mark.parametrize(("name", "mutate", "code"), [
    ("complete", lambda s: s["arms"][ARM_V1]["counts"].update(records=9), "report_seal_arm"),
    ("complete", lambda s: s["arms"][ARM_PTX]["exact_cost"].update(token_count_used=1), "report_seal_arm"),
    ("complete", lambda s: s["arms"][ARM_PTX]["exact_cost"].update(input_bytes=True), "report_seal_arm"),
    ("complete", lambda s: s["arms"][ARM_V1]["records"].pop(), "report_seal_arm"),
    ("complete", lambda s: s["arms"][ARM_V1]["records"][0].update(token_count_used=19), "report_seal_record"),
    ("complete", lambda s: s["arms"][ARM_V1]["records"][0].update(truncated=True), "report_seal_record"),
    ("complete", lambda s: s["arms"][ARM_V1]["records"][0].update(record_id="ptx.d.0001"), "report_seal_record"),
    ("complete", lambda s: s["arms"][ARM_PTX]["records"][0].update(mode="summary"), "report_seal_record"),
    ("complete", lambda s: s["arms"][ARM_PTX]["records"][0].update(source_identity="raw text"), "report_seal_record"),
    ("complete", lambda s: s["arms"][ARM_PTX].update(capability="token_partial"), "report_seal_capability"),
    ("complete", lambda s: s["arms"][ARM_PTX].update(token_partial=True), "report_seal_capability"),
    ("v1_truncated", lambda s: s["arms"][ARM_V1].update(capability="complete", refusal=None), "report_seal_capability"),
    ("ptx_query", lambda s: s["arms"][ARM_PTX].update(truncated_query_task_ids=[]), "report_seal_capability"),
    ("ptx_document", lambda s: s["arms"][ARM_PTX].update(truncated_document_identities=[]), "report_seal_capability"),
    ("ptx_query", lambda s: s.update(global_partial=False, global_status="complete"), "report_seal_partial"),
    ("complete", lambda s: s["arms"][ARM_PTX].update(publication_coverage="unknown"), "report_seal_arm"),
    ("complete", lambda s: s["arms"][ARM_PTX].update(time={"value": 1.0}), "report_seal_arm"),
    ("complete", lambda s: s["shared_cost"].update(total_seconds=-1.0), "report_seal"),
    ("complete", lambda s: s["records_returned"].update(value=1), "report_seal"),
    ("complete", lambda s: s["receipt_digests"].pop("admission"), "report_seal"),
    ("complete", lambda s: s.update(attempt_id="w5-semantic-g9"), "report_seal"),
    ("complete", lambda s: s.update(excerpt="text"), "report_seal"),
])
def test_resealed_tampering_is_caught_by_recomputation(seals: dict[str, dict[str, Any]], name: str, mutate: Any,
                                                       code: str) -> None:
    assert _code(validate_seal, _resealed(seals[name], mutate), 1) == code


def test_seal_identity_is_recomputed(seals: dict[str, dict[str, Any]]) -> None:
    tampered = copy.deepcopy(seals["complete"])
    tampered["global_status"] = "complete"
    tampered["shared_cost"]["load_seconds"] = 0.0
    assert _code(validate_seal, tampered, 1) == "report_seal_identity"


def test_census_preparation_request_are_closed_and_strict() -> None:
    pins = registered_task_pins()
    tasks = [{"task_id": t, "retained_task_sha256": d, "v1_query_task_sha256": d, "v1_learned_state": "admitted",
              "v1_learned_reason": None, "public_text_state": "unavailable", "public_text_reason": "x_reason"}
             for t, g, d in pins.tasks if g == 2]
    census = {"census_identity": D, "status": "document_only", "document_count": 1, "v1_verified_pair_count": 1,
              "tasks": tasks}
    assert validate_census(census, 2, pins) is census
    for mutate, code in ((lambda c: c.update(document_count=True), "report_census"),
                         (lambda c: c.update(status="maybe"), "report_census"),
                         (lambda c: c["tasks"][0].update(v1_learned_reason="Free Text"), "report_census_task"),
                         (lambda c: c["tasks"][0].update(task_sha256=D), "report_census_task"),
                         (lambda c: c["tasks"].append(dict(c["tasks"][0])), "report_census_retained_join"),
                         (lambda c: c["tasks"][0].update(retained_task_sha256=D), "report_census_retained_join")):
        value = copy.deepcopy(census)
        mutate(value)
        assert _code(validate_census, value, 2, pins) == code
    preparation = {"preparation_identity": D, "document_count": 1, "v1_verified_pair_count": 1, "exclusion_counts": {}}
    assert validate_preparation(preparation) is preparation
    preparation_bad: tuple[object, ...] = (
        {**preparation, "exclusion_counts": {"Reason X": 1}}, {**preparation, "exclusion_counts": {"r": 0}},
        {**preparation, "document_count": -1}, {**preparation, "extra": 1})
    for bad in preparation_bad:
        assert _code(validate_preparation, bad) == "report_preparation"
    request = {"input_identity": D, "records": 3, "documents": {ARM_V1: 1, ARM_PTX: 1},
               "queries": {ARM_V1: 1, ARM_PTX: 0}, "bytes": 10, "request_sha256": D}
    assert validate_request(request) is request and validate_request(None) is None
    for bad in ({**request, "records": 4}, {**request, "bytes": 0}, {**request, "documents": {ARM_V1: 1}},
                {**request, "queries": {ARM_V1: 1, ARM_PTX: False}}, {**request, "request_sha256": "sha256:x"}):
        assert _code(validate_request, bad) == "report_request"


def test_imports_indexes_fences_cleanup_and_source_are_closed() -> None:
    batch = "ptx1-g1-v1-" + "0" * 16
    item = {"arm": ARM_V1, "batch_id": batch, "capability": "complete", "row_count": 1, "seal_identity": D}
    assert validate_imports([item], 1) == [item]
    import_bad: tuple[object, ...] = (
        [{**item, "row_count": True}], [{**item, "capability": "refused"}], [item, item], [{**item, "x": 1}],
        [{**item, "batch_id": "ptx1-g2-v1-" + "0" * 16}], [{**item, "arm": ARM_PTX}], {})
    for bad in import_bad:
        assert _code(validate_imports, bad, 1) == "report_imports"
    index = {"arm": ARM_V1, "batch_id": batch, "state": "created"}
    assert validate_indexes([index]) == [index]
    for bad in ([{**index, "state": "valid"}], [index, index], [{**index, "name": "ptx_hnsw"}]):
        assert _code(validate_indexes, bad) == "report_indexes"
    fences = {"execution_kind": "synthetic_functional", "creation": "verified", "inventory": "verified",
              "publication": "current"}
    assert validate_fences(fences, True) is fences
    assert _code(validate_fences, fences, False) == "report_execution_kind"
    assert _code(validate_fences, {**fences, "inventory": "unknown"}, True) == "report_fences"
    cleanup = {"status": "clean", "reason": None, "objects": [{"kind": "constraint_index", "absent": True}]}
    assert validate_cleanup(cleanup) is cleanup
    for bad in ({**cleanup, "objects": [{"kind": "constraint_index", "absent": False}]},
                {**cleanup, "objects": [{"kind": "view", "absent": True}]}, {**cleanup, "reason": "x"},
                {"status": "failed", "reason": "Not A Code", "objects": []},
                {"status": "not_run", "reason": "cleanup_not_reached", "objects": [{"kind": "batch", "absent": True}]}):
        assert _code(validate_cleanup, bad) == "report_cleanup"
    source = {"q_source_closure": D, "artifact_profile_identity": D, "model_revision": "rev-1"}
    assert validate_source(source) is source
    for bad in ({**source, "model_revision": ""}, {**source, "model_revision": "é"}, {**source, "extra": 1}):
        assert _code(validate_source, bad) == "report_source"


def test_disclosures_follow_the_functional_marker_and_codes_are_closed() -> None:
    synthetic, native = disclosures(True), disclosures(False)
    assert set(synthetic) == set(native) and synthetic["execution"] != native["execution"]
    assert "never_proves_model_origin" in native["execution"] and "no_model_origin" in synthetic["execution"]
    with pytest.raises(ValueError):
        PublicTextReportRefusal("cell_fields")
