"""One-study/two-worker public-text allocation bookkeeping (study section 19.1).

Closed receipt schemas, cross-links and the only legal order: reserve the
study, reserve and finish g1, reserve and finish g2 (only after a completed
clean g1 and with separate stale-g1 evidence), then finish the study. There is
no release, repair or retry. ``native_status`` is always ``not_asserted``: a
receipt never proves native execution, and functional bookkeeping is labelled.
"""

from __future__ import annotations

from typing import cast

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re

from retrieval_public_text_allocation_io import (
    AllocationRefused, locked_root, read_receipt, require_digest, require_token, write_receipt,
)

SCHEMA_VERSION = "cloe-publictext-allocation-v2"
STUDY_KIND = "PUBLICTEXT-CAL1"
NATIVE_STATUS = "not_asserted"
STUDY_RESERVATION = "study-reservation.json"
G1_RESERVATION = "worker-g1-reservation.json"
G1_TERMINAL = "worker-g1-terminal.json"
G2_RESERVATION = "worker-g2-reservation.json"
G2_TERMINAL = "worker-g2-terminal.json"
STUDY_TERMINAL = "study-terminal.json"
RECEIPTS = (STUDY_RESERVATION, G1_RESERVATION, G1_TERMINAL, G2_RESERVATION, G2_TERMINAL, STUDY_TERMINAL)
_ALLOWED = frozenset(RECEIPTS)
_KINDS = {
    STUDY_RESERVATION: "study_reservation", G1_RESERVATION: "worker_reservation",
    G1_TERMINAL: "worker_terminal", G2_RESERVATION: "worker_reservation",
    G2_TERMINAL: "worker_terminal", STUDY_TERMINAL: "study_terminal",
}
_SLOTS = {1: (G1_RESERVATION, G1_TERMINAL), 2: (G2_RESERVATION, G2_TERMINAL)}
_ATTEMPTS = {1: "w5-semantic-g1", 2: "w5-semantic-g2"}
_NONCE = re.compile(r"[0-9a-f]{64}\Z")
FAILURE_CODES = frozenset({
    "study_initialization_failed", "g1_failed", "g2_preflight_refused", "g2_failed", "study_cleanup_failed",
    "study_evidence_failed",
})
_BASE = (
    "schema", "kind", "study_kind", "phase_id", "allocation_identity", "source_identity", "task_identity",
    "profile_identity", "approval_identity", "functional_transition_proof_sha256", "functional_only",
    "native_status",
)
_SPEC_DIGESTS = ("source_identity", "task_identity", "profile_identity", "approval_identity",
                 "functional_transition_proof_sha256")
_IDENTITY = (
    "generation", "attempt_label", "study_identity", "request_sha256", "publication_identity", "input_identity",
    "nonce", "frame_sha256", "preparation_identity", "census_identity", "estimate_identity",
)
_WORKER_DIGESTS = ("study_identity", "request_sha256", "publication_identity", "input_identity", "frame_sha256",
                   "preparation_identity", "census_identity", "estimate_identity")
_COMMON = frozenset(_BASE) | {"receipt_sha256"}
_FIELDS = {
    "study_reservation": _COMMON,
    "worker_reservation": _COMMON | frozenset(_IDENTITY) | {"study_reservation_sha256", "stale_g1_proof_sha256"},
    "worker_terminal": _COMMON | frozenset(_IDENTITY) | {"study_reservation_sha256", "reservation_sha256",
                                                         "status", "clean"},
    "study_terminal": _COMMON | {"study_identity", "study_reservation_sha256", "worker_g1_terminal_sha256",
                                 "worker_g2_terminal_sha256", "g1_state", "g2_state", "status", "failure_code",
                                 "clean", "cleanup_evidence_sha256"},
}


@dataclass(frozen=True, slots=True)
class StudySpec:
    """Pre-run invariants only; actual worker identities arrive later."""

    phase_id: str
    allocation_identity: str
    source_identity: str
    task_identity: str
    profile_identity: str
    approval_identity: str
    functional_transition_proof_sha256: str
    functional_only: bool = True

    def validate(self) -> StudySpec:
        require_token(self.phase_id, "phase_id")
        require_token(self.allocation_identity, "allocation_identity")
        for name in _SPEC_DIGESTS:
            require_digest(getattr(self, name), name)
        if type(self.functional_only) is not bool:
            raise AllocationRefused("functional_only must be bool")
        return self


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    """Actual generation, request, publication, input, frame and nonce identity."""

    generation: int
    study_identity: str
    request_sha256: str
    publication_identity: str
    input_identity: str
    nonce: str
    frame_sha256: str
    preparation_identity: str
    census_identity: str
    estimate_identity: str

    def validate(self) -> WorkerSpec:
        if type(self.generation) is not int or self.generation not in _ATTEMPTS:
            raise AllocationRefused("worker generation must be 1 or 2")
        for name in _WORKER_DIGESTS:
            require_digest(getattr(self, name), name)
        if type(self.nonce) is not str or _NONCE.fullmatch(self.nonce) is None:
            raise AllocationRefused("worker nonce is invalid")
        return self


def _base(spec: StudySpec, kind: str) -> dict[str, object]:
    spec.validate()
    values = (SCHEMA_VERSION, kind, STUDY_KIND, spec.phase_id, spec.allocation_identity, spec.source_identity,
              spec.task_identity, spec.profile_identity, spec.approval_identity,
              spec.functional_transition_proof_sha256, spec.functional_only, NATIVE_STATUS)
    return dict(zip(_BASE, values, strict=True))


def _worker(spec: StudySpec, worker: WorkerSpec, kind: str) -> dict[str, object]:
    worker.validate()
    value = _base(spec, kind)
    value.update(dict(zip(_IDENTITY, (
        worker.generation, _ATTEMPTS[worker.generation], worker.study_identity, worker.request_sha256,
        worker.publication_identity, worker.input_identity, worker.nonce, worker.frame_sha256,
        worker.preparation_identity, worker.census_identity, worker.estimate_identity), strict=True)))
    return value


def _validate_worker_fields(record: Mapping[str, object]) -> None:
    generation = record["generation"]
    if type(generation) is not int or generation not in _ATTEMPTS or record["attempt_label"] != _ATTEMPTS[generation]:
        raise AllocationRefused("worker generation identity is invalid")
    for name in (*_WORKER_DIGESTS, "study_reservation_sha256"):
        require_digest(record[name], name)
    if type(record["nonce"]) is not str or _NONCE.fullmatch(record["nonce"]) is None:
        raise AllocationRefused("worker nonce is invalid")


def _validate_study_terminal(record: Mapping[str, object]) -> None:
    for name in ("study_reservation_sha256", "cleanup_evidence_sha256"):
        require_digest(record[name], name)
    for name in ("study_identity", "worker_g1_terminal_sha256", "worker_g2_terminal_sha256"):
        if record[name] is not None:
            require_digest(record[name], name)
    if record["g1_state"] not in ("terminal", "unstarted") or record["g2_state"] not in ("terminal", "unstarted"):
        raise AllocationRefused("study worker state is invalid")
    for generation in (1, 2):
        terminal = record[f"g{generation}_state"] == "terminal"
        if terminal != (record[f"worker_g{generation}_terminal_sha256"] is not None):
            raise AllocationRefused("study worker link state is invalid")
    if (record["g1_state"] == "unstarted") != (record["study_identity"] is None):
        raise AllocationRefused("study identity state is invalid")
    if record["status"] not in ("completed", "failed") or type(record["clean"]) is not bool:
        raise AllocationRefused("study terminal status is invalid")
    if (record["status"] == "completed") != (record["failure_code"] is None):
        raise AllocationRefused("study terminal failure code is inconsistent")
    if record["status"] == "failed" and record["failure_code"] not in FAILURE_CODES:
        raise AllocationRefused("study failure code is invalid")


def _validate(record: dict[str, object], kind: str) -> dict[str, object]:
    if set(record) != _FIELDS[kind] or record.get("kind") != kind:
        raise AllocationRefused("receipt schema is closed or has the wrong kind")
    if (record["schema"], record["study_kind"], record["native_status"]) != (SCHEMA_VERSION, STUDY_KIND, NATIVE_STATUS):
        raise AllocationRefused("receipt schema, study kind, or native status is invalid")
    require_token(record["phase_id"], "phase_id")
    require_token(record["allocation_identity"], "allocation_identity")
    for name in (*_SPEC_DIGESTS, "receipt_sha256"):
        require_digest(record[name], name)
    if type(record["functional_only"]) is not bool:
        raise AllocationRefused("receipt functional_only is invalid")
    if kind in ("worker_reservation", "worker_terminal"):
        _validate_worker_fields(record)
    if kind == "worker_reservation":
        proof = record["stale_g1_proof_sha256"]
        if record["generation"] == 1 and proof is not None:
            raise AllocationRefused("g1 reservation carries stale proof")
        if record["generation"] == 2:
            require_digest(proof, "stale_g1_proof_sha256")
    if kind == "worker_terminal":
        require_digest(record["reservation_sha256"], "reservation_sha256")
        if record["status"] not in ("completed", "failed") or type(record["clean"]) is not bool:
            raise AllocationRefused("worker terminal status is invalid")
    if kind == "study_terminal":
        _validate_study_terminal(record)
    return record


def _read(root: Path, name: str, spec: StudySpec | None) -> dict[str, object] | None:
    record = read_receipt(root, name)
    if record is None:
        return None
    _validate(record, _KINDS[name])
    if spec is not None and any(record.get(key) != value for key, value in _base(spec, _KINDS[name]).items()):
        raise AllocationRefused("study invariant mismatch")
    return record


def _write(root: Path, name: str, payload: Mapping[str, object]) -> dict[str, object]:
    staged = dict(payload)
    staged["receipt_sha256"] = "sha256:" + "0" * 64
    _validate(staged, _KINDS[name])
    return write_receipt(root, name, payload)


def failure_for(g1: Mapping[str, object] | None, g2: Mapping[str, object] | None, *,
                cleanup_clean: bool = False) -> str:
    """The only truthful failure code for the observed worker terminals."""
    if type(cleanup_clean) is not bool:
        raise AllocationRefused("cleanup verdict must be bool")
    if g1 is None:
        return "study_initialization_failed"
    if g1["status"] != "completed":
        return "g1_failed"
    if g2 is None:
        return "g2_preflight_refused" if g1["clean"] is True else "study_cleanup_failed"
    if g2["status"] != "completed":
        return "g2_failed"
    return "study_evidence_failed" if cleanup_clean and g1["clean"] is True and g2["clean"] is True else "study_cleanup_failed"


def _check_links(state: Mapping[str, dict[str, object] | None]) -> None:
    study = state[STUDY_RESERVATION]
    if study is None:
        raise AllocationRefused("study reservation is required")
    for generation, (reservation_name, terminal_name) in _SLOTS.items():
        reservation, terminal = state[reservation_name], state[terminal_name]
        for item in (reservation, terminal):
            if item is not None and item["generation"] != generation:
                raise AllocationRefused("worker receipt is in the wrong generation slot")
            if item is not None and item["study_reservation_sha256"] != study["receipt_sha256"]:
                raise AllocationRefused("worker study reservation link is invalid")
        if terminal is not None and (reservation is None or terminal["reservation_sha256"] != reservation["receipt_sha256"]):
            raise AllocationRefused("worker terminal is not paired with its reservation")
        if terminal is not None and any(terminal[field] != cast(dict[str, object], reservation)[field] for field in _IDENTITY):
            raise AllocationRefused("worker terminal identity does not match reservation")
    g1r, g1t, g2r = state[G1_RESERVATION], state[G1_TERMINAL], state[G2_RESERVATION]
    if g2r is not None and (g1t is None or g1t["status"] != "completed" or g1t["clean"] is not True):
        raise AllocationRefused("g2 reservation is out of order")
    if g2r is not None and g2r["stale_g1_proof_sha256"] in {item["receipt_sha256"] for item in (g1r, g1t) if item}:
        raise AllocationRefused("g2 stale proof is not separate controller evidence")
    if g1r is not None and g2r is not None:
        if g1r["study_identity"] != g2r["study_identity"]:
            raise AllocationRefused("worker study identities do not agree")
        if any(g1r[field] == g2r[field] for field in ("request_sha256", "publication_identity", "nonce")):
            raise AllocationRefused("g1 and g2 actual identities must be distinct")


def _check_terminal(state: Mapping[str, dict[str, object] | None]) -> None:
    terminal, study = state[STUDY_TERMINAL], state[STUDY_RESERVATION]
    if terminal is None or study is None:
        return
    if terminal["study_reservation_sha256"] != study["receipt_sha256"]:
        raise AllocationRefused("study terminal study link is invalid")
    for generation, (reservation_name, terminal_name) in _SLOTS.items():
        worker_terminal = state[terminal_name]
        if terminal[f"g{generation}_state"] == "terminal":
            if worker_terminal is None or terminal[f"worker_g{generation}_terminal_sha256"] != worker_terminal["receipt_sha256"]:
                raise AllocationRefused(f"study terminal g{generation} link is invalid")
        elif state[reservation_name] is not None or worker_terminal is not None:
            raise AllocationRefused(f"unstarted g{generation} has a worker receipt")
    g1r, g1t, g2t = state[G1_RESERVATION], state[G1_TERMINAL], state[G2_TERMINAL]
    if g1r is not None and terminal["study_identity"] != g1r["study_identity"]:
        raise AllocationRefused("study terminal identity is invalid")
    complete = (g1t is not None and g2t is not None and terminal["clean"] is True
                and all(item["status"] == "completed" and item["clean"] is True for item in (g1t, g2t)))
    if terminal["status"] == "completed" and not complete:
        raise AllocationRefused("study terminal completion is inconsistent")
    if terminal["status"] == "failed" and terminal["failure_code"] != failure_for(g1t, g2t, cleanup_clean=cast(bool, terminal["clean"])):
        raise AllocationRefused("study terminal failure is inconsistent")


def _state(root: Path, spec: StudySpec) -> dict[str, dict[str, object] | None]:
    state = {name: _read(root, name, spec) for name in RECEIPTS}
    _check_links(state)
    _check_terminal(state)
    return state


def reserve_study(root: Path | str, study: StudySpec) -> Mapping[str, object]:
    study.validate()
    with locked_root(root, create=True, allowed=_ALLOWED) as path:
        if any(read_receipt(path, name) is not None for name in RECEIPTS):
            raise AllocationRefused("study allocation is already spent")
        return _write(path, STUDY_RESERVATION, _base(study, "study_reservation"))


def reserve_worker(root: Path | str, study: StudySpec, worker: WorkerSpec, *,
                   stale_g1_proof_sha256: str | None = None) -> Mapping[str, object]:
    study.validate()
    worker.validate()
    with locked_root(root, create=False, allowed=_ALLOWED) as path:
        state = _state(path, study)
        if state[STUDY_TERMINAL] is not None:
            raise AllocationRefused("study is terminal")
        reservation_name, terminal_name = _SLOTS[worker.generation]
        if state[reservation_name] is not None or state[terminal_name] is not None:
            raise AllocationRefused("worker allocation is already spent")
        proof: str | None = None
        if worker.generation == 1:
            if stale_g1_proof_sha256 is not None or state[G2_RESERVATION] is not None:
                raise AllocationRefused("g1 cannot carry stale proof or follow g2")
        else:
            g1, g1t = state[G1_RESERVATION], state[G1_TERMINAL]
            if g1 is None or g1t is None or g1t["status"] != "completed" or g1t["clean"] is not True:
                raise AllocationRefused("g2 requires a completed clean g1")
            proof = require_digest(stale_g1_proof_sha256, "stale_g1_proof_sha256")
            if proof in (g1["receipt_sha256"], g1t["receipt_sha256"]):
                raise AllocationRefused("stale-g1 proof must be separate controller evidence")
            if worker.study_identity != g1["study_identity"]:
                raise AllocationRefused("g2 must use the actual g1 study identity")
            if any(getattr(worker, field) == g1[field] for field in ("request_sha256", "publication_identity", "nonce")):
                raise AllocationRefused("g2 request/publication/nonce must differ from g1")
        study_receipt = state[STUDY_RESERVATION]
        assert study_receipt is not None
        payload = _worker(study, worker, "worker_reservation")
        payload.update({"study_reservation_sha256": study_receipt["receipt_sha256"], "stale_g1_proof_sha256": proof})
        return _write(path, reservation_name, payload)


def finish_worker(root: Path | str, study: StudySpec, worker: WorkerSpec, *, status: str,
                  clean: bool) -> Mapping[str, object]:
    study.validate()
    worker.validate()
    if status not in ("completed", "failed") or type(clean) is not bool:
        raise AllocationRefused("worker terminal arguments are invalid")
    with locked_root(root, create=False, allowed=_ALLOWED) as path:
        state = _state(path, study)
        if state[STUDY_TERMINAL] is not None:
            raise AllocationRefused("study is terminal")
        reservation_name, terminal_name = _SLOTS[worker.generation]
        reservation = state[reservation_name]
        if reservation is None or state[terminal_name] is not None:
            raise AllocationRefused("worker reservation is missing or terminal")
        expected = _worker(study, worker, "worker_reservation")
        if any(reservation[name] != expected[name] for name in _IDENTITY):
            raise AllocationRefused("worker identity mismatch")
        payload = _worker(study, worker, "worker_terminal")
        payload.update({"study_reservation_sha256": reservation["study_reservation_sha256"],
                        "reservation_sha256": reservation["receipt_sha256"], "status": status, "clean": clean})
        return _write(path, terminal_name, payload)


def finish_study(root: Path | str, study: StudySpec, *, status: str, failure_code: str | None,
                 cleanup_clean: bool, cleanup_evidence_sha256: str) -> Mapping[str, object]:
    study.validate()
    if status not in ("completed", "failed") or type(cleanup_clean) is not bool:
        raise AllocationRefused("study terminal arguments are invalid")
    if (status == "completed") != (failure_code is None):
        raise AllocationRefused("study failure code does not match status")
    require_digest(cleanup_evidence_sha256, "cleanup_evidence_sha256")
    with locked_root(root, create=False, allowed=_ALLOWED) as path:
        state = _state(path, study)
        if state[STUDY_TERMINAL] is not None:
            raise AllocationRefused("study is already terminal")
        g1r, g1, g2r, g2 = (state[name] for name in (G1_RESERVATION, G1_TERMINAL, G2_RESERVATION, G2_TERMINAL))
        if (g1r is not None and g1 is None) or (g2r is not None and g2 is None):
            raise AllocationRefused("every reserved worker must have a terminal")
        if status == "completed":
            if g1 is None or g2 is None or not cleanup_clean or not all(
                    item["status"] == "completed" and item["clean"] is True for item in (g1, g2)):
                raise AllocationRefused("study completion requires two clean completed workers and cleanup")
        elif failure_code != failure_for(g1, g2, cleanup_clean=cleanup_clean):
            raise AllocationRefused("study failure code does not describe observed state")
        study_receipt = state[STUDY_RESERVATION]
        assert study_receipt is not None
        payload = _base(study, "study_terminal")
        payload.update({
            "study_identity": None if g1r is None else g1r["study_identity"],
            "study_reservation_sha256": study_receipt["receipt_sha256"],
            "worker_g1_terminal_sha256": None if g1 is None else g1["receipt_sha256"],
            "worker_g2_terminal_sha256": None if g2 is None else g2["receipt_sha256"],
            "g1_state": "unstarted" if g1 is None else "terminal",
            "g2_state": "unstarted" if g2 is None else "terminal",
            "status": status, "failure_code": failure_code, "clean": cleanup_clean,
            "cleanup_evidence_sha256": cleanup_evidence_sha256,
        })
        return _write(path, STUDY_TERMINAL, payload)


def read_state(root: Path | str, study: StudySpec) -> Mapping[str, Mapping[str, object] | None]:
    study.validate()
    with locked_root(root, create=False, allowed=_ALLOWED) as path:
        return _state(path, study)


__all__ = [
    "AllocationRefused", "FAILURE_CODES", "G1_RESERVATION", "G1_TERMINAL", "G2_RESERVATION", "G2_TERMINAL",
    "NATIVE_STATUS", "RECEIPTS", "STUDY_RESERVATION", "STUDY_TERMINAL", "StudySpec", "WorkerSpec", "failure_for",
    "finish_study", "finish_worker", "read_state", "reserve_study", "reserve_worker",
]
