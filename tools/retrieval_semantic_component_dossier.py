"""Build a separate W5 artifact correspondence dossier; existing V1/V2 stay inert."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path

from retrieval_semantic_component_dossier_contract import (
    ACCEPTANCE, DISCLOSURES, DOSSIER_SCHEMA, validate_component_dossier,
)
from retrieval_semantic_component_dossier_io import read_component_dossier, write_component_dossier
from retrieval_semantic_experiment_artifacts import MEMBER_LIMITS
from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_pair_artifacts import (
    MEMBER_NAMES, MAX_REPORT_BYTES, MAX_RESULT_BYTES, PairReportRefusal,
    JournalArtifact, load_journal, refuse,
)
from retrieval_semantic_pair_v2_report import build_pair_report_v2
from retrieval_semantic_raw_component import verify_raw_component
from retrieval_semantic_raw_component_anchors import object_map
from retrieval_semantic_raw_component_io import (
    FileSnapshot, capture_file, capture_model_members, owned_path, verify_unchanged,
)


def generation_sources(value: object, *, complete: bool = True) -> dict[int, object]:
    """Normalize explicit slots; bool keys and duplicate sequence labels refuse."""
    if isinstance(value, Mapping):
        pairs = list(value.items())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        pairs = []
        for pair in value:
            if not isinstance(pair, Sequence) or isinstance(pair, (str, bytes)) or len(pair) != 2:
                raise refuse("dossier_source_slots")
            pairs.append((pair[0], pair[1]))
    else:
        raise refuse("dossier_source_slots")
    result: dict[int, object] = {}
    for generation, path in pairs:
        if type(generation) is not int or generation not in (1, 2) or generation in result:
            raise refuse("dossier_source_slots")
        result[generation] = path
    if complete and set(result) != {1, 2}:
        raise refuse("dossier_source_slots")
    return result


def _journal_inputs(path: object) -> tuple[JournalArtifact, tuple[FileSnapshot, ...]]:
    root = owned_path(path)
    snapshots = tuple(capture_file(root / name, limit=MEMBER_LIMITS[name]) for name in MEMBER_NAMES)
    journal = load_journal(root)
    if dict(journal.members) != {item.path.name:item.raw for item in snapshots}:
        raise refuse("dossier_source_changed")
    return journal, snapshots


def _generation_row(
    generation: int, journal: JournalArtifact, result: FileSnapshot,
    count_row: Mapping[str, object], model: tuple[FileSnapshot, ...] | None,
) -> dict[str, object]:
    source = object_map(count_row.get("source"), "dossier_component_source")
    recorded_digests = source.get("component_digests")
    component: dict[str, object] = {
        "recorded":count_row.get("status"), "recorded_counts":count_row.get("values"),
        "recorded_component_digests":recorded_digests, "supplied":"not_supplied",
        "correspondence":"unknown", "artifact_correspondence_verified":None,
        "verified_counts":None, "verified_component_digests":None,
    }
    if source.get("report_sha256") != journal.member_digests["report.json"]:
        raise refuse("dossier_component_source")
    if model is not None:
        summary = verify_raw_component(journal, {item.path.name:item.raw for item in model})
        verified = dict(summary.component_digests)
        if verified != recorded_digests:
            raise refuse("dossier_component_digest_join")
        component.update(supplied="supplied", correspondence="verified", artifact_correspondence_verified=True,
                         verified_counts=dict(summary.counts), verified_component_digests=verified)
    return {
        "generation":generation, "attempt_id":journal.attempt_id,
        "journal_members":{name:{"sha256":journal.member_digests[name],"length":journal.member_lengths[name]} for name in MEMBER_NAMES},
        "result_v2":result.binding, "component":component,
    }


def _join_provenance(
    report: Mapping[str, object], journals: Mapping[int, JournalArtifact], results: Mapping[int, FileSnapshot],
) -> None:
    provenance = object_map(report.get("source_provenance"), "dossier_provenance")
    for kind in ("journals", "results_v2"):
        values = provenance.get(kind)
        if type(values) is not list or len(values) != 2:
            raise refuse("dossier_provenance")
        for generation, value in enumerate(values, 1):
            item = object_map(value, "dossier_provenance")
            journal = journals[generation]
            if type(item.get("generation")) is not int or item.get("generation") != generation or item.get("attempt_id") != journal.attempt_id:
                raise refuse("dossier_provenance")
            if kind == "journals":
                if item.get("member_digests") != journal.member_digests or item.get("member_lengths") != journal.member_lengths:
                    raise refuse("dossier_provenance_join")
            elif any(item.get(key) != value for key,value in results[generation].binding.items()):
                raise refuse("dossier_provenance_join")


def build_component_dossier(
    journal_paths: object, result_paths: object, paired_report_path: object,
    model_bundle_paths: object = None,
) -> dict[str, object]:
    """Rebuild unchanged V2, then join original anchors and recheck input drift."""
    journal_sources = generation_sources(journal_paths)
    result_sources = generation_sources(result_paths)
    model_sources = {} if model_bundle_paths is None else generation_sources(model_bundle_paths, complete=False)
    journals: dict[int, JournalArtifact] = {}
    snapshots: list[FileSnapshot] = []
    for generation in (1, 2):
        journal, files = _journal_inputs(journal_sources[generation])
        if journal.generation != generation:
            raise refuse("dossier_journal_generation")
        journals[generation] = journal
        snapshots.extend(files)
    results = {generation:capture_file(result_sources[generation], limit=MAX_RESULT_BYTES) for generation in (1, 2)}
    snapshots.extend(results.values())
    paired = capture_file(paired_report_path, limit=MAX_REPORT_BYTES)
    snapshots.append(paired)
    models = {generation:capture_model_members(path) for generation,path in model_sources.items()}
    snapshots.extend(item for files in models.values() for item in files)
    report = build_pair_report_v2(journal_sources, result_sources)
    if canonical_json_bytes(report) + b"\n" != paired.raw:
        raise refuse("dossier_paired_source_mismatch")
    _join_provenance(report, journals, results)
    count_rows = report.get("component_counts")
    if type(count_rows) is not list or len(count_rows) != 2:
        raise refuse("dossier_component_source")
    rows = []
    for generation, value in enumerate(count_rows, 1):
        count_row = object_map(value, "dossier_component_source")
        if type(count_row.get("generation")) is not int or count_row.get("generation") != generation:
            raise refuse("dossier_component_source")
        rows.append(_generation_row(generation, journals[generation], results[generation], count_row, models.get(generation)))
    dossier: dict[str, object] = {"schema":DOSSIER_SCHEMA, "paired_report":paired.binding,
               "generations":rows, "acceptance":dict(ACCEPTANCE), "disclosures":dict(DISCLOSURES)}
    validate_component_dossier(dossier)
    verify_unchanged(snapshots)
    for generation, path in model_sources.items():
        if models[generation] != capture_model_members(path):
            raise refuse("dossier_source_changed")
    return dossier


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    build = commands.add_parser("build")
    for generation in (1, 2):
        build.add_argument(f"--journal-{generation}", required=True, type=Path)
        build.add_argument(f"--result-{generation}", required=True, type=Path)
        build.add_argument(f"--model-{generation}", type=Path)
    build.add_argument("--paired-report", required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    check = commands.add_parser("check", help="structural only; no source reauthentication")
    check.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == "check":
            read_component_dossier(args.input)
        else:
            journals = {generation:getattr(args, f"journal_{generation}") for generation in (1, 2)}
            results = {generation:getattr(args, f"result_{generation}") for generation in (1, 2)}
            models = {generation:getattr(args, f"model_{generation}") for generation in (1, 2) if getattr(args, f"model_{generation}") is not None}
            dossier = build_component_dossier(journals, results, args.paired_report, models)
            write_component_dossier(args.output, dossier)
    except PairReportRefusal as error:
        parser.exit(3, f"dossier refused: {error.code}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_component_dossier", "generation_sources", "main", "read_component_dossier", "write_component_dossier"]
