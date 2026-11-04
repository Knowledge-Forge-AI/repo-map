"""Stored cost and component-count projections for the W5 V2 report."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from retrieval_semantic_pair_artifacts import JournalArtifact, refuse
from retrieval_semantic_pair_v2_cost_fields import (
    COMPONENT_COST as _COMPONENT_COST,
    COMPONENT_INTEGER as _COMPONENT_INTEGER,
    CORRESPONDENCE_COST as _CORRESPONDENCE_COST,
    CORRESPONDENCE_INTEGER as _CORRESPONDENCE_INTEGER,
    GENERATION_COST as _GENERATION_COST,
    GENERATION_INTEGER as _GENERATION_INTEGER,
    OBSERVATION_BYTES as _OBSERVATION_BYTES,
    OBSERVATION_INTEGER as _OBSERVATION_INTEGER,
    RESULT_BYTES as _RESULT_BYTES,
    RESULT_INTEGER as _RESULT_INTEGER,
    byte_map as _byte_map,
    mapping as _mapping,
    number as _number,
    numeric_map as _numeric_map,
    validate_byte_map as _validate_byte_map,
    validate_numeric_map as _validate_numeric_map,
)
_COMPONENT_DIGESTS = frozenset(
    {
        "admission",
        "declaration",
        "report",
        "request",
        "source_manifest",
        "sources_archive",
        "terminal",
    }
)
_COUNT_FIELDS = frozenset({"record_count", "embedding_count", "document_count", "query_count"})


def _component_identity(journal: JournalArtifact) -> dict[str, object]:
    raw = journal.report.get("component")
    if raw is None:
        return {"report_sha256": journal.member_digests["report.json"], "component_digests": None}
    component = _mapping(raw, "pair_v2_component_identity")
    if frozenset(component) != _COMPONENT_DIGESTS:
        raise refuse("pair_v2_component_identity")
    digests: dict[str, object] = {}
    for key, value in component.items():
        if type(key) is not str or type(value) is not str:
            raise refuse("pair_v2_component_identity")
        if len(value) != 71 or not value.startswith("sha256:") or any(
            char not in "0123456789abcdef" for char in value[7:]
        ):
            raise refuse("pair_v2_component_identity")
        digests[key] = value
    return {
        "report_sha256": journal.member_digests["report.json"],
        "component_digests": dict(sorted(digests.items())),
    }


def component_counts(journal: JournalArtifact) -> dict[str, object]:
    """Expose only counts recorded in a sealed report; never derive missing zeroes."""

    raw = journal.report.get("component_counts")
    identity = _component_identity(journal)
    if raw is None:
        return {
            "status": "not_recorded",
            "values": None,
            "source": identity,
            "independently_revalidated": False,
        }
    counts = _mapping(raw, "pair_v2_component_counts")
    if frozenset(counts) != _COUNT_FIELDS:
        raise refuse("pair_v2_component_counts")
    values: dict[str, object] = {}
    for field in sorted(_COUNT_FIELDS):
        value = counts[field]
        if type(value) is not int or value < 0:
            raise refuse("pair_v2_component_counts")
        values[field] = value
    document_count = cast(int, values["document_count"])
    query_count = cast(int, values["query_count"])
    record_count = cast(int, values["record_count"])
    embedding_count = cast(int, values["embedding_count"])
    if (
        document_count + query_count != record_count
        or embedding_count != record_count
    ):
        raise refuse("pair_v2_component_count_algebra")
    response_cost = journal.report.get("component_response_cost")
    if isinstance(response_cost, Mapping) and "input_records" in response_cost:
        if response_cost["input_records"] != values["record_count"]:
            raise refuse("pair_v2_component_count_cost_mismatch")
    return {
        "status": "recorded",
        "values": values,
        "source": identity,
        "independently_revalidated": False,
    }


def generation_work(journal: JournalArtifact) -> dict[str, object]:
    return {
        "cost": _numeric_map(
            journal.report.get("cost"),
            _GENERATION_COST,
            "pair_v2_generation_cost",
            _GENERATION_INTEGER,
        ),
        "component_response_cost": _numeric_map(
            journal.report.get("component_response_cost"),
            _COMPONENT_COST,
            "pair_v2_component_cost",
            _COMPONENT_INTEGER,
        ),
        "component_counts": component_counts(journal),
        "timing_disclosure": "layers_are_independent_and_may_overlap",
        "source": {"member": "report.json", "sha256": journal.member_digests["report.json"]},
    }


def pair_work(pair: Mapping[str, object]) -> dict[str, object]:
    observation = pair.get("journal_observation")
    observation_map = observation if isinstance(observation, Mapping) else {}
    result = _mapping(pair.get("result_v2"), "pair_v2_result_work")
    raw_observation_bytes = observation_map.get("byte_accounting")
    observation_bytes = (
        {
            key: value
            for key, value in raw_observation_bytes.items()
            if key in _OBSERVATION_BYTES
        }
        if isinstance(raw_observation_bytes, Mapping)
        else raw_observation_bytes
    )
    correspondence = result.get("correspondence")
    correspondence_cost = (
        correspondence.get("cost") if isinstance(correspondence, Mapping) else None
    )
    return {
        "journal": {
            "elapsed_ns": _number(
                observation_map.get("elapsed_ns"), "pair_v2_elapsed", integer=True
            ),
            "byte_accounting": _byte_map(
                observation_bytes,
                _OBSERVATION_BYTES,
                _OBSERVATION_INTEGER,
                "pair_v2_byte_accounting",
            ),
            "source": "observations.jsonl" if observation is not None else "not_recorded",
        },
        "result_v2": {
            "byte_work": _byte_map(
                result.get("byte_work"),
                _RESULT_BYTES,
                _RESULT_INTEGER,
                "pair_v2_byte_work",
            ),
            "correspondence_cost": _numeric_map(
                correspondence_cost,
                _CORRESPONDENCE_COST,
                "pair_v2_correspondence_cost",
                _CORRESPONDENCE_INTEGER,
            ),
            "source": "result-v2.json",
        },
    }


def validate_generation_work(value: object) -> None:
    work = _mapping(value, "pair_v2_generation_work")
    if frozenset(work) != {
        "cost",
        "component_response_cost",
        "component_counts",
        "timing_disclosure",
        "source",
    }:
        raise refuse("pair_v2_generation_work_fields")
    source = _mapping(work.get("source"), "pair_v2_generation_work_source")
    if frozenset(source) != {"member", "sha256"}:
        raise refuse("pair_v2_generation_work_source")
    if source.get("member") != "report.json":
        raise refuse("pair_v2_generation_work_source")
    digest = source.get("sha256")
    if type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:"):
        raise refuse("pair_v2_generation_work_source")
    _validate_numeric_map(
        work.get("cost"), _GENERATION_COST, "pair_v2_generation_cost", _GENERATION_INTEGER
    )
    _validate_numeric_map(
        work.get("component_response_cost"),
        _COMPONENT_COST,
        "pair_v2_component_cost",
        _COMPONENT_INTEGER,
    )
    if work.get("timing_disclosure") != "layers_are_independent_and_may_overlap":
        raise refuse("pair_v2_generation_work_timing")
    counts = _mapping(work.get("component_counts"), "pair_v2_component_counts")
    if frozenset(counts) != {"status", "values", "source", "independently_revalidated"}:
        raise refuse("pair_v2_component_counts")
    if counts.get("status") not in {"recorded", "not_recorded"}:
        raise refuse("pair_v2_component_counts")
    if counts.get("independently_revalidated") is not False:
        raise refuse("pair_v2_component_counts")
    count_source = _mapping(counts.get("source"), "pair_v2_component_counts_source")
    if frozenset(count_source) != {"report_sha256", "component_digests"}:
        raise refuse("pair_v2_component_counts_source")
    report_digest = count_source.get("report_sha256")
    if (
        type(report_digest) is not str
        or len(report_digest) != 71
        or not report_digest.startswith("sha256:")
    ):
        raise refuse("pair_v2_component_counts_source")
    component_digests = count_source.get("component_digests")
    if component_digests is not None:
        digest_map = _mapping(component_digests, "pair_v2_component_counts_source")
        if frozenset(digest_map) != _COMPONENT_DIGESTS:
            raise refuse("pair_v2_component_counts_source")
        for digest in digest_map.values():
            if type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:"):
                raise refuse("pair_v2_component_counts_source")
    elif counts.get("status") == "recorded":
        raise refuse("pair_v2_component_counts_source")
    values = counts.get("values")
    if counts.get("status") == "not_recorded":
        if values is not None:
            raise refuse("pair_v2_component_counts")
    else:
        value_map = _mapping(values, "pair_v2_component_counts")
        if frozenset(value_map) != _COUNT_FIELDS or any(
            type(item) is not int or item < 0 for item in value_map.values()
        ):
            raise refuse("pair_v2_component_counts")
        if (
            cast(int, value_map["document_count"]) + cast(int, value_map["query_count"])
            != cast(int, value_map["record_count"])
            or cast(int, value_map["embedding_count"]) != cast(int, value_map["record_count"])
        ):
            raise refuse("pair_v2_component_count_algebra")
        component_cost = work.get("component_response_cost")
        if isinstance(component_cost, Mapping) and "input_records" in component_cost:
            if component_cost["input_records"] != value_map["record_count"]:
                raise refuse("pair_v2_component_count_cost_mismatch")


def validate_pair_work(value: object) -> None:
    work = _mapping(value, "pair_v2_pair_work")
    if frozenset(work) != {"journal", "result_v2"}:
        raise refuse("pair_v2_pair_work_fields")
    for name in ("journal", "result_v2"):
        side = _mapping(work.get(name), "pair_v2_pair_work_side")
        if name == "journal" and frozenset(side) != {"elapsed_ns", "byte_accounting", "source"}:
            raise refuse("pair_v2_pair_work_side")
        if name == "result_v2" and frozenset(side) != {
            "byte_work",
            "correspondence_cost",
            "source",
        }:
            raise refuse("pair_v2_pair_work_side")
        if name == "journal":
            if side.get("source") not in {"observations.jsonl", "not_recorded"}:
                raise refuse("pair_v2_pair_work_source")
            if side.get("source") == "not_recorded" and any(
                side.get(key) is not None for key in ("elapsed_ns", "byte_accounting")
            ):
                raise refuse("pair_v2_pair_work_source")
            _number(side.get("elapsed_ns"), "pair_v2_elapsed", integer=True)
            _validate_byte_map(
                side.get("byte_accounting"),
                _OBSERVATION_BYTES,
                _OBSERVATION_INTEGER,
                "pair_v2_byte_accounting",
            )
        else:
            if side.get("source") not in {"result-v2.json", "not_recorded"}:
                raise refuse("pair_v2_pair_work_source")
            if side.get("source") == "not_recorded" and any(
                side.get(key) is not None for key in ("byte_work", "correspondence_cost")
            ):
                raise refuse("pair_v2_pair_work_source")
            _validate_byte_map(
                side.get("byte_work"),
                _RESULT_BYTES,
                _RESULT_INTEGER,
                "pair_v2_byte_work",
            )
            _validate_numeric_map(
                side.get("correspondence_cost"),
                _CORRESPONDENCE_COST,
                "pair_v2_correspondence_cost",
                _CORRESPONDENCE_INTEGER,
            )


__all__ = [
    "component_counts",
    "generation_work",
    "pair_work",
    "validate_generation_work",
    "validate_pair_work",
]
