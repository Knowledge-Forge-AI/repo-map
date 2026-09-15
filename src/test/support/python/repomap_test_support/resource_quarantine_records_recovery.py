"""Interruption recovery helpers for quarantine records."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence

from repomap_test_support.resource_gc_ledger import GcLedger, GcRecord
from repomap_test_support.resource_ledger import (
    ResourceLedger,
    ResourceLedgerError,
    RunIdentity,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
)
from repomap_test_support.resource_retention import RetentionClass
from repomap_test_support.resource_scratch_history import HistoricalGcCandidate
from repomap_test_support.resource_validation import sha256_hex
from repomap_test_support.test_scratch import MANIFEST_SCHEMA


def _owner():
    from repomap_test_support import resource_quarantine_records

    return resource_quarantine_records


def _recover_intent(
    scratch_root: Path,
    registry: ClaimRegistry,
    ledger: GcLedger,
    intent: GcRecord,
    records: Sequence[GcRecord],
    counts: dict[str, int],
    now_seconds: int,
) -> None:
    owner = _owner()
    run_id = intent.payload["run_id"]
    source = scratch_root / "r" / run_id
    quarantine = scratch_root / ".quarantine" / registry.project / run_id
    source_present = source.exists() and not source.is_symlink()
    quarantine_present = quarantine.exists() and not quarantine.is_symlink()
    if source_present and not quarantine_present:
        record_path = ledger.quarantine_record_path(run_id)
        if record_path.is_file():
            restore_intent = owner._restore_intent_for_record(
                records, run_id, owner.read_quarantine_record(record_path)
            )
            restore_completion = (
                owner._restore_completion_for_intent(records, restore_intent.record_id)
                if restore_intent is not None
                else None
            )
            if restore_intent is None or restore_completion is None:
                owner._ambiguous(
                    ledger,
                    intent,
                    "restored_source_with_open_record",
                    counts,
                    now_seconds,
                )
                counts["ambiguous_evidence_conflict"] += 1
                return
            owner._remove_completed_restore_record(
                record_path,
                owner.read_quarantine_record(record_path),
                restore_completion,
                restore_intent,
            )
        counts["no_mutation"] += 1
        owner._append_once(
            ledger,
            "recovered_no_mutation",
            {"run_id": run_id, "intent_record_id": intent.record_id},
            now_seconds,
        )
        return
    if source_present and quarantine_present:
        owner._ambiguous(ledger, intent, "both_present", counts, now_seconds)
        counts["ambiguous_both_present"] += 1
        return
    if not source_present and not quarantine_present:
        owner._ambiguous(ledger, intent, "neither_present", counts, now_seconds)
        counts["ambiguous_neither_present"] += 1
        return
    metadata = quarantine.stat(follow_symlinks=False)
    if (metadata.st_dev, metadata.st_ino) != (
        intent.payload["source_device"], intent.payload["source_inode"]
    ):
        owner._ambiguous(ledger, intent, "identity_changed", counts, now_seconds)
        counts["ambiguous_evidence_conflict"] += 1
        return
    if (registry.root / f"{run_id}.claim.json").exists():
        counts["claim_recovery_required"] += 1
        owner._append_once(
            ledger,
            "recovery_claim_required",
            {"run_id": run_id, "intent_record_id": intent.record_id},
            now_seconds,
        )
        return
    record_path = ledger.quarantine_record_path(run_id)
    finalization = owner._finalization_record(records, run_id)
    if finalization is not None and not record_path.is_file():
        owner._ambiguous(ledger, intent, "ledger_event_without_record", counts, now_seconds)
        counts["ambiguous_evidence_conflict"] += 1
        return
    completion = owner._completion_for_intent(records, intent.record_id)
    if record_path.is_file():
        record = owner.read_quarantine_record(record_path)
        if not owner._record_matches_intent(record, intent, metadata, ledger.pass_id):
            owner._ambiguous(ledger, intent, "record_identity_conflict", counts, now_seconds)
            counts["ambiguous_evidence_conflict"] += 1
            return
        if finalization is None:
            counts["quarantined_needs_ledger_finalization"] += 1
            ledger.append(
                "recovered_record_finalization",
                {"run_id": run_id, "quarantine_record_id": record["quarantine_record_id"]},
                now_seconds=now_seconds,
            )
        else:
            counts["quarantined_complete"] += 1
        return
    counts["quarantined_needs_record_finalization"] += 1
    mode = "recovered_after_rename_completion"
    if completion is None:
        completion = ledger.append(
            "recovered_completion",
            {"run_id": run_id, "intent_record_id": intent.record_id},
            now_seconds=now_seconds,
        )
        mode = "recovered_before_rename_completion"
    try:
        candidate = owner._recovery_candidate(source, quarantine, intent, registry.project)
        owner.write_quarantine_record(
            ledger,
            candidate,
            claim_record_id=intent.payload["claim_record_id"],
            pass_id=ledger.pass_id,
            quarantined_at_seconds=now_seconds,
            quarantine_device=metadata.st_dev,
            quarantine_inode=metadata.st_ino,
            completion_record_id=completion.record_id,
            intent_record_id=intent.record_id,
            finalization_mode=mode,
        )
    except owner.QuarantineError:
        counts["quarantined_needs_record_finalization"] -= 1
        counts["ambiguous_evidence_conflict"] += 1
        owner._ambiguous(
            ledger, intent, "recovery_authority_incomplete", counts, now_seconds
        )


def _recovery_candidate(
    source: Path,
    quarantine: Path,
    intent: GcRecord,
    project: str,
) -> HistoricalGcCandidate:
    owner = _owner()
    manifest_path = quarantine / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise owner.QuarantineError("recovery manifest is unavailable")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            type(manifest) is not dict
            or manifest.get("schema") != MANIFEST_SCHEMA
            or manifest.get("project") != project
            or manifest.get("run_id") != intent.payload["run_id"]
            or Path(manifest.get("physical_run_root", "")) != source
        ):
            raise ValueError("recovery manifest identity mismatch")
        ResourceLedger.open(
            quarantine / "resource-ledger.json",
            RunIdentity(project, manifest["phase"], manifest["run_id"]),
        )
    except (OSError, ValueError, ResourceLedgerError) as error:
        raise owner.QuarantineError("recovery authority is incomplete") from error
    return HistoricalGcCandidate(
        manifest["run_id"],
        manifest["phase"],
        source,
        intent.payload["source_device"],
        intent.payload["source_inode"],
        0,
        0,
        0,
        RetentionClass.SUCCESSFUL_EVIDENCE,
        False,
    )


def _empty_recovery_counts() -> dict[str, int]:
    return {
        "no_mutation": 0,
        "quarantined_complete": 0,
        "quarantined_needs_record_finalization": 0,
        "quarantined_needs_ledger_finalization": 0,
        "claim_recovery_required": 0,
        "ambiguous_both_present": 0,
        "ambiguous_neither_present": 0,
        "ambiguous_evidence_conflict": 0,
        "operator_attention_required": 0,
    }


def _classify_unrecorded_quarantine(
    scratch_root: Path,
    registry: ClaimRegistry,
    ledger: GcLedger,
    intents: Sequence[GcRecord],
    records: Sequence[GcRecord],
    counts: dict[str, int],
    now_seconds: int,
) -> None:
    owner = _owner()
    known = {record.payload.get("run_id") for record in intents}
    quarantine_root = scratch_root / ".quarantine" / registry.project
    if not quarantine_root.exists() or quarantine_root.is_symlink():
        return
    for entry in quarantine_root.iterdir():
        if entry.name in known:
            continue
        counts["ambiguous_evidence_conflict"] += 1
        counts["operator_attention_required"] += 1
        owner._append_once(
            ledger,
            "recovery_ambiguous",
            {"category": "unrecorded_quarantine_entry"},
            now_seconds,
        )


def _ambiguous(
    ledger: GcLedger,
    intent: GcRecord,
    category: str,
    counts: dict[str, int],
    now_seconds: int,
) -> None:
    owner = _owner()
    counts["operator_attention_required"] += 1
    owner._append_once(
        ledger,
        "recovery_ambiguous",
        {"category": category, "intent_record_id": intent.record_id},
        now_seconds,
    )


def _append_once(
    ledger: GcLedger,
    event: str,
    payload: dict[str, object],
    now_seconds: int,
) -> GcRecord | None:
    for record in ledger.records():
        if record.event == event and record.payload == payload:
            return record
    return ledger.append(event, payload, now_seconds=now_seconds)


def _completion_for_intent(records: Sequence[GcRecord], intent_id: str) -> GcRecord | None:
    return next(
        (
            record for record in records
            if record.event in {"rename_completion", "recovered_completion"}
            and record.payload.get("intent_record_id") == intent_id
        ),
        None,
    )


def _restore_intent_for_record(
    records: Sequence[GcRecord],
    run_id: str,
    record: dict[str, object],
) -> GcRecord | None:
    return next(
        (
            entry
            for entry in reversed(records)
            if entry.event == "restore_intent"
            and entry.payload.get("run_id") == run_id
            and entry.payload.get("quarantine_record_id")
            == record["quarantine_record_id"]
        ),
        None,
    )


def _restore_completion_for_intent(
    records: Sequence[GcRecord], intent_id: str
) -> GcRecord | None:
    return next(
        (
            entry
            for entry in records
            if entry.event == "restore_completion"
            and entry.payload.get("intent_record_id") == intent_id
        ),
        None,
    )


def _remove_completed_restore_record(
    path: Path,
    record: dict[str, object],
    completion: GcRecord,
    intent: GcRecord,
) -> None:
    owner = _owner()
    if (
        completion.event != "restore_completion"
        or completion.payload.get("intent_record_id") != intent.record_id
        or intent.event != "restore_intent"
        or intent.payload.get("quarantine_record_id")
        != record["quarantine_record_id"]
    ):
        raise owner.QuarantineError("restore completion authority is invalid")
    try:
        readback = owner.read_quarantine_record(path)
        if readback["quarantine_record_id"] != record["quarantine_record_id"]:
            raise owner.QuarantineError("restore record identity changed")
        path.unlink()
    except OSError as error:
        raise owner.QuarantineError("completed restore record cleanup failed") from error


def _finalization_record(records: Sequence[GcRecord], run_id: str) -> GcRecord | None:
    return next(
        (
            record for record in records
            if record.event in {"quarantine_record", "recovered_record_finalization"}
            and record.payload.get("run_id") == run_id
        ),
        None,
    )


def _ledger_finalized(records: Sequence[GcRecord], run_id: str, record_id: str) -> bool:
    return any(
        record.event in {"quarantine_record", "recovered_record_finalization"}
        and record.payload.get("run_id") == run_id
        and record.payload.get("quarantine_record_id") == record_id
        for record in records
    )


def _record_matches_intent(
    record: dict[str, object],
    intent: GcRecord,
    metadata: os.stat_result,
    pass_id: str,
) -> bool:
    return (
        record["run_id"] == intent.payload["run_id"]
        and record["original_device"] == intent.payload["source_device"]
        and record["original_inode"] == intent.payload["source_inode"]
        and record["quarantine_device"] == metadata.st_dev
        and record["quarantine_inode"] == metadata.st_ino
        and record["gc_pass_id"] == pass_id
    )


def _intent_for_completion(records: Sequence[GcRecord], completion_id: str) -> str:
    owner = _owner()
    completion = next(
        (record for record in records if record.record_id == completion_id), None
    )
    if completion is None or completion.event not in {
        "rename_completion", "recovered_completion"
    }:
        raise owner.QuarantineError("quarantine completion authority is invalid")
    return sha256_hex(completion.payload.get("intent_record_id"), "intent record id")
