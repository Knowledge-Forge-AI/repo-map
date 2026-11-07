"""Opt-in, hash-bound W5 paired context and cost report (V2)."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import os
from pathlib import Path
from typing import cast

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
from retrieval_semantic_pair_report import build_pair_report
from retrieval_semantic_pair_report_support import generation_2_limitation
from retrieval_semantic_pair_v2_context import (
    Identity,
    build_context,
    index_query_observed,
)
from retrieval_semantic_pair_v2_cost import (
    generation_work,
    pair_work,
)
from retrieval_semantic_pair_v2_rows import (
    project_comparison,
    project_generation,
    project_pair,
)
from retrieval_semantic_pair_v2_validation import validate_report


PAIR_REPORT_V2_SCHEMA = "cloe-w5-semantic-paired-report-v2"
MAX_PAIR_REPORT_V2_BYTES = MAX_REPORT_BYTES


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value


def _source_map(value: object, code: str) -> dict[int, object]:
    if isinstance(value, Mapping):
        raw = dict(value)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        raw = {}
        for item in value:
            if not isinstance(item, Sequence) or len(item) != 2 or type(item[0]) is not int:
                raise refuse(code)
            if item[0] in raw:
                raise refuse(code)
            raw[item[0]] = item[1]
    else:
        raise refuse(code)
    if set(raw) != {1, 2}:
        raise refuse(code)
    return {generation: raw[generation] for generation in (1, 2)}


def _identity(pair: Mapping[str, object]) -> Identity:
    value = _mapping(pair.get("identity"), "pair_v2_identity")
    generation, task, arm, repetition = (
        value.get("generation"), value.get("task_id"), value.get("arm_id"), value.get("repetition")
    )
    if (
        type(generation) is not int
        or generation not in {1, 2}
        or type(task) is not str
        or not task
        or type(arm) is not str
        or not arm
        or type(repetition) is not int
        or repetition < 1
    ):
        raise refuse("pair_v2_identity")
    return generation, task, arm, repetition


def _source_provenance(
    journals: Mapping[int, JournalArtifact], base: Mapping[str, object]
) -> dict[str, object]:
    raw = _mapping(base.get("source_provenance"), "pair_v2_provenance")
    output: dict[str, object] = {"journals": [], "results_v2": []}
    for name in ("journals", "results_v2"):
        entries = raw.get(name)
        if type(entries) is not list:
            raise refuse("pair_v2_provenance")
        safe_entries: list[dict[str, object]] = []
        for entry in entries:
            item = _mapping(entry, "pair_v2_provenance")
            generation = item.get("generation")
            attempt = item.get("attempt_id")
            if type(generation) is not int or generation not in {1, 2} or type(attempt) is not str:
                raise refuse("pair_v2_provenance")
            safe: dict[str, object] = {"generation": generation, "attempt_id": attempt}
            if name == "journals":
                journal = journals[generation]
                safe["member_digests"] = journal.member_digests
                safe["member_lengths"] = journal.member_lengths
            else:
                digest = item.get("sha256")
                if type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:"):
                    raise refuse("pair_v2_provenance")
                safe["length"] = item.get("length")
                safe["sha256"] = digest
            safe_entries.append(safe)
        output[name] = sorted(safe_entries, key=lambda item: cast(int, item["generation"]))
    return output


def _reconcile_journal_reads(
    base_generations: object, journals: Mapping[int, JournalArtifact]
) -> None:
    if type(base_generations) is not list:
        raise refuse("pair_v2_source_changed")
    seen: set[int] = set()
    for raw in base_generations:
        summary = _mapping(raw, "pair_v2_source_changed")
        generation = summary.get("generation")
        if type(generation) is not int or generation not in {1, 2} or generation in seen:
            raise refuse("pair_v2_source_changed")
        journal = journals[generation]
        source = _mapping(summary.get("source_provenance"), "pair_v2_source_changed")
        if source.get("attempt_id") != journal.attempt_id:
            raise refuse("pair_v2_source_changed")
        members = _mapping(source.get("journal_members"), "pair_v2_source_changed")
        if set(members) != set(journal.member_digests):
            raise refuse("pair_v2_source_changed")
        for name, digest in journal.member_digests.items():
            member = _mapping(members.get(name), "pair_v2_source_changed")
            if frozenset(member) != {"length", "sha256"}:
                raise refuse("pair_v2_source_changed")
            if member.get("length") != journal.member_lengths[name] or member.get("sha256") != digest:
                raise refuse("pair_v2_source_changed")
        seen.add(generation)
    if seen != {1, 2}:
        raise refuse("pair_v2_source_changed")


def _generation_2_limitation(
    base_pairs: Sequence[Mapping[str, object]],
    base_generations: Sequence[Mapping[str, object]],
    work: Mapping[int, Mapping[str, object]],
) -> dict[str, object]:
    limitation = generation_2_limitation(base_pairs, base_generations)
    counts = _mapping(work[2].get("component_counts"), "pair_v2_component_counts")
    if counts.get("status") == "recorded":
        values = _mapping(counts.get("values"), "pair_v2_component_counts")
        query_count = values.get("query_count")
        if type(query_count) is not int or query_count < 0:
            raise refuse("pair_v2_component_counts")
        document_count = values.get("document_count")
        record_count = values.get("record_count")
        if (
            type(document_count) is not int
            or document_count < 0
            or type(record_count) is not int
            or record_count < 0
        ):
            raise refuse("pair_v2_component_counts")
        limitation["document_only"] = {
            "value": query_count == 0 and document_count == record_count,
            "evidence_status": "recorded_sealed_response",
        }
        limitation["component_querycount"] = {
            "value": query_count,
            "evidence_status": "recorded_sealed_response",
        }
    elif counts.get("status") == "not_recorded":
        limitation["document_only"] = {"value": None, "evidence_status": "unknown"}
        limitation["component_querycount"] = {"value": None, "evidence_status": "unknown"}
    return limitation


def _cal07_disclosure(base: Mapping[str, object]) -> dict[str, object]:
    disclosures = _mapping(base.get("disclosures"), "pair_v2_disclosures")
    legacy = _mapping(
        disclosures.get("native_cal07_raw_process_stdout_bytes"), "pair_v2_disclosures"
    )
    values = legacy.get("stored_values")
    reference = legacy.get("retained_reference")
    if type(values) is not list or any(type(value) is not int or value < 0 for value in values):
        raise refuse("pair_v2_disclosures")
    if type(reference) is not int or reference < 0:
        raise refuse("pair_v2_disclosures")
    return {
        "current_observed_values": list(values),
        "historical_reference": reference,
        "status": "historical_reference_only",
    }


def _safe_comparisons(
    comparisons: object, contexts: Mapping[Identity, Mapping[str, object]]
) -> list[dict[str, object]]:
    if type(comparisons) is not list:
        raise refuse("pair_v2_comparisons")
    gaps: dict[Identity, list[str]] = {}
    for key, value in contexts.items():
        raw_gaps = value.get("comparability_gaps")
        if isinstance(raw_gaps, list):
            gaps[key] = [item for item in raw_gaps if type(item) is str]
    result: list[dict[str, object]] = []
    for value in comparisons:
        result.append(project_comparison(_mapping(value, "pair_v2_comparison"), gaps, contexts))
    return result


def _validate_report(report: Mapping[str, object]) -> None:
    validate_report(report, PAIR_REPORT_V2_SCHEMA)


def build_pair_report_v2(
    journal_paths: Mapping[int, object] | Sequence[Sequence[object]],
    result_paths: Mapping[int, object] | Sequence[Sequence[object]],
) -> dict[str, object]:
    """Build V2 from source-verified V1 joins plus independent V2 projections."""

    base = build_pair_report(journal_paths, result_paths)
    base_generations = base.get("generations")
    sources = _source_map(journal_paths, "pair_v2_journal_sources")
    journals = {generation: load_journal(sources[generation]) for generation in (1, 2)}
    _reconcile_journal_reads(base_generations, journals)
    indexes = {generation: index_query_observed(journal) for generation, journal in journals.items()}
    contexts: dict[Identity, Mapping[str, object]] = {}
    pairs: list[dict[str, object]] = []
    base_pairs = base.get("pairs")
    if type(base_pairs) is not list:
        raise refuse("pair_v2_base_pairs")
    for raw in base_pairs:
        pair = _mapping(raw, "pair_v2_base_pair")
        identity = _identity(pair)
        event_line = indexes[identity[0]].get(identity)
        event = event_line[0] if event_line is not None else None
        line = event_line[1] if event_line is not None else None
        context = build_context(pair, event, line)
        work = pair_work(pair)
        contexts[identity] = context
        pairs.append(project_pair(pair, context, work))
    if type(base_generations) is not list:
        raise refuse("pair_v2_base_generations")
    generation_work_rows = {
        generation: generation_work(journals[generation]) for generation in (1, 2)
    }
    generations = [
        project_generation(
            _mapping(next(item for item in base_generations if item.get("generation") == generation), "pair_v2_base_generation"),
            generation_work_rows[generation],
        )
        for generation in (1, 2)
    ]
    comparisons = _safe_comparisons(base.get("comparisons"), contexts)
    base_acceptance = _mapping(base.get("acceptance"), "pair_v2_acceptance")
    report: dict[str, object] = {
        "schema": PAIR_REPORT_V2_SCHEMA,
        "base_report_schema": base.get("schema"),
        "acceptance": dict(base_acceptance),
        "pairing": base.get("pairing"),
        "source_provenance": _source_provenance(journals, base),
        "generations": generations,
        "pairs": pairs,
        "comparisons": comparisons,
        "denominators": base.get("denominators"),
        "component_counts": [
            {"generation": generation, **cast(dict[str, object], generation_work_rows[generation]["component_counts"])}
            for generation in (1, 2)
        ],
        "pair_count": len(pairs),
        "disclosures": {
            "comparative_aggregate": "not_emitted",
            "declared_vs_observed": "differences_disclosed; conflicting_observed_claims_refused",
            "reader_live_store_authentication": "not_performed",
            "source_verified_builder": "journal_and_result_v2_hashes_validated_before_projection",
            "structural_reader": "does_not_reauthenticate_source_files_or_live_stores",
            "raw_model_bundle": "deferred; missing_component_counts_are_not_recorded",
            "generation_2_limitation": _generation_2_limitation(
                cast(Sequence[Mapping[str, object]], base_pairs),
                cast(Sequence[Mapping[str, object]], base_generations),
                generation_work_rows,
            ),
            "native_cal07_raw_process_stdout_bytes": _cal07_disclosure(base),
            "unaccepted_65536_byte_criterion": {"value": 65536, "status": "unaccepted"},
            "timing": "named_layers_are_independent_and_may_overlap; no_additive_total",
        },
        "measurement_boundaries": {
            "ann_correctness": "stored exact_reference_recall only; distinct from relevance",
            "relevance": "stored_task_grade_values_only",
            "safety_and_absence": "not_quality_metrics",
            "database_io": "unknown_values_remain_null",
            "scientific_comparability": "not_emitted",
        },
    }
    _validate_report(report)
    return report


def _output_path(value: object) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise refuse("pair_v2_output_path")
    path = Path(value)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise refuse("pair_v2_output_path")
    if any(parent.is_symlink() for parent in path.parents):
        raise refuse("pair_v2_output_path")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise refuse("pair_v2_output_path")
    return path


def write_pair_report_v2(report: Mapping[str, object], output_path: object) -> None:
    _validate_report(report)
    path = _output_path(output_path)
    raw = canonical_json_bytes(dict(report)) + b"\n"
    if len(raw) > MAX_PAIR_REPORT_V2_BYTES:
        raise refuse("pair_v2_output_size")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError as error:
        raise refuse("pair_v2_output_exists") from error
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        raise refuse("pair_v2_output_write") from error


def read_pair_report_v2(input_path: object) -> dict[str, object]:
    """Perform structural validation only; source files and live stores are not reread."""

    raw = read_owned_file(input_path, limit=MAX_PAIR_REPORT_V2_BYTES, code_prefix="pair_v2_report")
    payload = raw[:-1] if raw.endswith(b"\n") else raw
    report = parse_json_object(payload, code_prefix="pair_v2_report")
    if canonical_json_bytes(report) != payload:
        raise refuse("pair_v2_noncanonical")
    _validate_report(report)
    return report


def _binding(raw: str, code: str) -> tuple[int, Path]:
    generation, separator, path_text = raw.partition("=")
    if not separator or generation not in {"1", "2"} or not path_text:
        raise refuse(code)
    path = Path(path_text)
    if not path.is_absolute():
        path = Path.cwd() / path
    return int(generation), path


def _bindings(values: Sequence[str], code: str) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for value in values:
        generation, path = _binding(value, code)
        if generation in result:
            raise refuse(code + "_duplicate")
        result[generation] = path
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an opt-in W5 paired context report V2")
    parser.add_argument("--journal", action="append", required=True, metavar="GENERATION=PATH")
    parser.add_argument("--result", action="append", required=True, metavar="GENERATION=PATH")
    parser.add_argument("--output", required=True, metavar="PATH")
    args = parser.parse_args(argv)
    try:
        journals = _bindings(args.journal, "pair_v2_journal_argument")
        results = _bindings(args.result, "pair_v2_result_argument")
        write_pair_report_v2(build_pair_report_v2(journals, results), args.output)
    except PairReportRefusal as error:
        parser.exit(2, f"pair report V2 refused: {error.code}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MAX_PAIR_REPORT_V2_BYTES",
    "PAIR_REPORT_V2_SCHEMA",
    "build_pair_report_v2",
    "main",
    "read_pair_report_v2",
    "write_pair_report_v2",
]
