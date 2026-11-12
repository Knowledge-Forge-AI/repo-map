"""Genuine public-text component journals and the private failure receipt (study sections 11 and 19.5).

Journals use only the unchanged filesystem primitives: ``admit_attempt`` with
the actual request/admission bytes and the evaluator closure, ``append`` for
private operation events, ``finish`` exactly once and ``load_journal``. A
component is recorded only from the actual raw model members, which the
unchanged ``verify_raw_component`` must reconcile; otherwise the journal says
``not_recorded``. The failure receipt is closed, bounded and private, never a
partial calibration report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, cast

from retrieval_evaluation_attempts import AttemptJournal, admit_attempt
from retrieval_public_text_report_cells import ARMS, REPETITIONS, TOTAL_CELLS
from retrieval_public_text_request import STUDY_PHASE
from retrieval_public_text_sources import SourceClosure
from retrieval_semantic_experiment_contracts import TIMEOUT_POLICY, canonical_json_bytes
from retrieval_semantic_generator_output_receipt import VerifiedWorkerResponse
from retrieval_semantic_pair_artifacts import JOURNAL_SCHEMA, JournalArtifact, digest_bytes, load_journal
from retrieval_semantic_raw_component import verify_raw_component
from retrieval_semantic_raw_component_anchors import COUNT_FIELDS, MEMBER_ROLES

FAILURE_SCHEMA = "cloe-public-text-study-failure-v1"
FAILURE_NAME = "public-text-study-failure.json"
MAX_FAILURE_BYTES = 64 * 1024
STUDY_STATES = (
    "DECLARED", "CLUSTER_READY", "G1_PUBLISHED", "G1_PREPARED", "G1_FROZEN", "G1_WORKER", "G1_SEALED",
    "TABLES_CREATED", "G1_IMPORTED", "G1_OBSERVED", "G2_PUBLISHED", "G1_STALE_PROVEN", "G2_PREPARED", "G2_FROZEN",
    "G2_WORKER", "G2_SEALED", "G2_IMPORTED", "G2_OBSERVED", "CLEANED", "REPORTED",
)
FAILURE_CODES = frozenset({
    "study_declaration_refused", "cluster_setup_failed", "publication_failed", "preparation_refused",
    "request_refused", "exchange_refused", "worker_response_refused", "seal_refused", "sql_failed",
    "observation_failed", "operation_failed", "stale_proof_failed", "source_changed", "report_failed",
    "cleanup_failed", "journal_failed", "study_execution_failed", "study_interrupted", "transition_failed",
    "evidence_export_failed",
})
CLEANUP_STATUSES = frozenset({"clean", "failed", "not_run"})
EVENTS = frozenset({
    "component_admission_accepted", "study_cell", "learned_operation", "stale_g1_observation",
    "transition_interval", "generation_frame", "study_failure",
})
_CODE = re.compile(r"[a-z0-9_.:-]{1,96}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class StudyJournalRefusal(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _private_root(root: Path) -> None:
    if not isinstance(root, Path) or not root.is_absolute() or any(
            path.is_symlink() for path in (root, *root.parents)):
        raise StudyJournalRefusal("failure_receipt_root")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise StudyJournalRefusal("failure_receipt_root")
    root.chmod(0o700)


def begin_component_journal(root: Path, *, attempt_id: str, generation: int, task_ids: Sequence[str],
                            request_raw: bytes, admission_raw: bytes, evaluator: SourceClosure,
                            worker: SourceClosure, input_files: Mapping[str, bytes]) -> AttemptJournal:
    """Admit the genuine evaluator journal with the real admission bytes, then record the admission event."""
    if worker.name != "worker" or evaluator.name != "evaluator":
        raise StudyJournalRefusal("journal_closure_names")
    if (type(generation) is not int or generation not in (1, 2)
            or f"w5-semantic-g{generation}" != attempt_id or set(input_files) & {"request.json", "admission.json"}):
        raise StudyJournalRefusal("journal_attempt_identity")
    request = json.loads(request_raw)
    declaration = {
        "schema": JOURNAL_SCHEMA, "phase": STUDY_PHASE, "attempt_id": attempt_id, "generation": generation,
        "arms": list(ARMS), "task_ids": list(task_ids), "repetitions": len(REPETITIONS),
        "input_identity": request["input_identity"],
        "representation_report_identity": request["representation_report_identity"],
        "publication_identity": request["publication_identity"],
        "artifact_profile_identity": request["artifact_profile_identity"],
        "request_sha256": digest_bytes(request_raw), "controller_admission_sha256": digest_bytes(admission_raw),
        "source_closure": dict(worker.digests), "component_source_closure": dict(worker.digests),
        "worker_source_closure_identity": worker.identity, "q_source_closure_identity": evaluator.identity,
        "candidate_closure_digests": dict(evaluator.digests), "timeout_policy": dict(TIMEOUT_POLICY),
    }
    inputs = {"request.json": request_raw, "admission.json": admission_raw, **dict(input_files)}
    _private_root(root)
    journal = admit_attempt(root, declaration, dict(evaluator.files), input_files=inputs)
    journal.append({"event": "component_admission_accepted", "generation": generation,
                    "request_sha256": declaration["request_sha256"],
                    "controller_admission_sha256": declaration["controller_admission_sha256"]})
    return journal


def record_operation(journal: AttemptJournal, event: str, **fields: Any) -> None:
    """Private journal event; raw rows, plans and grades stay here, never in the public report."""
    if event not in EVENTS:
        raise StudyJournalRefusal("journal_event")
    journal.append({"event": event, **fields})


def component_digests(request_raw: bytes, admission_raw: bytes, members: Mapping[str, bytes]) -> dict[str, str]:
    """The seven component role digests computed from the actual raw bytes."""
    if set(members) != set(MEMBER_ROLES):
        raise StudyJournalRefusal("journal_component_members")
    digests = {role: digest_bytes(members[name]) for name, role in MEMBER_ROLES.items()}
    digests.update(request=digest_bytes(request_raw), admission=digest_bytes(admission_raw))
    return digests


def finish_component_journal(journal: AttemptJournal, *, request_raw: bytes, admission_raw: bytes,
                             response: VerifiedWorkerResponse | None, raw_members: Mapping[str, bytes] | None,
                             status: str, failure_code: str | None = None) -> JournalArtifact:
    """Component/observations through cleanup, excluding later study report/export.

    Finish once; recorded components reconcile through unchanged verification.
    A completed journal is not whole-study acceptance.
    """
    if status not in ("completed", "failed") or (status == "failed") != (failure_code is not None):
        raise StudyJournalRefusal("journal_status")
    if failure_code is not None and failure_code not in FAILURE_CODES:
        raise StudyJournalRefusal("journal_failure_code")
    if (response is None) != (raw_members is None) or (status == "completed" and response is None):
        raise StudyJournalRefusal("journal_component_state")
    report: dict[str, Any] = {"status": status, "failure_code": failure_code, "timeout_policy": dict(TIMEOUT_POLICY)}
    if response is not None and raw_members is not None:
        report["component"] = component_digests(request_raw, admission_raw, raw_members)
        report["component_counts"] = {name: getattr(response, name) for name in COUNT_FIELDS}
    else:
        report["component_status"] = "not_recorded"
    journal.finish(status, report)
    artifact = load_journal(journal.directory)
    if raw_members is not None:
        verify_raw_component(artifact, raw_members)
    return artifact


@dataclass(frozen=True)
class StudyFailureReceipt:
    """Truthful facts at the stop point only; unknown identities stay ``None``."""

    functional_only: bool
    study_identity: str | None
    q_source_closure_identity: str | None
    task_pins_identity: str
    stop_state: str
    failure_code: str
    observed_cells: int
    components: tuple[tuple[int, str | None], ...]
    cleanup_status: str
    cleanup_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema": FAILURE_SCHEMA, "phase": STUDY_PHASE, "functional_only": self.functional_only,
            "study_identity": self.study_identity, "q_source_closure_identity": self.q_source_closure_identity,
            "task_pins_identity": self.task_pins_identity, "stop_state": self.stop_state,
            "failure_code": self.failure_code, "planned_cells": TOTAL_CELLS, "observed_cells": self.observed_cells,
            "unknown_cells": TOTAL_CELLS - self.observed_cells if type(self.observed_cells) is int else None,
            "components": [{"generation": g, "state": "not_recorded" if d is None else "recorded",
                            "report_sha256": d} for g, d in self.components],
            "cleanup": {"status": self.cleanup_status, "reason": self.cleanup_reason},
        }
        validate_failure_receipt(value)
        return value


def _optional_digest(value: object) -> bool:
    return value is None or (type(value) is str and _DIGEST.fullmatch(value) is not None)


def validate_failure_receipt(value: object) -> None:
    """Closed fields, strict types, exact cell arithmetic and no free text."""
    mapping = cast(Mapping[str, Any], value)
    fields = {"schema", "phase", "functional_only", "study_identity", "q_source_closure_identity",
              "task_pins_identity", "stop_state", "failure_code", "planned_cells", "observed_cells", "unknown_cells",
              "components", "cleanup"}
    ok = isinstance(value, Mapping) and set(mapping) == fields
    ok = ok and (mapping["schema"], mapping["phase"]) == (FAILURE_SCHEMA, STUDY_PHASE)
    ok = ok and type(mapping["functional_only"]) is bool and mapping["stop_state"] in STUDY_STATES
    ok = ok and mapping["failure_code"] in FAILURE_CODES and _optional_digest(mapping["study_identity"])
    ok = ok and _optional_digest(mapping["q_source_closure_identity"]) and _optional_digest(mapping["task_pins_identity"])
    ok = ok and mapping["task_pins_identity"] is not None and mapping["planned_cells"] == TOTAL_CELLS
    ok = ok and all(type(mapping[n]) is int for n in ("planned_cells", "observed_cells", "unknown_cells"))
    ok = ok and 0 <= mapping["observed_cells"] <= TOTAL_CELLS
    ok = ok and mapping["observed_cells"] + mapping["unknown_cells"] == TOTAL_CELLS
    components = mapping["components"] if ok else None
    ok = ok and type(components) is list and [c.get("generation") for c in components if isinstance(c, Mapping)] \
        == list(range(1, len(components) + 1)) and len(components) <= 2
    for item in components or ():
        ok = ok and set(item) == {"generation", "state", "report_sha256"} and _optional_digest(item["report_sha256"])
        ok = ok and type(item["generation"]) is int
        ok = ok and item["state"] == ("not_recorded" if item["report_sha256"] is None else "recorded")
    cleanup = mapping["cleanup"] if ok else None
    cleanup_mapping = cast(Mapping[str, Any], cleanup)
    ok = ok and isinstance(cleanup, Mapping) and set(cleanup_mapping) == {"status", "reason"}
    ok = ok and cleanup_mapping["status"] in CLEANUP_STATUSES
    ok = ok and (cleanup_mapping["reason"] is None) == (cleanup_mapping["status"] == "clean")
    ok = ok and (cleanup_mapping["reason"] is None or (
        type(cleanup_mapping["reason"]) is str and _CODE.fullmatch(cleanup_mapping["reason"]) is not None))
    if not ok:
        raise StudyJournalRefusal("failure_receipt_invalid")


def write_failure_receipt(root: Path, receipt: StudyFailureReceipt) -> str:
    """Exclusive, fsynced, bounded canonical bytes under the private export root; returns its sha256."""
    raw = canonical_json_bytes(receipt.to_dict()) + b"\n"
    if len(raw) > MAX_FAILURE_BYTES or not isinstance(root, Path) or not root.is_absolute():
        raise StudyJournalRefusal("failure_receipt_bounds")
    _private_root(root)
    descriptor = os.open(root / FAILURE_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                         0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("failure_receipt_write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def cleanup_fields(cleanup: Mapping[str, Any] | None, error: str | None) -> tuple[str, str | None]:
    """Failure-receipt cleanup facts; an unreadable proof never becomes clean."""
    if cleanup is not None:
        return cleanup["status"], cleanup["reason"]
    return ("failed", error) if error is not None else ("not_run", "cleanup_not_reached")


__all__ = [
    "EVENTS", "FAILURE_CODES", "FAILURE_NAME", "FAILURE_SCHEMA", "STUDY_STATES", "StudyFailureReceipt",
    "StudyJournalRefusal", "begin_component_journal", "cleanup_fields", "component_digests", "finish_component_journal",
    "record_operation", "validate_failure_receipt", "write_failure_receipt",
]
