"""Versioned, read-only paired evidence report for retained W5 artifacts.

This is an evaluator/tool boundary.  It never reads a live graph, authenticates
a store, rescales a stored metric, or changes the product CLI.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
from typing import cast

from retrieval_semantic_baseline_result_frames import (
    MAX_RESULT_BYTES,
)
from retrieval_semantic_baseline_result_objects import BaselineResultV2
from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_pair_artifacts import (
    MAX_REPORT_BYTES,
    JournalArtifact,
    PairReportRefusal,
    load_journal,
    parse_json_object,
    read_owned_file,
    refuse,
)
from retrieval_semantic_pair_comparisons import build_pair_comparisons, validate_pair_comparisons
from retrieval_semantic_pair_metrics import build_generation_pairs
from retrieval_semantic_pair_report_support import (
    cal07_values,
    encoded_result_frame_size,
    generation_2_limitation,
    source_provenance,
    validate_result_input_lengths,
    validate_result_frame_budget,
)


PAIR_REPORT_SCHEMA = "cloe-w5-semantic-paired-report-v1"
_TOP_FIELDS = {
    "schema", "acceptance", "pairing", "source_provenance", "generations", "pairs",
    "comparisons", "denominators", "disclosures", "measurement_boundaries", "pair_count",
}
_ACCEPTANCE_FIELDS = {"accepted", "scientific", "fullW5", "heldout", "production"}
_PAIR_FIELDS = {
    "identity", "classification", "alignment", "journal_observation", "journal_grade",
    "result_v2", "file_grading_policy_version", "file_grading_policy_version_source",
    "rational_fusion",
}


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value


def _source_mapping(value: object, code: str) -> dict[int, object]:
    if isinstance(value, Mapping):
        raw = dict(value)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        raw = {}
        for item in value:
            if not isinstance(item, Sequence) or len(item) != 2:
                raise refuse(code)
            generation = item[0]
            if type(generation) is not int or generation in raw:
                raise refuse(code)
            raw[generation] = item[1]
    else:
        raise refuse(code)
    if any(type(generation) is not int for generation in raw):
        raise refuse(code)
    if set(raw) != {1, 2}:
        raise refuse(code)
    return {int(generation): raw[generation] for generation in (1, 2)}


def _decode_result(raw: bytes) -> tuple[dict[str, object], BaselineResultV2]:
    payload = raw[:-1] if raw.endswith(b"\n") else raw
    mapping = parse_json_object(payload, code_prefix="pair_result_v2")
    try:
        if canonical_json_bytes(mapping) != payload:
            raise refuse("pair_result_v2_noncanonical")
        result = BaselineResultV2.from_mapping(mapping)
    except PairReportRefusal:
        raise
    except ImportError as error:
        raise refuse("pair_result_decoder_unavailable") from error
    except Exception as error:
        raise refuse("pair_result_v2_invalid") from error
    return mapping, result


def _aggregate_denominators(summaries: Sequence[Mapping[str, object]]) -> dict[str, object]:
    totals = {name: 0 for name in ("whole", "supported", "graded", "eligible")}
    reasons: Counter[str] = Counter()
    definitions: Mapping[str, object] = {}
    for summary in summaries:
        denominator = summary.get("denominators")
        if not isinstance(denominator, Mapping):
            raise refuse("pair_report_generation_denominator")
        for name in totals:
            value = denominator.get(name)
            if type(value) is not int or value < 0:
                raise refuse("pair_report_denominator")
            totals[name] += value
        raw_reasons = denominator.get("reason_categories")
        if not isinstance(raw_reasons, Mapping):
            raise refuse("pair_report_reason_categories")
        for reason, count in raw_reasons.items():
            if type(reason) is not str or type(count) is not int or count < 0:
                raise refuse("pair_report_reason_categories")
            reasons[reason] += count
        if not definitions:
            raw_definitions = denominator.get("definitions")
            if not isinstance(raw_definitions, Mapping):
                raise refuse("pair_report_denominator_definitions")
            definitions = raw_definitions
    return {
        **totals,
        "reason_categories": dict(sorted(reasons.items())),
        "definitions": {
            **dict(definitions),
            "aggregation": "cross_generation_count_only_not_pooled",
        },
    }


def _validate_report(report: Mapping[str, object]) -> None:
    if frozenset(report) != _TOP_FIELDS or report.get("schema") != PAIR_REPORT_SCHEMA:
        raise refuse("pair_report_fields")
    acceptance = _mapping(report.get("acceptance"), "pair_report_acceptance")
    if frozenset(acceptance) != _ACCEPTANCE_FIELDS or any(value is not False for value in acceptance.values()):
        raise refuse("pair_report_acceptance")
    pairs = report.get("pairs")
    if type(pairs) is not list or report.get("pair_count") != len(pairs):
        raise refuse("pair_report_pairs")
    seen: set[tuple[object, object, object, object]] = set()
    for pair in pairs:
        mapping = _mapping(pair, "pair_report_pair")
        if frozenset(mapping) != _PAIR_FIELDS:
            raise refuse("pair_report_pair_fields")
        identity = _mapping(mapping.get("identity"), "pair_report_identity")
        key = (
            identity.get("generation"), identity.get("task_id"),
            identity.get("arm_id"), identity.get("repetition"),
        )
        if (
            type(key[0]) is not int or key[0] not in {1, 2}
            or type(key[1]) is not str or not key[1]
            or type(key[2]) is not str or not key[2]
            or type(key[3]) is not int or key[3] < 1
        ):
            raise refuse("pair_report_identity")
        if key in seen:
            raise refuse("pair_report_duplicate_identity")
        seen.add(key)
    validate_pair_comparisons(report.get("comparisons"))
    generations = report.get("generations")
    if type(generations) is not list or len(generations) != 2:
        raise refuse("pair_report_generations")
    generation_ids: set[int] = set()
    for generation in generations:
        summary = _mapping(generation, "pair_report_generation")
        generation_id = summary.get("generation")
        if type(generation_id) is not int or generation_id not in {1, 2} or generation_id in generation_ids:
            raise refuse("pair_report_generation_count")
        generation_ids.add(generation_id)
        pair_count = summary.get("pair_count")
        if type(pair_count) is not int or pair_count < 0:
            raise refuse("pair_report_generation_count")
    provenance = report.get("source_provenance")
    if type(provenance) is not dict or frozenset(provenance) != {"journals", "results_v2"}:
        raise refuse("pair_report_provenance")
    for name in ("journals", "results_v2"):
        entries = provenance[name]
        if type(entries) is not list or len(entries) != 2:
            raise refuse("pair_report_provenance")
        entry_generations: set[int] = set()
        for entry in entries:
            item = _mapping(entry, "pair_report_provenance")
            generation_id = item.get("generation")
            if type(generation_id) is not int or generation_id not in {1, 2} or generation_id in entry_generations:
                raise refuse("pair_report_provenance")
            entry_generations.add(generation_id)
            if type(item.get("attempt_id")) is not str or not item["attempt_id"]:
                raise refuse("pair_report_provenance")
            if name == "results_v2":
                digest = item.get("sha256")
                if type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:"):
                    raise refuse("pair_report_provenance_digest")


def build_pair_report(
    journal_paths: Mapping[int, object] | Sequence[Sequence[object]],
    result_paths: Mapping[int, object] | Sequence[Sequence[object]],
) -> dict[str, object]:
    """Build a report from exactly the two retained journal/result generations."""

    journal_sources = _source_mapping(journal_paths, "pair_journal_sources")
    result_sources = _source_mapping(result_paths, "pair_result_sources")
    provenance_journals: list[dict[str, object]] = []
    provenance_results: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []
    journals: dict[int, JournalArtifact] = {}
    result_raws: dict[int, bytes] = {}
    for generation in (1, 2):
        journal = load_journal(journal_sources[generation])
        if journal.generation != generation:
            raise refuse("pair_generation_mismatch")
        journals[generation] = journal
        result_raws[generation] = read_owned_file(
            result_sources[generation], limit=MAX_RESULT_BYTES, code_prefix="pair_result_v2",
        )
    validate_result_input_lengths(tuple(len(result_raws[generation]) for generation in (1, 2)))
    frame_lengths: list[int] = []
    for generation in (1, 2):
        journal = journals[generation]
        result_raw = result_raws[generation]
        result, result_object = _decode_result(result_raw)
        frame_lengths.append(encoded_result_frame_size(result_object))
        if result.get("attempt_id") != journal.attempt_id or result.get("generation") != generation:
            raise refuse("pair_result_attempt_mismatch")
        provenance = source_provenance(journal, result, result_raw, generation)
        provenance_journals.append({
            "generation": generation,
            "attempt_id": journal.attempt_id,
            "member_digests": journal.member_digests,
        })
        result_provenance = _mapping(provenance.get("result_v2"), "pair_result_provenance")
        result_digest = result_provenance.get("sha256")
        if type(result_digest) is not str:
            raise refuse("pair_result_provenance_digest")
        provenance_results.append({
            **result_provenance,
            "generation": generation,
            "attempt_id": journal.attempt_id,
        })
        generation_pairs, summary = build_generation_pairs(journal, result, result_digest)
        pairs.extend(generation_pairs)
        summary["source_provenance"] = provenance
        summaries.append(summary)
    validate_result_frame_budget(frame_lengths)
    plan_input_identities = {
        cast(int, summary["generation"]): _mapping(summary["plan"], "pair_report_plan").get("input_identity")
        for summary in summaries
    }
    comparisons = build_pair_comparisons(pairs, plan_input_identities)
    report: dict[str, object] = {
        "schema": PAIR_REPORT_SCHEMA,
        "acceptance": {
            "accepted": False,
            "scientific": False,
            "fullW5": False,
            "heldout": False,
            "production": False,
        },
        "pairing": {
            "identity_key": ["generation", "task_id", "arm_id", "repetition"],
            "join_mode": "recorded_identity",
            "array_position_join": False,
        },
        "source_provenance": {"journals": provenance_journals, "results_v2": provenance_results},
        "generations": summaries,
        "denominators": _aggregate_denominators(summaries),
        "pairs": pairs,
        "comparisons": comparisons,
        "pair_count": len(pairs),
        "disclosures": {
            "comparative_aggregate": "not_emitted",
            "fixed_arm_comparisons": "stored_values_and_gaps_only; no aggregate, rescore, or decision",
            "rescore": "not_performed",
            "native_cal07_raw_process_stdout_bytes": {
                "stored_values": cal07_values(pairs),
                "retained_reference": 495781,
            },
            "unaccepted_65536_byte_criterion": {
                "value": 65536,
                "status": "unaccepted",
            },
            "generation_2_limitation": generation_2_limitation(pairs, summaries),
            "reader_live_store_authentication": "not_performed",
        },
        "measurement_boundaries": {
            "ann_correctness": "stored exact_reference_recall only; distinct from relevance",
            "relevance": "stored_task_grade_values_only",
            "timing": "components_retained_independently; overlap_not_added",
            "io": "unknown_values_remain_null",
            "safety_and_absence": "not_quality_metrics",
        },
    }
    _validate_report(report)
    return report


def _output_path(raw_path: object) -> Path:
    if not isinstance(raw_path, (str, os.PathLike)):
        raise refuse("pair_output_path")
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if any(part in {".", ".."} for part in path.parts) or any(parent.is_symlink() for parent in path.parents):
        raise refuse("pair_output_unsafe")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise refuse("pair_output_unsafe")
    return path


def _validate_report_output_size(size: object) -> None:
    if type(size) is not int or size < 0 or size > MAX_REPORT_BYTES:
        raise refuse("pair_output_size")


def write_report(report: Mapping[str, object], output_path: object) -> None:
    """Write one new owned output; never overwrite an existing artifact."""

    _validate_report(report)
    path = _output_path(output_path)
    try:
        raw = json.dumps(
            report, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
        ).encode("ascii") + b"\n"
        _validate_report_output_size(len(raw))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError as error:
        raise refuse("pair_output_exists") from error
    except PairReportRefusal:
        raise
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        raise refuse("pair_output_write") from error


def read_report(input_path: object) -> dict[str, object]:
    """Read a generated report without authenticating any live publication."""

    raw = read_owned_file(input_path, limit=MAX_REPORT_BYTES, code_prefix="pair_report")
    report = parse_json_object(raw[:-1] if raw.endswith(b"\n") else raw, code_prefix="pair_report")
    _validate_report(report)
    return report


def _binding(raw: str, code: str) -> tuple[int, Path]:
    generation_text, separator, path_text = raw.partition("=")
    if not separator or generation_text not in {"1", "2"} or not path_text:
        raise refuse(code)
    path = Path(path_text)
    if not path.is_absolute():
        path = Path.cwd() / path
    return int(generation_text), path


def _bindings(values: Sequence[str], code: str) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for value in values:
        generation, path = _binding(value, code)
        if generation in result:
            raise refuse(code + "_duplicate")
        result[generation] = path
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a hash-bound W5 paired artifact report")
    parser.add_argument("--journal", action="append", required=True, metavar="GENERATION=PATH")
    parser.add_argument("--result", action="append", required=True, metavar="GENERATION=PATH")
    parser.add_argument("--output", required=True, metavar="PATH")
    args = parser.parse_args(argv)
    try:
        journals = _bindings(args.journal, "pair_journal_argument")
        results = _bindings(args.result, "pair_result_argument")
        report = build_pair_report(journals, results)
        write_report(report, args.output)
    except PairReportRefusal as error:
        parser.exit(2, f"pair report refused: {error.code}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = ["PAIR_REPORT_SCHEMA", "build_pair_report", "main", "read_report", "write_report"]
