"""Public-text allocation sequencing: one study, two workers, no repair or retry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
from typing import cast

import pytest

from retrieval_public_text_allocation import (
    G1_RESERVATION, G1_TERMINAL, G2_RESERVATION, G2_TERMINAL, NATIVE_STATUS, STUDY_RESERVATION, STUDY_TERMINAL,
    AllocationRefused, StudySpec, WorkerSpec, finish_study, finish_worker, read_state, reserve_study, reserve_worker,
)
from retrieval_public_text_allocation_io import canonical_receipt_bytes, receipt_digest


def _sha(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("ascii")).hexdigest()


def _study(tag: str = "base", *, functional_only: bool = True, phase_id: str = "REPOMAP-CLOE-PUBLIC-TEXT1") -> StudySpec:
    return StudySpec(phase_id, "PUBLICTEXT-CAL1-" + tag, _sha("source:" + tag), _sha("tasks:" + tag),
                     _sha("profile:" + tag), _sha("approval:" + tag), _sha("transition:" + tag), functional_only)


def _worker(generation: int, tag: str = "base", *, study_tag: str | None = None, **changes: str) -> WorkerSpec:
    values = {
        "study_identity": _sha("study:" + (study_tag or tag)),
        "request_sha256": _sha(f"request:g{generation}:{tag}"),
        "publication_identity": _sha(f"publication:g{generation}:{tag}"),
        "input_identity": _sha(f"input:g{generation}:{tag}"),
        "nonce": hashlib.sha256(f"nonce:g{generation}:{tag}".encode()).hexdigest(),
        "frame_sha256": _sha(f"frame:g{generation}:{tag}"),
        "preparation_identity": _sha(f"preparation:g{generation}:{tag}"),
        "census_identity": _sha(f"census:g{generation}:{tag}"),
        "estimate_identity": _sha(f"estimate:g{generation}:{tag}"),
    }
    values.update(changes)
    return WorkerSpec(generation=generation, **values)


def _complete(root: Path, study: StudySpec, tag: str = "base") -> None:
    reserve_study(root, study)
    reserve_worker(root, study, _worker(1, tag))
    finish_worker(root, study, _worker(1, tag), status="completed", clean=True)
    reserve_worker(root, study, _worker(2, tag, study_tag=tag), stale_g1_proof_sha256=_sha("stale-proof:" + tag))
    finish_worker(root, study, _worker(2, tag, study_tag=tag), status="completed", clean=True)
    finish_study(root, study, status="completed", failure_code=None, cleanup_clean=True,
                 cleanup_evidence_sha256=_sha("cleanup:" + tag))


@pytest.mark.parametrize("clean,code,opposite", [
    (True, "study_evidence_failed", "study_cleanup_failed"),
    (False, "study_cleanup_failed", "study_evidence_failed"),
])
def test_completed_workers_keep_evidence_failure_separate_from_cleanup(
        tmp_path: Path, clean: bool, code: str, opposite: str) -> None:
    root, study = tmp_path / "allocation", _study()
    reserve_study(root, study)
    for generation in (1, 2):
        worker = _worker(generation)
        reserve_worker(root, study, worker, stale_g1_proof_sha256=None if generation == 1 else _sha("stale"))
        finish_worker(root, study, worker, status="completed", clean=True)
    with pytest.raises(AllocationRefused, match="failure code"):
        finish_study(root, study, status="failed", failure_code=opposite, cleanup_clean=clean,
                     cleanup_evidence_sha256=_sha("actual-cleanup"))
    terminal = finish_study(root, study, status="failed", failure_code=code, cleanup_clean=clean,
                            cleanup_evidence_sha256=_sha("actual-cleanup"))
    assert terminal["clean"] is clean and terminal["failure_code"] == code
    assert read_state(root, study)["study-terminal.json"] == terminal
    _rewrite(root / "study-terminal.json", lambda item: item.update(failure_code=opposite))
    with pytest.raises(AllocationRefused, match="inconsistent"):
        read_state(root, study)


def _rewrite(path: Path, change) -> None:
    value = json.loads(path.read_bytes())
    change(value)
    body = dict(value)
    body.pop("receipt_sha256")
    value["receipt_sha256"] = receipt_digest(canonical_receipt_bytes(body))
    path.write_bytes(canonical_receipt_bytes(value))
    path.chmod(0o600)


def test_unsafe_phase_identity_refuses_before_root_creation(tmp_path: Path) -> None:
    root = tmp_path / "allocation"
    with pytest.raises(AllocationRefused):
        reserve_study(root, _study(phase_id="../public-text"))
    assert not root.exists()


def test_study_reservation_holds_only_preflight_invariants(tmp_path: Path) -> None:
    record = reserve_study(tmp_path / "allocation", _study())
    assert "study_identity" not in record and "request_sha256" not in record
    assert record["functional_only"] is True and record["native_status"] == NATIVE_STATUS
    native = reserve_study(tmp_path / "native", _study("native", functional_only=False))
    assert native["functional_only"] is False and native["native_status"] == NATIVE_STATUS


def test_failure_before_g1_has_no_forged_worker_records(tmp_path: Path) -> None:
    root, study = tmp_path / "allocation", _study("before-g1")
    reserve_study(root, study)
    finish_study(root, study, status="failed", failure_code="study_initialization_failed", cleanup_clean=True,
                 cleanup_evidence_sha256=_sha("cleanup"))
    state = read_state(root, study)
    terminal = state[STUDY_TERMINAL]
    assert terminal is not None and terminal["study_identity"] is None
    assert (terminal["g1_state"], terminal["g2_state"]) == ("unstarted", "unstarted")
    assert all(state[name] is None for name in (G1_RESERVATION, G1_TERMINAL, G2_RESERVATION, G2_TERMINAL))


def test_clean_g1_can_end_failed_before_g2_only_with_the_truthful_code(tmp_path: Path) -> None:
    root, study = tmp_path / "allocation", _study("g2-gate")
    reserve_study(root, study)
    reserve_worker(root, study, _worker(1))
    finish_worker(root, study, _worker(1), status="completed", clean=True)
    for code in ("invented", "g1_failed", None):
        with pytest.raises(AllocationRefused):
            finish_study(root, study, status="failed", failure_code=code, cleanup_clean=True,
                         cleanup_evidence_sha256=_sha("cleanup"))
    with pytest.raises(AllocationRefused):
        finish_study(root, study, status="completed", failure_code=None, cleanup_clean=True,
                     cleanup_evidence_sha256=_sha("cleanup"))
    finish_study(root, study, status="failed", failure_code="g2_preflight_refused", cleanup_clean=True,
                 cleanup_evidence_sha256=_sha("cleanup"))
    assert read_state(root, study)[G2_RESERVATION] is None


def test_two_workers_bind_one_study_and_remain_not_asserted(tmp_path: Path) -> None:
    root, study = tmp_path / "allocation", _study()
    _complete(root, study)
    state = read_state(root, study)
    g1, g2 = state[G1_RESERVATION], state[G2_RESERVATION]
    assert g1 is not None and g2 is not None and g1["study_identity"] == g2["study_identity"]
    assert all(g1[name] != g2[name] for name in ("request_sha256", "publication_identity", "nonce"))
    terminal = state[STUDY_TERMINAL]
    assert terminal is not None and terminal["status"] == "completed"
    for record in state.values():
        assert record is not None and record["native_status"] == NATIVE_STATUS
        assert not {"path", "raw_text", "password", "token"} & set(record)


def test_g1_failure_finishes_honestly_and_blocks_g2(tmp_path: Path) -> None:
    root, study = tmp_path / "allocation", _study("g1-failed")
    reserve_study(root, study)
    reserve_worker(root, study, _worker(1))
    finish_worker(root, study, _worker(1), status="failed", clean=True)
    with pytest.raises(AllocationRefused):
        reserve_worker(root, study, _worker(2), stale_g1_proof_sha256=_sha("proof"))
    finish_study(root, study, status="failed", failure_code="g1_failed", cleanup_clean=True,
                 cleanup_evidence_sha256=_sha("cleanup"))
    terminal = read_state(root, study)[STUDY_TERMINAL]
    assert terminal is not None and terminal["g2_state"] == "unstarted"


def test_g2_failure_is_terminal_but_never_successful(tmp_path: Path) -> None:
    root, study = tmp_path / "allocation", _study("g2-failed")
    reserve_study(root, study)
    reserve_worker(root, study, _worker(1))
    finish_worker(root, study, _worker(1), status="completed", clean=True)
    reserve_worker(root, study, _worker(2, study_tag="base"), stale_g1_proof_sha256=_sha("proof"))
    finish_worker(root, study, _worker(2, study_tag="base"), status="failed", clean=False)
    with pytest.raises(AllocationRefused):
        finish_study(root, study, status="completed", failure_code=None, cleanup_clean=True,
                     cleanup_evidence_sha256=_sha("cleanup"))
    finish_study(root, study, status="failed", failure_code="g2_failed", cleanup_clean=False,
                 cleanup_evidence_sha256=_sha("cleanup"))


def test_generation_two_requires_same_study_distinct_actuals_and_separate_proof(tmp_path: Path) -> None:
    root, study = tmp_path / "allocation", _study("identity")
    g1 = _worker(1)
    reserve_study(root, study)
    with pytest.raises(AllocationRefused):
        reserve_worker(root, study, _worker(2), stale_g1_proof_sha256=_sha("proof"))
    reserve_worker(root, study, g1)
    with pytest.raises(AllocationRefused):
        reserve_worker(root, study, _worker(2), stale_g1_proof_sha256=_sha("proof"))
    finish_worker(root, study, g1, status="completed", clean=True)
    prior = read_state(root, study)[G1_RESERVATION]
    assert prior is not None
    attempts = (
        (_worker(2), prior["receipt_sha256"]),
        (_worker(2, study_tag="other"), _sha("proof")),
        (_worker(2, request_sha256=g1.request_sha256), _sha("proof")),
        (_worker(2, publication_identity=g1.publication_identity), _sha("proof")),
        (_worker(2, nonce=g1.nonce), _sha("proof")),
        (_worker(2), None),
    )
    for worker, proof in attempts:
        with pytest.raises(AllocationRefused):
            reserve_worker(root, study, worker, stale_g1_proof_sha256=cast(str | None, proof))
    reserve_worker(root, study, _worker(2), stale_g1_proof_sha256=_sha("proof"))


def test_replay_wrong_spec_and_malformed_inputs_refuse(tmp_path: Path) -> None:
    root, study = tmp_path / "allocation", _study("replay")
    _complete(root, study, "replay")
    g1 = _worker(1, "replay")
    actions = (
        lambda: reserve_study(root, study),
        lambda: reserve_worker(root, study, g1),
        lambda: finish_worker(root, study, g1, status="completed", clean=True),
        lambda: finish_study(root, study, status="completed", failure_code=None, cleanup_clean=True,
                             cleanup_evidence_sha256=_sha("again")),
        lambda: read_state(root, _study("other")),
        lambda: reserve_worker(root, study, _worker(3, "replay")),
        lambda: reserve_worker(root, study, _worker(1, "replay", nonce="ABC")),
        lambda: finish_worker(root, study, g1, status="done", clean=True),
        lambda: finish_worker(root, study, g1, status="completed", clean=cast(bool, 1)),
    )
    for action in actions:
        with pytest.raises(AllocationRefused):
            action()


@pytest.mark.parametrize("name,change", [
    (G1_TERMINAL, lambda v: v.update(reservation_sha256=_sha("wrong"))),
    (STUDY_RESERVATION, lambda v: v.update(functional_only=1)),
    (G1_RESERVATION, lambda v: v.update(generation=2, attempt_label="w5-semantic-g2")),
    (G2_RESERVATION, lambda v: v.update(study_identity=_sha("study:other"))),
    (STUDY_TERMINAL, lambda v: v.update(failure_code="g1_failed", status="failed")),
    (G1_TERMINAL, lambda v: v.update(native_status="asserted")),
    (G2_TERMINAL, lambda v: v.update(extra=True)),
])
def test_well_hashed_cross_link_and_closed_field_mutations_refuse(tmp_path: Path, name: str, change) -> None:
    root, study = tmp_path / "allocation", _study("mutations")
    _complete(root, study, "mutations")
    _rewrite(root / name, change)
    with pytest.raises(AllocationRefused):
        read_state(root, study)


def test_torn_unknown_symlink_and_mode_custody_refuse(tmp_path: Path) -> None:
    root, study = tmp_path / "torn", _study("torn")
    reserve_study(root, study)
    (root / STUDY_RESERVATION).write_bytes(b'{"schema":')
    with pytest.raises(AllocationRefused):
        read_state(root, study)
    unknown = tmp_path / "unknown"
    unknown.mkdir(mode=0o700)
    (unknown / "unexpected").write_bytes(b"x")
    (unknown / "unexpected").chmod(0o600)
    with pytest.raises(AllocationRefused):
        reserve_study(unknown, study)
    linked = tmp_path / "linked"
    linked.mkdir(mode=0o700)
    (linked / "target").write_bytes(b"x")
    (linked / STUDY_RESERVATION).symlink_to("target")
    with pytest.raises(AllocationRefused):
        reserve_study(linked, study)
    mode = tmp_path / "mode"
    reserve_study(mode, study)
    (mode / STUDY_RESERVATION).chmod(0o644)
    with pytest.raises(AllocationRefused):
        read_state(mode, study)


def test_concurrent_study_reservation_spends_exactly_once(tmp_path: Path) -> None:
    root, study = tmp_path / "allocation", _study("concurrent")
    root.mkdir(mode=0o700)
    barrier, results = threading.Barrier(4), []

    def contend() -> None:
        barrier.wait()
        try:
            reserve_study(root, study)
        except AllocationRefused:
            results.append("refused")
        else:
            results.append("reserved")

    threads = [threading.Thread(target=contend) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(results) == ["refused", "refused", "refused", "reserved"]
