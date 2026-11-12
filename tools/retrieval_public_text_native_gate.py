"""Closed public-text generation-gate frames and the one-shot bounded log reader (study section 19.3).

The inner driver prints one canonical frame, prefixed and LF-terminated,
after ``publish_request`` and before generic readiness. Every value is a
bounded digest, count, enum or boolean actually observed inside the
evaluator; there is no host transition-gate field. The reader reads an owned
0600 log once, after readiness, without waiting. A frame is evidence for the
private host, never authority: ``validate_native_gate`` additionally refuses
``functional_only: true``.
"""

from __future__ import annotations

from typing import cast

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from retrieval_public_text_preflight import PreflightRefusal, checked_counts, estimate_generation

PHASE = "REPOMAP-CLOE-PUBLIC-TEXT1"
ALLOCATION = "PUBLICTEXT-CAL1"
FRAME_SCHEMA = "cloe-publictext-generation-gate-v1"
PROOF_SCHEMA = "cloe-publictext-stale-publication-proof-v1"
PREFIX = b"CLOE_PUBLICTEXT_GENERATION_GATE "
MAX_LOG_BYTES = 8 * 1024 * 1024
MAX_FRAME_BYTES = 64 * 1024
STALE_PIN_REFUSAL = "stale_publication_receipt"
BATCH_STATUSES = frozenset({"imported_non_current", "not_imported_non_current"})
ATTEMPTS = {1: "w5-semantic-g1", 2: "w5-semantic-g2"}
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[0-9a-f]{64}\Z")
FRAME_DIGESTS = (
    "study_identity", "request_sha256", "input_identity", "publication_identity", "artifact_profile_identity",
    "q_source_closure_identity", "worker_source_closure_identity", "task_pins_identity",
    "selected_task_set_identity", "census_identity", "preparation_identity", "estimate_gate_identity",
)
FRAME_FIELDS = frozenset({
    "schema", "phase", "allocation", "attempt_id", "generation", "nonce", "record_counts", "functional_only",
    "stale_g1_proof", *FRAME_DIGESTS,
})
PROOF_FIELDS = frozenset({"schema", "old_publication_identity", "new_publication_identity", "old_pin_refusal",
                          "old_batch_status", "raw_observation_sha256", "proof_identity"})
_STUDY_INVARIANTS = ("study_identity", "artifact_profile_identity", "q_source_closure_identity",
                     "worker_source_closure_identity", "task_pins_identity", "selected_task_set_identity")


class NativeGateRefusal(ValueError):
    """Closed refusal without raw log paths, frame content or authority claims."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _canonical(value: object) -> bytes:
    def ready(item: object) -> object:
        if item is None or type(item) in (str, bool, int):
            return item
        if isinstance(item, Mapping) and all(type(key) is str for key in item):
            return {key: ready(val) for key, val in item.items()}
        raise NativeGateRefusal("native_gate_json_value")
    text = json.dumps(ready(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return text.encode("ascii") + b"\n"


def _identity(value: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)[:-1]).hexdigest()


def _digest(value: object, code: str = "native_gate_digest") -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise NativeGateRefusal(code)
    return value


def stale_g1_proof(*, old_publication_identity: str, new_publication_identity: str, old_pin_refusal: str,
                   old_batch_status: str, raw_observation_sha256: str) -> dict[str, object]:
    """Bind the actual old-pin refusal and no-vector old-batch status; nothing expected is hashed."""
    body: dict[str, object] = {
        "schema": PROOF_SCHEMA, "old_publication_identity": old_publication_identity,
        "new_publication_identity": new_publication_identity, "old_pin_refusal": old_pin_refusal,
        "old_batch_status": old_batch_status, "raw_observation_sha256": raw_observation_sha256,
    }
    return _validate_proof({**body, "proof_identity": _identity(body)})


def _validate_proof(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != PROOF_FIELDS or value["schema"] != PROOF_SCHEMA:
        raise NativeGateRefusal("native_gate_stale_proof_fields")
    for name in ("old_publication_identity", "new_publication_identity", "raw_observation_sha256"):
        _digest(value[name], "native_gate_stale_proof_digest")
    if value["old_publication_identity"] == value["new_publication_identity"]:
        raise NativeGateRefusal("native_gate_stale_proof_publications")
    if value["old_pin_refusal"] != STALE_PIN_REFUSAL or value["old_batch_status"] not in BATCH_STATUSES:
        raise NativeGateRefusal("native_gate_stale_proof_observation")
    body = {key: item for key, item in value.items() if key != "proof_identity"}
    if value["proof_identity"] != _identity(body):
        raise NativeGateRefusal("native_gate_stale_proof_identity")
    return value


def _validate_frame(frame: object, *, native: bool = False) -> dict[str, object]:
    if type(frame) is not dict or set(frame) != FRAME_FIELDS:
        raise NativeGateRefusal("native_gate_fields")
    if (frame["schema"], frame["phase"], frame["allocation"]) != (FRAME_SCHEMA, PHASE, ALLOCATION):
        raise NativeGateRefusal("native_gate_header")
    generation = frame["generation"]
    if type(generation) is not int or generation not in ATTEMPTS or frame["attempt_id"] != ATTEMPTS[generation]:
        raise NativeGateRefusal("native_gate_generation")
    if type(frame["nonce"]) is not str or _NONCE.fullmatch(frame["nonce"]) is None:
        raise NativeGateRefusal("native_gate_nonce")
    for name in FRAME_DIGESTS:
        _digest(frame[name])
    if type(frame["functional_only"]) is not bool:
        raise NativeGateRefusal("native_gate_functional_flag")
    try:
        counts = checked_counts(frame["record_counts"], generation)
        estimate = estimate_generation(generation, counts)
    except PreflightRefusal:
        raise NativeGateRefusal("native_gate_counts_or_estimate") from None
    if frame["record_counts"] != counts or estimate["estimate_gate_identity"] != frame["estimate_gate_identity"]:
        raise NativeGateRefusal("native_gate_counts_or_estimate")
    proof = frame["stale_g1_proof"]
    if generation == 1 and proof is not None:
        raise NativeGateRefusal("native_gate_g1_stale_proof")
    if generation == 2 and _validate_proof(proof)["new_publication_identity"] != frame["publication_identity"]:
        raise NativeGateRefusal("native_gate_stale_proof_binding")
    if native and frame["functional_only"] is not False:
        raise NativeGateRefusal("native_gate_functional_frame")
    return frame


def gate_frame(*, generation: int, nonce: str, record_counts: Mapping[str, int], functional_only: bool,
               stale_proof: Mapping[str, object] | None, **digests: str) -> dict[str, object]:
    """Assemble and validate one frame from actual values; the estimate is recomputed here."""
    if set(digests) != set(FRAME_DIGESTS) - {"estimate_gate_identity"}:
        raise NativeGateRefusal("native_gate_fields")
    try:
        estimate = estimate_generation(generation, record_counts)
    except PreflightRefusal:
        raise NativeGateRefusal("native_gate_counts_or_estimate") from None
    frame = {
        "schema": FRAME_SCHEMA, "phase": PHASE, "allocation": ALLOCATION, "attempt_id": ATTEMPTS.get(generation),
        "generation": generation, "nonce": nonce, "record_counts": dict(record_counts),
        "functional_only": functional_only, "stale_g1_proof": None if stale_proof is None else dict(stale_proof),
        "estimate_gate_identity": estimate["estimate_gate_identity"], **digests,
    }
    return _validate_frame(frame)


def encode_gate(frame: Mapping[str, object]) -> bytes:
    """Canonical frame bytes plus LF; encoding authorizes nothing."""
    raw = _canonical(_validate_frame(dict(frame)))
    if len(raw) > MAX_FRAME_BYTES:
        raise NativeGateRefusal("native_gate_frame_bounds")
    return raw


def format_gate(frame: Mapping[str, object]) -> bytes:
    return PREFIX + encode_gate(frame)


def decode_gate(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_FRAME_BYTES or not raw.endswith(b"\n"):
        raise NativeGateRefusal("native_gate_frame_bounds")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise NativeGateRefusal("native_gate_decode") from None
    frame = _validate_frame(value)
    if _canonical(frame) != raw:
        raise NativeGateRefusal("native_gate_noncanonical")
    return frame


def validate_native_gate(frame: Mapping[str, object]) -> dict[str, object]:
    """Native-only check: a functional frame never reaches a native reservation."""
    return _validate_frame(dict(frame), native=True)


def _log_bytes(path: Path) -> bytes:
    if not _NOFOLLOW or not isinstance(path, Path) or not path.is_absolute():
        raise NativeGateRefusal("native_frame_log_path")
    try:
        descriptor = os.open(str(path), os.O_RDONLY | _NOFOLLOW | _CLOEXEC | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        raise NativeGateRefusal("native_frame_log_unavailable") from None
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600):
            raise NativeGateRefusal("native_frame_log_custody")
        if not 0 < before.st_size <= MAX_LOG_BYTES:
            raise NativeGateRefusal("native_frame_log_bounds")
        raw = bytearray()
        while len(raw) <= MAX_LOG_BYTES:
            part = os.read(descriptor, min(65536, MAX_LOG_BYTES + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        after = os.fstat(descriptor)
        if len(raw) > MAX_LOG_BYTES or after.st_size > MAX_LOG_BYTES:
            raise NativeGateRefusal("native_frame_log_bounds")
        if after.st_size < before.st_size or len(raw) < before.st_size:
            raise NativeGateRefusal("native_frame_log_truncated")
        current = os.lstat(path)
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino) or stat.S_ISLNK(current.st_mode):
            raise NativeGateRefusal("native_frame_log_replaced")
        return bytes(raw)
    except OSError:
        raise NativeGateRefusal("native_frame_log_read_failed") from None
    finally:
        os.close(descriptor)


def read_actual_gate(log_path: Path, *, generation: int, nonce: str,
                     request_sha256: str) -> tuple[dict[str, object], bytes, str]:
    """Read once after readiness: exact ordered unique frames bound to the actual nonce and request."""
    if type(generation) is not int or generation not in ATTEMPTS:
        raise NativeGateRefusal("native_frame_generation")
    if type(nonce) is not str or _NONCE.fullmatch(nonce) is None:
        raise NativeGateRefusal("native_frame_nonce")
    _digest(request_sha256, "native_frame_request_digest")
    lines = _log_bytes(log_path).split(b"\n")
    if lines[-1].startswith(PREFIX):
        raise NativeGateRefusal("native_frame_incomplete")
    frames: list[tuple[dict[str, object], bytes]] = []
    for line in lines[:-1]:
        if not line.startswith(PREFIX):
            continue
        payload = line[len(PREFIX):] + b"\n"
        try:
            frames.append((decode_gate(payload), payload))
        except NativeGateRefusal:
            raise NativeGateRefusal("native_frame_decode_refused") from None
    if [value["generation"] for value, _payload in frames] != list(range(1, generation + 1)):
        raise NativeGateRefusal("native_frame_missing_duplicate_or_out_of_order")
    if len({value["nonce"] for value, _ in frames}) != generation or len(
            {value["request_sha256"] for value, _ in frames}) != generation:
        raise NativeGateRefusal("native_frame_duplicate_identity")
    if generation == 2 and any(frames[0][0][name] != frames[1][0][name] for name in _STUDY_INVARIANTS):
        raise NativeGateRefusal("native_frame_cross_generation_mismatch")
    if generation == 2 and cast(dict[str, object], frames[1][0]["stale_g1_proof"])["old_publication_identity"] != frames[0][0][
            "publication_identity"]:
        raise NativeGateRefusal("native_frame_old_publication_mismatch")
    value, payload = frames[-1]
    if (value["nonce"], value["request_sha256"]) != (nonce, request_sha256):
        raise NativeGateRefusal("native_frame_actual_request_mismatch")
    return value, payload, "sha256:" + hashlib.sha256(payload).hexdigest()


__all__ = [
    "ALLOCATION", "BATCH_STATUSES", "FRAME_FIELDS", "MAX_FRAME_BYTES", "MAX_LOG_BYTES", "NativeGateRefusal",
    "PHASE", "PREFIX", "STALE_PIN_REFUSAL", "decode_gate", "encode_gate", "format_gate", "gate_frame",
    "read_actual_gate", "stale_g1_proof", "validate_native_gate",
]
