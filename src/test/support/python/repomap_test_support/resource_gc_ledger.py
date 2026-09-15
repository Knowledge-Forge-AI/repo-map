"""Private immutable evidence for one quarantine-only maintenance pass."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repomap_test_support.resource_index_records import owner_token, safe_run_id
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    exact_object,
    nonnegative_int,
    sha256_hex,
)


PASS_SCHEMA = "repomap-test-gc-pass-v1"
RECORD_SCHEMA = "repomap-test-gc-ledger-record-v1"
TRIGGERS = frozenset(
    {"operator_requested", "operator_scheduled", "admission_time_soft_watermark"}
)
EVENTS = frozenset(
    {
        "candidate_discovered", "candidate_excluded", "stale_claim_intent",
        "stale_claim_completion", "stale_lock_intent", "stale_lock_completion",
        "rename_intent", "rename_completion", "recovered_no_mutation",
        "recovered_completion", "recovered_record_finalization",
        "recovery_claim_required", "recovery_ambiguous", "quarantine_record",
        "protection_observation", "rename_collision", "restore_intent",
        "restore_collision", "restore_completion", "batch_summary",
        "deletion_protection_observation", "deletion_intent",
        "deletion_barrier", "deletion_progress", "deletion_completion",
        "deleted_tombstone", "protected_restored", "delete_batch_summary",
        "deleted_index_reconciliation_pending",
    }
)


class GcLedgerError(RuntimeError):
    """The private GC ledger is malformed, conflicting, or unavailable."""


@dataclass(frozen=True)
class GcRecord:
    path: Path
    sequence: int
    event: str
    record_id: str
    payload: dict[str, Any]


class GcLedger:
    def __init__(
        self,
        root: Path,
        pass_id: str,
        trigger: str,
        configuration_digest: str,
        maintenance_owner_token: str,
    ) -> None:
        self.root = Path(root)
        self.pass_id = safe_run_id(pass_id)
        self.trigger = _trigger(trigger)
        self.configuration_digest = sha256_hex(
            configuration_digest, "configuration digest"
        )
        self.maintenance_owner_token = owner_token(maintenance_owner_token)
        self.records_root = self.root / "records"
        self.tombstone_root = self.root / "tombstones"
        self.quarantine_root = self.root / "quarantine-records"
        self._next_sequence = 0

    @classmethod
    def create(
        cls,
        scratch_root: Path,
        *,
        project: str,
        pass_id: str,
        trigger: str,
        configuration_digest: str,
        maintenance_owner_token: str,
        now_seconds: int,
    ) -> "GcLedger":
        project = safe_run_id(project)
        pass_id = safe_run_id(pass_id)
        gc_root = Path(scratch_root) / ".gc"
        project_root = gc_root / project
        root = project_root / pass_id
        _private_directory(gc_root, create=True)
        _private_directory(project_root, create=True)
        _private_directory(root, create=True)
        ledger = cls(
            root, pass_id, trigger, configuration_digest, maintenance_owner_token
        )
        for path in (ledger.records_root, ledger.tombstone_root, ledger.quarantine_root):
            _private_directory(path, create=True)
        seed = {
            "schema": PASS_SCHEMA,
            "project": project,
            "pass_id": pass_id,
            "trigger": ledger.trigger,
            "configuration_digest": ledger.configuration_digest,
            "maintenance_owner_token": ledger.maintenance_owner_token,
            "created_at_seconds": nonnegative_int(now_seconds, "pass timestamp"),
        }
        payload = {**seed, "pass_record_id": _record_id(seed)}
        try:
            write_private_json_exclusive(root / "pass.json", payload)
        except (FileExistsError, OSError, PrivateJsonError) as error:
            raise GcLedgerError("GC pass record creation failed") from error
        return ledger

    @classmethod
    def open(cls, root: Path) -> "GcLedger":
        try:
            payload = exact_object(
                read_private_json(Path(root) / "pass.json"),
                {
                    "schema", "project", "pass_id", "trigger", "configuration_digest",
                    "maintenance_owner_token", "created_at_seconds", "pass_record_id",
                },
                "GC pass record",
            )
            if payload["schema"] != PASS_SCHEMA:
                raise HygieneValidationError("unsupported GC pass schema")
            seed = dict(payload)
            record_id = seed.pop("pass_record_id")
            if _record_id(seed) != record_id:
                raise HygieneValidationError("GC pass record integrity mismatch")
            ledger = cls(
                root,
                payload["pass_id"],
                payload["trigger"],
                payload["configuration_digest"],
                payload["maintenance_owner_token"],
            )
            for path in (
                ledger.root, ledger.records_root, ledger.tombstone_root,
                ledger.quarantine_root,
            ):
                _private_directory(path, create=False)
            records = ledger.records()
            ledger._next_sequence = len(records)
            return ledger
        except (OSError, PrivateJsonError, HygieneValidationError) as error:
            raise GcLedgerError("GC pass record is invalid") from error

    def append(self, event: str, payload: dict[str, Any], *, now_seconds: int) -> GcRecord:
        if event not in EVENTS:
            raise GcLedgerError("GC ledger event is not in the closed vocabulary")
        if type(payload) is not dict:
            raise GcLedgerError("GC ledger event payload must be an object")
        sequence = self._next_sequence
        seed = {
            "schema": RECORD_SCHEMA,
            "pass_id": self.pass_id,
            "sequence": sequence,
            "event": event,
            "recorded_at_seconds": nonnegative_int(now_seconds, "record timestamp"),
            "payload": payload,
        }
        record_id = _record_id(seed)
        record_payload = {**seed, "record_id": record_id}
        path = self.records_root / f"{sequence:06d}-{record_id}.json"
        try:
            write_private_json_exclusive(path, record_payload)
        except (FileExistsError, OSError, PrivateJsonError) as error:
            raise GcLedgerError("GC ledger record creation failed") from error
        self._next_sequence += 1
        return GcRecord(path, sequence, event, record_id, dict(payload))

    def records(self) -> tuple[GcRecord, ...]:
        try:
            files = sorted(self.records_root.iterdir(), key=lambda item: item.name)
        except OSError as error:
            raise GcLedgerError("GC ledger record directory is unreadable") from error
        records = []
        for expected, path in enumerate(files):
            try:
                payload = exact_object(
                    read_private_json(path),
                    {
                        "schema", "pass_id", "sequence", "event",
                        "recorded_at_seconds", "payload", "record_id",
                    },
                    "GC ledger record",
                )
                if payload["schema"] != RECORD_SCHEMA or payload["pass_id"] != self.pass_id:
                    raise HygieneValidationError("GC ledger identity mismatch")
                if payload["sequence"] != expected or payload["event"] not in EVENTS:
                    raise HygieneValidationError("GC ledger sequence or event is invalid")
                if type(payload["payload"]) is not dict:
                    raise HygieneValidationError("GC ledger payload is invalid")
                seed = dict(payload)
                record_id = seed.pop("record_id")
                if _record_id(seed) != record_id or path.name != f"{expected:06d}-{record_id}.json":
                    raise HygieneValidationError("GC ledger record integrity mismatch")
                records.append(
                    GcRecord(path, expected, payload["event"], record_id, payload["payload"])
                )
            except (OSError, PrivateJsonError, HygieneValidationError) as error:
                raise GcLedgerError("GC ledger record is invalid") from error
        return tuple(records)

    def tombstone_path(self, kind: str, identity: str) -> Path:
        if kind not in {"claim", "admission-lock"}:
            raise GcLedgerError("tombstone kind is unsupported")
        identity = safe_run_id(identity)
        return self.tombstone_root / f"{kind}-{identity}.json"

    def quarantine_record_path(self, run_id: str) -> Path:
        return self.quarantine_root / f"{safe_run_id(run_id)}.json"


def _trigger(value: str) -> str:
    if value not in TRIGGERS:
        raise GcLedgerError("maintenance trigger is not in the closed vocabulary")
    return value


def _private_directory(path: Path, *, create: bool) -> None:
    if create:
        Path(path).mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = Path(path).stat(follow_symlinks=False)
    if Path(path).is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise GcLedgerError("GC ledger directory identity is unsafe")
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise GcLedgerError("GC ledger directory ownership or mode is unsafe")


def _record_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["GcLedger", "GcLedgerError", "GcRecord", "TRIGGERS"]
