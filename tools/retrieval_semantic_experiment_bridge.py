"""Nonce-bound request/response exchange for the isolated W5 component.

This client only writes data files and emits a readiness record.  It never
starts, signals, or interprets a model process; the phase-private supervisor
owns that work and must return the complete maintained response bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Mapping

from retrieval_semantic_bridge_transport import (
    BridgeRefusal,
    ReadyEvent,
    READY_PREFIX,
    READY_SCHEMA,
    SANDBOX_SCRATCH_ROOT,
)
from retrieval_semantic_bridge_transport_io import (
    read_response_files,
    write_request_file,
)
from retrieval_semantic_generator_worker_protocol import (
    MAX_ADMISSION_BYTES,
    _digest,
    _source_digests,
    parse_controller_admission,
)
from retrieval_semantic_generator_worker_contracts import WORKER_SOURCE_FILES
from retrieval_semantic_experiment_contracts import (
    ExperimentRefusal,
    TIMEOUT_POLICY,
    canonical_json_bytes,
)

ADMISSION_ACK_PREFIX = "CLOE_W5_COMPONENT_ADMISSION_ACK "
CONTROLLER_ADMISSION_NAME = "controller.admission.json"
CONTROLLER_ADMISSION_READY_NAME = "controller.admission.ready.json"
CONTROLLER_ADMISSION_READY_SCHEMA = "cloe-w5-controller-admission-ready-v1"
_NONCE = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MARKER_MAX_BYTES = 4096


@dataclass(frozen=True)
class ComponentExchange:
    """Prepared request and controller admission for one owned nonce path."""

    attempt_id: str
    nonce: str
    directory: Path
    request_raw: bytes
    admission_raw: bytes | None
    admission_sha256: str | None
    ready: ReadyEvent
    expected_source_closure: tuple[tuple[str, str], ...] = ()

    @property
    def readiness_line(self) -> str:
        document = {
            "schema": READY_SCHEMA,
            "nonce": self.nonce,
            "attempt_id": self.attempt_id,
            "request_relative_path": self.ready.request_relative_path,
            "request_sha256": self.ready.request_sha256,
            "request_bytes": self.ready.request_bytes,
        }
        return READY_PREFIX + canonical_json_bytes(document).decode("ascii")

    def emit_request_readiness(self) -> None:
        """Frame the durable-request event after any test progress output."""
        print("\n" + self.readiness_line, flush=True)

    @property
    def admission_ack_line(self) -> str:
        """Second-stage event: the request-bound admission is durable and accepted."""
        if self.admission_sha256 is None:
            raise ExperimentRefusal("controller_admission_required")
        return ADMISSION_ACK_PREFIX + canonical_json_bytes({
            "schema": "cloe-w5-component-admission-ack-v1",
            "nonce": self.nonce,
            "attempt_id": self.attempt_id,
            "request_sha256": self.ready.request_sha256,
            "admission_sha256": self.admission_sha256,
        }).decode("ascii")

    @classmethod
    def publish_request(
        cls,
        *,
        attempt_id: str,
        request: Mapping[str, object],
        expected_source_closure: Mapping[str, str],
    ) -> ComponentExchange:
        """Durably publish the frozen request before controller admission exists."""
        if not isinstance(request, Mapping) or not request:
            raise ExperimentRefusal("request_required")
        request_raw = canonical_json_bytes(dict(request))
        source_files = _local_worker_source_files()
        source_closure = _source_digests(source_files)
        if dict(source_closure) != dict(expected_source_closure):
            raise ExperimentRefusal("worker_source_closure_changed")
        _validate_attempt_id(attempt_id)
        root = _safe_root()
        nonce = secrets.token_hex(32)
        attempt_root = root / attempt_id
        _mkdir_owned(attempt_root, allow_existing=False)
        directory = attempt_root / f"w5-component-{nonce}"
        _mkdir_owned(directory, allow_existing=False)
        relative = f"{attempt_id}/w5-component-{nonce}/request.json"
        ready = ReadyEvent(
            nonce=nonce,
            attempt_id=attempt_id,
            request_relative_path=relative,
            request_sha256=_digest(request_raw),
            request_bytes=len(request_raw),
        )
        published = write_request_file(Path(ready.request_path), request_raw, ready)
        if isinstance(published, BridgeRefusal):
            raise ExperimentRefusal("request_" + published.code)
        return cls(
            attempt_id,
            nonce,
            directory,
            request_raw,
            None,
            None,
            ready,
            tuple(sorted(source_closure.items())),
        )

    def await_controller_admission(
        self,
        *,
        timeout_seconds: float = TIMEOUT_POLICY["controller_admission_seconds"],
    ) -> ComponentExchange:
        """Wait for this nonce's payload then ready marker and bind the admission."""
        if type(timeout_seconds) not in (int, float) or not 0.1 <= timeout_seconds <= 600.0:
            raise ExperimentRefusal("invalid_controller_timeout")
        source_closure = _source_digests(_local_worker_source_files())
        if not self.expected_source_closure or dict(source_closure) != dict(self.expected_source_closure):
            raise ExperimentRefusal("worker_source_closure_changed")
        deadline = time.monotonic() + float(timeout_seconds)
        while time.monotonic() < deadline:
            source_closure = _source_digests(_local_worker_source_files())
            if dict(source_closure) != dict(self.expected_source_closure):
                raise ExperimentRefusal("worker_source_closure_changed")
            marker_raw = _read_exchange_file(
                self.directory / CONTROLLER_ADMISSION_READY_NAME,
                maximum=_MARKER_MAX_BYTES,
                missing_code="controller_admission_marker_unreadable",
                incomplete_on_change=True,
                allow_empty=True,
                bounds_code="controller_admission_marker_malformed",
            )
            if marker_raw is None:
                time.sleep(0.05)
                continue
            marker = _parse_marker(marker_raw)
            if marker["attempt_id"] != self.attempt_id or marker["nonce"] != self.nonce:
                raise ExperimentRefusal("controller_admission_marker_identity_mismatch")
            if marker["request_sha256"] != self.ready.request_sha256:
                raise ExperimentRefusal("controller_admission_request_mismatch")
            expected_length = marker["admission_bytes"]
            assert isinstance(expected_length, int)
            admission_raw = _read_admission_payload(
                self.directory / CONTROLLER_ADMISSION_NAME,
                expected_length=expected_length,
            )
            if admission_raw is None:
                time.sleep(0.05)
                continue
            admission_sha256 = _digest(admission_raw)
            if admission_sha256 != marker["admission_sha256"]:
                raise ExperimentRefusal("controller_admission_identity_mismatch")
            parse_controller_admission(
                admission_raw,
                expected_admission_sha256=admission_sha256,
                request=json.loads(self.request_raw),
                request_sha256=self.ready.request_sha256,
                source_closure=source_closure,
            )
            if dict(_source_digests(_local_worker_source_files())) != dict(self.expected_source_closure):
                raise ExperimentRefusal("worker_source_closure_changed")
            return self._bind_controller_admission(admission_raw, admission_sha256)
        raise ExperimentRefusal("controller_admission_timeout")

    def _bind_controller_admission(self, raw: bytes, sha256: str) -> ComponentExchange:
        if self.admission_raw is not None or self.admission_sha256 is not None:
            raise ExperimentRefusal("controller_admission_repeated")
        _write_exclusive(self.directory / "admission.json", raw)
        return replace(self, admission_raw=raw, admission_sha256=sha256)

    def await_response(self, *, timeout_seconds: float = TIMEOUT_POLICY["component_response_seconds"]) -> dict[str, bytes]:
        """Wait for one complete response marker; missing output never means success."""
        if type(timeout_seconds) not in (int, float) or not 0.1 <= timeout_seconds <= 600.0:
            raise ExperimentRefusal("invalid_component_timeout")
        if self.admission_raw is None or self.admission_sha256 is None:
            raise ExperimentRefusal("controller_admission_required")
        deadline = time.monotonic() + float(timeout_seconds)
        while time.monotonic() < deadline:
            result = read_response_files(self.directory, self.nonce)
            if isinstance(result, BridgeRefusal):
                raise ExperimentRefusal("bridge_" + result.code)
            if result is not None:
                if result.get("request.json") != self.request_raw:
                    raise ExperimentRefusal("response_request_mismatch")
                if result.get("admission.json") != self.admission_raw:
                    raise ExperimentRefusal("response_admission_mismatch")
                return result
            time.sleep(0.05)
        raise ExperimentRefusal("component_response_timeout")


def _validate_attempt_id(value: object) -> None:
    if type(value) is not str or not value or len(value) > 96 or any(
        not (char.isascii() and (char.isalnum() or char in "._-")) for char in value
    ) or not value[0].isalnum():
        raise ExperimentRefusal("invalid_attempt_id")


def _local_worker_source_files() -> dict[str, bytes]:
    root = Path(__file__).resolve().parent
    files: dict[str, bytes] = {}
    for name in WORKER_SOURCE_FILES:
        path = root / name
        try:
            if path.is_symlink() or not path.is_file():
                raise ExperimentRefusal("worker_source_missing")
            files[name] = path.read_bytes()
        except OSError as exc:
            raise ExperimentRefusal("worker_source_unreadable") from exc
    return files


def _safe_root() -> Path:
    root = Path(SANDBOX_SCRATCH_ROOT)
    try:
        info = os.lstat(root)
    except OSError as exc:
        raise ExperimentRefusal("bridge_scratch_unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ExperimentRefusal("bridge_scratch_unavailable")
    return root

def _read_exchange_file(
    path: Path,
    *,
    maximum: int,
    missing_code: str,
    incomplete_on_change: bool = False,
    allow_empty: bool = False,
    bounds_code: str | None = None,
) -> bytes | None:
    try:
        parent_info = os.lstat(path.parent)
    except OSError as exc:
        raise ExperimentRefusal(missing_code) from exc
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        raise ExperimentRefusal(missing_code)
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ExperimentRefusal(missing_code) from exc
    try:
        before = os.fstat(descriptor)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ExperimentRefusal("controller_admission_type")
        if before.st_size == 0 and allow_empty:
            return None
        if not 1 <= before.st_size <= maximum:
            raise ExperimentRefusal(bounds_code or "controller_admission_bounds")
        content = bytearray()
        while len(content) <= maximum:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        after = os.fstat(descriptor)
        if (
            len(content) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            if incomplete_on_change:
                return None
            raise ExperimentRefusal("controller_admission_changed")
        return bytes(content)
    except OSError as exc:
        raise ExperimentRefusal("controller_admission_unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_admission_payload(path: Path, *, expected_length: int) -> bytes | None:
    raw = _read_exchange_file(
        path,
        maximum=MAX_ADMISSION_BYTES,
        missing_code="controller_admission_unreadable",
        incomplete_on_change=True,
    )
    if raw is None:
        return None
    if len(raw) != expected_length:
        raise ExperimentRefusal("controller_admission_length_mismatch")
    return raw

def _json_object(raw: bytes) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_marker_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise ValueError("nonfinite_marker")

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject_constant)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise ValueError("noncanonical_marker")
    return value


def _parse_marker(raw: bytes) -> dict[str, object]:
    try:
        if not raw.endswith(b"\n"):
            raise ValueError("marker_line_termination_required")
        value = _json_object(raw[:-1])
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        raise ExperimentRefusal("controller_admission_marker_malformed") from exc
    if set(value) != {
        "schema", "attempt_id", "nonce", "request_sha256", "admission_sha256", "admission_bytes",
    } or value["schema"] != CONTROLLER_ADMISSION_READY_SCHEMA:
        raise ExperimentRefusal("controller_admission_marker_malformed")
    if (
        type(value["attempt_id"]) is not str
        or type(value["nonce"]) is not str
        or _NONCE.fullmatch(value["nonce"] if isinstance(value["nonce"], str) else "") is None
        or type(value["request_sha256"]) is not str
        or _DIGEST.fullmatch(value["request_sha256"] if isinstance(value["request_sha256"], str) else "") is None
        or type(value["admission_sha256"]) is not str
        or _DIGEST.fullmatch(value["admission_sha256"] if isinstance(value["admission_sha256"], str) else "") is None
        or not (type(value["admission_bytes"]) is int and 1 <= value["admission_bytes"] <= MAX_ADMISSION_BYTES)
    ):
        raise ExperimentRefusal("controller_admission_marker_malformed")
    _validate_attempt_id(value["attempt_id"])
    return value


def _mkdir_owned(path: Path, *, allow_existing: bool) -> None:
    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=allow_existing)
        info = os.lstat(path)
    except OSError as exc:
        raise ExperimentRefusal("bridge_directory") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ExperimentRefusal("bridge_directory")


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        written = 0
        while written < len(raw):
            written += os.write(descriptor, raw[written:])
        os.fsync(descriptor)
    except OSError as exc:
        raise ExperimentRefusal("admission_publish") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


__all__ = [
    "ADMISSION_ACK_PREFIX", "CONTROLLER_ADMISSION_NAME", "CONTROLLER_ADMISSION_READY_NAME",
    "CONTROLLER_ADMISSION_READY_SCHEMA", "ComponentExchange",
]
