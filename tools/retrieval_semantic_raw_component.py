"""Offline original-artifact correspondence, with no runtime or authority claim."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from retrieval_semantic_generator_output_parser import parse_verified_worker_response
from retrieval_semantic_generator_output_receipt import read_worker_archive_inputs
from retrieval_semantic_generator_worker_contracts import WorkerRequestError
from retrieval_semantic_generator_worker_protocol import parse_controller_admission, parse_worker_request
from retrieval_semantic_experiment_artifacts import MEMBER_LIMITS, MEMBER_NAMES
from retrieval_semantic_pair_artifacts import JournalArtifact, digest_bytes, load_journal, refuse
from retrieval_semantic_pair_v2_cost import component_counts
from retrieval_semantic_provenance import RepresentationValidationError
from retrieval_semantic_raw_component_anchors import (
    COUNT_FIELDS, MEMBER_ROLES, canonical_anchors, safe_subcode,
)
from retrieval_semantic_raw_component_io import (
    MODEL_MEMBERS, capture_file, capture_model_members, owned_path, verify_unchanged,
)


@dataclass(frozen=True)
class RawComponentSummary:
    """Only counts and digests leave the worker-parser boundary."""

    generation: int
    attempt_id: str
    counts: tuple[tuple[str, int], ...]
    component_digests: tuple[tuple[str, str], ...]


def verify_raw_component(
    journal: JournalArtifact, members: Mapping[str, bytes],
) -> RawComponentSummary:
    """Join independently recorded canonical anchors to all seven raw digests."""
    if set(members) != set(MODEL_MEMBERS):
        raise refuse("component_members")
    anchors = canonical_anchors(journal)
    try:
        inputs = read_worker_archive_inputs(members["sources.zip"])
        if set(inputs) != {"request.json", "admission.json"}:
            raise refuse("component_archive_inputs")
        request_raw, admission_raw = inputs["request.json"], inputs["admission.json"]
        actual = {role: digest_bytes(members[name]) for name, role in MEMBER_ROLES.items()}
        actual.update(request=digest_bytes(request_raw), admission=digest_bytes(admission_raw))
        if actual != dict(anchors.digests):
            raise refuse("component_digest_mismatch")
        request, _records = parse_worker_request(request_raw)
        parse_controller_admission(
            admission_raw, expected_admission_sha256=anchors.admission,
            request=request, request_sha256=actual["request"],
            source_closure=dict(anchors.closure),
        )
        response = parse_verified_worker_response(
            request_raw=request_raw, report_raw=members["report.json"],
            terminal_raw=members["terminal.json"], declaration_raw=members["declaration.json"],
            source_manifest_raw=members["source-manifest.json"],
            sources_archive_raw=members["sources.zip"],
            expected_controller_admission_sha256=anchors.admission,
            expected_source_closure=dict(anchors.closure),
        )
    except (WorkerRequestError, RepresentationValidationError) as error:
        raise refuse("component_response." + safe_subcode(error)) from None
    except (KeyError, TypeError, OverflowError):
        raise refuse("component_response_structure") from None
    if response.attempt_id != journal.attempt_id:
        raise refuse("component_attempt_mismatch")
    counts = tuple((name, getattr(response, name)) for name in COUNT_FIELDS)
    recorded = component_counts(journal)["values"]
    if recorded is not None and dict(counts) != recorded:
        raise refuse("component_recorded_counts_mismatch")
    return RawComponentSummary(journal.generation, journal.attempt_id, counts, tuple(sorted(actual.items())))


def read_raw_component(journal_path: object, model_directory: object) -> RawComponentSummary:
    """Validate complete supplied artifacts without importing archived code."""
    root = owned_path(journal_path)
    canonical = tuple(capture_file(root/name, limit=MEMBER_LIMITS[name]) for name in MEMBER_NAMES)
    journal = load_journal(root)
    if journal.members != {item.path.name:item.raw for item in canonical}:
        raise refuse("component_source_changed")
    model = capture_model_members(model_directory)
    summary = verify_raw_component(journal, {item.path.name:item.raw for item in model})
    verify_unchanged((*canonical, *model))
    if model != capture_model_members(model_directory):
        raise refuse("component_source_changed")
    return summary


__all__ = ["RawComponentSummary", "read_raw_component", "verify_raw_component"]
