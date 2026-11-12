"""Closed generation-frame codec and the one-shot owned log reader, over real 0600 files."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import cast

import pytest

import retrieval_public_text_native_gate as gate
from retrieval_public_text_native_gate import (
    MAX_FRAME_BYTES, MAX_LOG_BYTES, PREFIX, NativeGateRefusal, decode_gate, encode_gate, format_gate, gate_frame,
    read_actual_gate, stale_g1_proof, validate_native_gate,
)

G1 = {"v1.document": 30, "ptx.document": 20, "v1.query": 4, "ptx.query": 2}
G2 = {"v1.document": 30, "ptx.document": 20, "v1.query": 0, "ptx.query": 0}


def _sha(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


def _digests(generation: int, **changes: str) -> dict[str, str]:
    values = {name: _sha(name) for name in (
        "study_identity", "artifact_profile_identity", "q_source_closure_identity", "worker_source_closure_identity",
        "task_pins_identity", "selected_task_set_identity", "census_identity", "preparation_identity")}
    values.update(request_sha256=_sha(f"request{generation}"), input_identity=_sha(f"input{generation}"),
                  publication_identity=_sha(f"publication{generation}"))
    values.update(changes)
    return values


def _proof(**changes: str) -> dict[str, object]:
    values = {"old_publication_identity": _sha("publication1"), "new_publication_identity": _sha("publication2"),
              "old_pin_refusal": "stale_publication_receipt", "old_batch_status": "imported_non_current",
              "raw_observation_sha256": _sha("raw-status")}
    values.update(changes)
    return stale_g1_proof(**values)


def _frame(generation: int, *, functional_only: bool = True, **changes: str) -> dict[str, object]:
    return gate_frame(generation=generation, nonce=hashlib.sha256(f"n{generation}".encode()).hexdigest(),
                      record_counts=G1 if generation == 1 else G2, functional_only=functional_only,
                      stale_proof=None if generation == 1 else _proof(), **_digests(generation, **changes))


def _log(tmp_path: Path, body: bytes, *, mode: int = 0o600) -> Path:
    path = tmp_path / "canonical.stdout.log"
    path.write_bytes(body)
    path.chmod(mode)
    return path


def _read(path: Path, frame: dict[str, object]):
    return read_actual_gate(path, generation=cast(int, frame["generation"]), nonce=cast(str, frame["nonce"]),
                            request_sha256=cast(str, frame["request_sha256"]))


def test_frames_round_trip_canonically_and_omit_host_transition_fields() -> None:
    g1, g2 = _frame(1), _frame(2)
    assert decode_gate(encode_gate(g1)) == g1 and decode_gate(encode_gate(g2)) == g2
    assert "transition_gate_identity" not in g1 and g1["stale_g1_proof"] is None
    proof = cast(dict[str, object], g2["stale_g1_proof"])
    assert proof["new_publication_identity"] == g2["publication_identity"]
    assert format_gate(g1).startswith(PREFIX) and format_gate(g1).endswith(b"\n")


def test_native_validation_refuses_functional_frames_only() -> None:
    with pytest.raises(NativeGateRefusal, match="functional_frame"):
        validate_native_gate(_frame(1))
    assert validate_native_gate(_frame(1, functional_only=False))["functional_only"] is False


@pytest.mark.parametrize("mutate,code", [
    (lambda f: f.update(extra=1), "native_gate_fields"),
    (lambda f: f.update(transition_gate_identity=_sha("t")), "native_gate_fields"),
    (lambda f: f.update(phase="OTHER"), "native_gate_header"),
    (lambda f: f.update(attempt_id="w5-semantic-g2"), "native_gate_generation"),
    (lambda f: f.update(generation=True), "native_gate_generation"),
    (lambda f: f.update(nonce="A" * 64), "native_gate_nonce"),
    (lambda f: f.update(census_identity="sha256:short"), "native_gate_digest"),
    (lambda f: f.update(functional_only=1), "native_gate_functional_flag"),
    (lambda f: f.update(record_counts={**G1, "v1.query": 5}), "native_gate_counts_or_estimate"),
    (lambda f: f.update(estimate_gate_identity=_sha("other")), "native_gate_counts_or_estimate"),
    (lambda f: f.update(stale_g1_proof=_proof()), "native_gate_g1_stale_proof"),
])
def test_closed_g1_frame_refusals(mutate, code: str) -> None:
    frame = _frame(1)
    mutate(frame)
    with pytest.raises(NativeGateRefusal) as raised:
        encode_gate(frame)
    assert raised.value.code == code


def test_g2_stale_proof_must_be_actual_bound_and_self_consistent() -> None:
    with pytest.raises(NativeGateRefusal, match="publications"):
        _proof(new_publication_identity=_sha("publication1"))
    with pytest.raises(NativeGateRefusal, match="observation"):
        _proof(old_pin_refusal="expected_state")
    with pytest.raises(NativeGateRefusal, match="observation"):
        _proof(old_batch_status="current")
    frame = _frame(2)
    proof = cast(dict[str, object], frame["stale_g1_proof"])
    frame["stale_g1_proof"] = {**proof, "raw_observation_sha256": _sha("other")}
    with pytest.raises(NativeGateRefusal, match="stale_proof_identity"):
        encode_gate(frame)
    with pytest.raises(NativeGateRefusal, match="stale_proof_binding"):
        _frame(2, publication_identity=_sha("publication3"))
    frame = _frame(2)
    frame["stale_g1_proof"] = None
    with pytest.raises(NativeGateRefusal):
        encode_gate(frame)


@pytest.mark.parametrize("raw", [
    b"", b"{}", b"not json\n", b"\xff\n", b" " * (MAX_FRAME_BYTES + 1),
])
def test_decode_refuses_bounds_and_malformed_bytes(raw: bytes) -> None:
    with pytest.raises(NativeGateRefusal):
        decode_gate(raw)


def test_decode_refuses_noncanonical_but_equal_json() -> None:
    raw = json.dumps(_frame(1), sort_keys=False, separators=(", ", ": ")).encode() + b"\n"
    with pytest.raises(NativeGateRefusal, match="noncanonical"):
        decode_gate(raw)


def test_reader_binds_actual_nonce_request_and_order(tmp_path: Path) -> None:
    g1, g2 = _frame(1), _frame(2)
    body = b"progress\n" + format_gate(g1) + b"CLOE_W5_COMPONENT_READY {}\n"
    value, payload, digest = _read(_log(tmp_path, body), g1)
    assert value == g1 and digest == "sha256:" + hashlib.sha256(payload).hexdigest()
    log = _log(tmp_path, body + b"more output\n" + format_gate(g2) + b"partial line without newline")
    assert _read(log, g2)[0] == g2
    with pytest.raises(NativeGateRefusal, match="actual_request_mismatch"):
        read_actual_gate(log, generation=2, nonce=cast(str, g2["nonce"]), request_sha256=_sha("other"))
    with pytest.raises(NativeGateRefusal, match="actual_request_mismatch"):
        read_actual_gate(log, generation=2, nonce="0" * 64,
                         request_sha256=cast(str, g2["request_sha256"]))


@pytest.mark.parametrize("builder,generation,code", [
    (lambda g1, g2: b"", 1, "native_frame_log_bounds"),
    (lambda g1, g2: b"noise\n", 1, "native_frame_missing_duplicate_or_out_of_order"),
    (lambda g1, g2: format_gate(g1) + format_gate(g1), 1, "native_frame_missing_duplicate_or_out_of_order"),
    (lambda g1, g2: format_gate(g2) + format_gate(g1), 2, "native_frame_missing_duplicate_or_out_of_order"),
    (lambda g1, g2: format_gate(g2), 2, "native_frame_missing_duplicate_or_out_of_order"),
    (lambda g1, g2: format_gate(g1) + PREFIX + b"{\"x\":1}\n", 2, "native_frame_decode_refused"),
    (lambda g1, g2: format_gate(g1)[:-1], 1, "native_frame_incomplete"),
    (lambda g1, g2: format_gate(g1) + format_gate({**g2, "nonce": g1["nonce"]}), 2, "native_frame_duplicate_identity"),
])
def test_reader_refuses_missing_duplicate_out_of_order_malformed_or_unbound(
        tmp_path: Path, builder, generation: int, code: str) -> None:
    g1, g2 = _frame(1), _frame(2)
    path = _log(tmp_path, builder(g1, g2))
    expected = g1 if generation == 1 else g2
    with pytest.raises(NativeGateRefusal) as raised:
        _read(path, expected)
    assert raised.value.code == code


def test_reader_refuses_cross_generation_study_mismatch(tmp_path: Path) -> None:
    g1, g2 = _frame(1), _frame(2, study_identity=_sha("another-study"))
    with pytest.raises(NativeGateRefusal, match="cross_generation"):
        _read(_log(tmp_path, format_gate(g1) + format_gate(g2)), g2)


def test_reader_joins_stale_old_publication_to_actual_first_frame(tmp_path: Path) -> None:
    g1, g2 = _frame(1), _frame(2)
    g2["stale_g1_proof"] = _proof(old_publication_identity=_sha("unrelated-publication"))
    with pytest.raises(NativeGateRefusal, match="old_publication_mismatch"):
        _read(_log(tmp_path, format_gate(g1) + format_gate(g2)), g2)


def test_reader_refuses_a_real_fifo_without_waiting_for_a_writer(tmp_path: Path) -> None:
    path = tmp_path / "owned.fifo"
    os.mkfifo(path, 0o600)
    with pytest.raises(NativeGateRefusal, match="custody"):
        _read(path, _frame(1))


def test_reader_custody_refusals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    g1 = _frame(1)
    with pytest.raises(NativeGateRefusal, match="custody"):
        _read(_log(tmp_path, format_gate(g1), mode=0o644), g1)
    with pytest.raises(NativeGateRefusal, match="log_path"):
        read_actual_gate(Path("relative.log"), generation=1, nonce=cast(str, g1["nonce"]),
                         request_sha256=cast(str, g1["request_sha256"]))
    target = _log(tmp_path, format_gate(g1))
    link = tmp_path / "link.log"
    link.symlink_to(target)
    with pytest.raises(NativeGateRefusal, match="unavailable"):
        _read(link, g1)
    with pytest.raises(NativeGateRefusal, match="unavailable"):
        _read(tmp_path / "missing.log", g1)
    big = tmp_path / "big.log"
    with big.open("wb") as handle:
        handle.truncate(MAX_LOG_BYTES + 1)
    big.chmod(0o600)
    with pytest.raises(NativeGateRefusal, match="log_bounds"):
        _read(big, g1)


class _OsView:
    """Module-local ``os`` view for the gate owner only; the real process ``os`` is untouched."""

    def __init__(self, **overrides) -> None:
        self._overrides = overrides

    def __getattr__(self, name: str):
        return self._overrides.get(name, getattr(os, name))


def test_reader_refuses_a_replaced_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    g1 = _frame(1)
    replacement = tmp_path / "replacement.log"
    replacement.write_bytes(format_gate(g1))
    replacement.chmod(0o600)
    path = _log(tmp_path, format_gate(g1))

    def swapped_lstat(target, *args, **kwargs):
        return os.lstat(replacement) if Path(target) == path else os.lstat(target, *args, **kwargs)

    monkeypatch.setattr(gate, "os", _OsView(lstat=swapped_lstat))
    with pytest.raises(NativeGateRefusal, match="replaced"):
        _read(path, g1)


def test_reader_refuses_a_log_truncated_during_the_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    g1 = _frame(1)
    path = _log(tmp_path, b"x" * 64 + b"\n" + format_gate(g1))
    calls = {"n": 0}

    def truncating_read(descriptor: int, size: int) -> bytes:
        calls["n"] += 1
        if calls["n"] == 2:
            os.truncate(path, 10)
        return os.read(descriptor, min(size, 16))

    monkeypatch.setattr(gate, "os", _OsView(read=truncating_read))
    with pytest.raises(NativeGateRefusal, match="truncated"):
        _read(path, g1)
