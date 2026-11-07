"""Cross-checks for V2 disclosures derived from recorded work."""

from __future__ import annotations

from collections.abc import Mapping

from retrieval_semantic_pair_artifacts import refuse


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value


def validate_generation_2_component_disclosure(disclosures: object, work: object) -> None:
    report_disclosures = _mapping(disclosures, "pair_v2_disclosures")
    limitation = _mapping(report_disclosures.get("generation_2_limitation"), "pair_v2_disclosures")
    component = _mapping(work, "pair_v2_generation_work")
    counts = _mapping(component.get("component_counts"), "pair_v2_component_counts")
    document = _mapping(limitation.get("document_only"), "pair_v2_disclosures")
    query = _mapping(limitation.get("component_querycount"), "pair_v2_disclosures")
    status = counts.get("status")
    if status == "recorded":
        values = _mapping(counts.get("values"), "pair_v2_component_counts")
        document_count = values.get("document_count")
        query_count = values.get("query_count")
        record_count = values.get("record_count")
        if any(type(value) is not int or value < 0 for value in (document_count, query_count, record_count)):
            raise refuse("pair_v2_component_counts")
        expected_document = {
            "value": query_count == 0 and document_count == record_count,
            "evidence_status": "recorded_sealed_response",
        }
        expected_query = {"value": query_count, "evidence_status": "recorded_sealed_response"}
        if dict(document) != expected_document or dict(query) != expected_query:
            raise refuse("pair_v2_disclosures")
    elif status == "not_recorded":
        expected = {"value": None, "evidence_status": "unknown"}
        legacy = {"value": None, "evidence_status": "not_recorded"}
        if dict(document) not in (expected, legacy) or dict(query) not in (expected, legacy):
            raise refuse("pair_v2_disclosures")
    else:
        raise refuse("pair_v2_component_counts")


__all__ = ["validate_generation_2_component_disclosure"]
