"""Strict ``cloe-public-text-calibration-v1`` builder, writer and reader (study sections 11 and 18.4-18.5).

The report holds hashes, offsets, counts and closed reasons only. Closed nested
schemas live in ``retrieval_public_text_report_contracts`` and every join in
``retrieval_public_text_report_joins``. The reader is structural by default and
says so; raw-evidence verification needs the actual component journal, model
members and selected task objects (``read_verified_report``). A mandatory strict
``functional_only`` marker distinguishes synthetic functional evidence from a
native run; neither value proves model origin. Acceptance flags are always False.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from common_lore_index.storage.semantic_candidates import digest_json
from retrieval_public_text_census import PublicTextCensus
from retrieval_public_text_contracts import PrivateMarkerScope, counter_mapping, require_scope
from retrieval_public_text_descriptors import PublicTextPreparation
from retrieval_public_text_report_cells import (
    ARMS, FILE_GRADING_STATES, LEARNED_ARMS, STATES, TOTAL_CELLS, ReportCellRefusal, file_grading_counts,
    state_counts, validate_cells,
)
from retrieval_public_text_report_contracts import (
    EXECUTION_KINDS, REPORT_SCHEMA, SEAL_SCHEMA, TOP_FIELDS, PublicTextReportRefusal, digest, disclosures, require,
    strict_equal, validate_cleanup, validate_source,
)
from retrieval_public_text_report_joins import (
    NOT_RECORDED_COMPONENT, ReportEvidence, component_evidence, join_cells, join_cleanup, validate_generation,
    verify_evidence,
)
from retrieval_public_text_request import ARM_PTX, ARM_V1, STUDY_PHASE, DualArmInput, encode_dual_arm_request
from retrieval_public_text_response import StudyGenerationSeal
from retrieval_public_text_study_catalog import IndexIdentity
from retrieval_public_text_study_queries import StudyBatch
from retrieval_public_text_tasks import SelectedTaskPins, registered_task_pins
from retrieval_semantic_component_dossier_contract import ACCEPTANCE
from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_pair_artifacts import MAX_REPORT_BYTES, PairReportRefusal, parse_json_object, read_owned_file

_PRIVATE_SHAPES = ("/Users/", "/home/", "/private/", "/var/folders/", "\\u0000")


def census_summary(census: PublicTextCensus) -> dict[str, Any]:
    """Both task-digest schemes are carried under their own names; they are never equated."""
    require(type(census) is PublicTextCensus, "report_census")
    public = census.to_dict()
    return {"census_identity": public["census_identity"], "status": census.status,
            "document_count": census.document_count, "v1_verified_pair_count": census.v1_verified_pair_count,
            "tasks": [{"task_id": t.task_id, "retained_task_sha256": t.retained_task_sha256,
                       "v1_query_task_sha256": t.task_sha256, "v1_learned_state": t.v1_learned_state,
                       "v1_learned_reason": t.v1_learned_reason, "public_text_state": t.public_text_state,
                       "public_text_reason": t.public_text_reason} for t in census.tasks]}


def preparation_summary(preparation: PublicTextPreparation) -> dict[str, Any]:
    require(type(preparation) is PublicTextPreparation, "report_preparation")
    return {"preparation_identity": str(digest_json(preparation.to_dict())), "document_count": len(preparation.documents),
            "v1_verified_pair_count": preparation.v1_verified_pair_count,
            "exclusion_counts": counter_mapping([item.reason for item in preparation.exclusions])}


def request_summary(value: DualArmInput, request_raw: bytes) -> dict[str, Any]:
    """Recomputed from the actual input; the supplied bytes must be its exact encoding."""
    require(type(value) is DualArmInput and type(request_raw) is bytes
            and encode_dual_arm_request(value) == request_raw, "report_request")
    count = {arm: {mode: sum(1 for row in value.layout if row.arm == arm and row.mode.value == mode)
                   for mode in ("document", "query")} for arm in (ARM_V1, ARM_PTX)}
    return {"input_identity": value.input_identity, "records": len(value.records),
            "documents": {arm: count[arm]["document"] for arm in count},
            "queries": {arm: count[arm]["query"] for arm in count},
            "bytes": len(request_raw), "request_sha256": "sha256:" + hashlib.sha256(request_raw).hexdigest()}


def seal_summary(seal: StudyGenerationSeal) -> dict[str, Any]:
    """The verbatim public study seal (no text or vectors)."""
    require(type(seal) is StudyGenerationSeal, "report_seal")
    return seal.to_dict()


def import_summary(batch: StudyBatch) -> dict[str, Any]:
    require(type(batch) is StudyBatch, "report_imports")
    return {"arm": batch.arm, "batch_id": batch.batch_id, "capability": batch.capability,
            "row_count": len(batch.entries), "seal_identity": batch.seal_identity}


def index_summary(index: IndexIdentity, arm: str) -> dict[str, Any]:
    require(type(index) is IndexIdentity and arm in (ARM_V1, ARM_PTX), "report_indexes")
    return {"arm": arm, "batch_id": index.batch_id, "state": "created"}


def fences_summary(*, functional_only: bool, creation: str, inventory: str, publication: str) -> dict[str, Any]:
    require(type(functional_only) is bool, "report_functional_only")
    return {"execution_kind": EXECUTION_KINDS[functional_only], "creation": creation, "inventory": inventory,
            "publication": publication}


def json_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _counts(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Execution states and file-grading states are separate count families, both recomputed."""
    states, grading = state_counts(cells), file_grading_counts(cells)
    return {"cells": {"value": len(cells)}, "states": {name: {"value": states[name]} for name in STATES},
            "file_grading": {name: {"value": grading[name]} for name in FILE_GRADING_STATES},
            "generations": {str(g): {"value": sum(1 for c in cells if c["generation"] == g)} for g in (1, 2)},
            "learned_completed": {"value": sum(1 for c in cells if c["arm"] in LEARNED_ARMS
                                               and c["state"] == "completed")}}


def _observation_status(cells: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]],
                        cleanup: Mapping[str, Any]) -> str:
    observed = (all(c["state"] != "unknown" for c in cells) and all(row["seal"] is not None for row in rows)
                and cleanup.get("status") == "clean")
    return "all_cells_observed" if observed else "incomplete"


def _task_pins(pins: SelectedTaskPins, selected_task_set_identity: object) -> dict[str, Any]:
    require(digest(selected_task_set_identity), "report_task_pins")
    return {"catalog_file_sha256": pins.catalog_file_sha256,
            "historical_semantic_catalog_identity": pins.historical_semantic_catalog_identity,
            "original_manifest_sha256": pins.original_manifest_sha256, "task_pins_identity": pins.identity(),
            "selected_task_set_identity": selected_task_set_identity,
            "task_digest_schemes": {"cell_task_sha256": "canonical-json-ascii-v1",
                                    "census_retained_task_sha256": "canonical-json-ascii-v1",
                                    "census_v1_query_task_sha256": "canonical-json-utf8-v1"},
            "tasks": [{"task_id": t, "generation": g, "task_sha256": d} for t, g, d in pins.tasks]}


def validate_report(report: object) -> None:
    """Closed nested schema, exact recomputed identities/counts/arm correspondence and every join."""
    try:
        _validate_report(report)
    except (KeyError, TypeError, AttributeError, IndexError):
        raise PublicTextReportRefusal("report_structure") from None


def _validate_report(report: object) -> None:
    require(isinstance(report, Mapping) and set(report) == TOP_FIELDS, "report_fields")
    assert isinstance(report, Mapping)
    pins, functional_only = registered_task_pins(), report["functional_only"]
    require((report["schema"], report["phase"], report["declaration"]) == (REPORT_SCHEMA, STUDY_PHASE, 2)
            and type(report["declaration"]) is int and digest(report["study_identity"]), "report_identity")
    require(type(functional_only) is bool, "report_functional_only")
    task_pins = report["task_pins"]
    require(isinstance(task_pins, Mapping) and task_pins == _task_pins(pins, task_pins.get("selected_task_set_identity")),
            "report_task_pins")
    source = validate_source(report["source"])
    require(report["arms"] == list(ARMS), "report_arms")
    generations = report["generations"]
    require(type(generations) is list and len(generations) == 2, "report_generations")
    rows = [validate_generation(row, index, pins, functional_only, source["artifact_profile_identity"])
            for index, row in enumerate(generations, 1)]
    try:
        validate_cells(report["cells"], tasks=pins.tasks)
    except ReportCellRefusal as error:
        raise PublicTextReportRefusal("report_" + error.code) from None
    join_cells(report["cells"], rows)
    cleanup = validate_cleanup(report["cleanup"])
    join_cleanup(cleanup, rows)
    require(report["acceptance"] == ACCEPTANCE and all(v is False for v in report["acceptance"].values()),
            "report_acceptance")
    require(report["disclosures"] == disclosures(functional_only), "report_disclosures")
    require(strict_equal(report["counts"], _counts(report["cells"]))
            and report["counts"]["cells"]["value"] == TOTAL_CELLS, "report_counts")
    require(report["observation_status"] == _observation_status(report["cells"], rows, cleanup),
            "report_observation_status")


def _assert_private_free(raw: bytes, scope: PrivateMarkerScope | None) -> None:
    """Host-path shapes always refuse; private markers refuse whenever a scope is supplied."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise PublicTextReportRefusal("report_private_value") from None
    require(not any(shape in text for shape in _PRIVATE_SHAPES), "report_private_value")
    if scope is not None:
        markers = require_scope(scope).markers
        decoded = json.dumps(json.loads(raw), ensure_ascii=False)
        require(not any(marker in decoded for marker in markers), "report_private_value")


def build_report(*, study_identity: str, selected_task_set_identity: str, source: Mapping[str, Any],
                 functional_only: bool, generations: Sequence[Mapping[str, Any]], cells: list[dict[str, Any]],
                 cleanup: Mapping[str, Any], scope: PrivateMarkerScope | None = None) -> dict[str, Any]:
    """Assemble, recompute counts/status, then validate exactly as the reader does."""
    require(type(functional_only) is bool, "report_functional_only")
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA, "phase": STUDY_PHASE, "declaration": 2, "study_identity": study_identity,
        "functional_only": functional_only,
        "task_pins": _task_pins(registered_task_pins(), selected_task_set_identity), "source": dict(source),
        "arms": list(ARMS), "generations": [dict(row) for row in generations], "cells": cells,
        "cleanup": dict(cleanup), "acceptance": dict(ACCEPTANCE), "disclosures": disclosures(functional_only),
        "counts": _counts(cells) if type(cells) is list else {}, "observation_status": "incomplete",
    }
    if type(cells) is list and len(report["generations"]) == 2 and isinstance(cleanup, Mapping):
        try:
            report["observation_status"] = _observation_status(cells, report["generations"], cleanup)
        except (KeyError, TypeError, AttributeError):
            raise PublicTextReportRefusal("report_structure") from None
    validate_report(report)
    _assert_private_free(canonical_json_bytes(report), scope)
    return report


def write_report(path: Path, report: Mapping[str, Any], *, scope: PrivateMarkerScope | None = None) -> str:
    """Canonical bytes plus LF, at most 32 MiB, exclusive create; returns the report identity."""
    validate_report(report)
    raw = canonical_json_bytes(report) + b"\n"
    require(len(raw) <= MAX_REPORT_BYTES, "report_size")
    _assert_private_free(raw[:-1], scope)
    require(isinstance(path, Path) and path.is_absolute(), "report_path")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ReportRead:
    """A read report and how far it was verified; structural reads never claim raw verification."""

    report: dict[str, Any]
    identity: str
    verification: str  # structural_only | raw_evidence_verified


def read_report(path: Path, *, evidence: ReportEvidence | None = None) -> ReportRead:
    """Bounded no-symlink read, canonical-byte equality, privacy and full recomputation; evidence optional."""
    try:
        raw = read_owned_file(path, limit=MAX_REPORT_BYTES, code_prefix="report_file")
        value = parse_json_object(raw, code_prefix="report_json")
    except PairReportRefusal as error:
        raise PublicTextReportRefusal("report_read:" + error.code[:80]) from None
    require(canonical_json_bytes(value) + b"\n" == raw, "report_noncanonical")
    validate_report(value)
    _assert_private_free(raw[:-1], None if evidence is None else evidence.scope)
    identity = "sha256:" + hashlib.sha256(raw).hexdigest()
    if evidence is None:
        return ReportRead(value, identity, "structural_only")
    try:
        verify_evidence(value, evidence)
    except PublicTextReportRefusal:
        raise
    except (KeyError, TypeError, AttributeError, IndexError, ValueError):
        raise PublicTextReportRefusal("report_evidence") from None
    return ReportRead(value, identity, "raw_evidence_verified")


def read_verified_report(path: Path, evidence: ReportEvidence) -> ReportRead:
    """The positive study closeout entry: raw evidence is mandatory, never a stored flag."""
    require(type(evidence) is ReportEvidence, "report_evidence")
    return read_report(path, evidence=evidence)


__all__ = [
    "NOT_RECORDED_COMPONENT", "PublicTextReportRefusal", "REPORT_SCHEMA", "ReportEvidence", "ReportRead",
    "SEAL_SCHEMA", "build_report", "census_summary", "component_evidence", "fences_summary", "import_summary",
    "index_summary", "json_digest", "preparation_summary", "read_report", "read_verified_report",
    "request_summary", "seal_summary", "validate_report", "write_report",
]
