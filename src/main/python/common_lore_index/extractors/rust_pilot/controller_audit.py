"""Sanitized controller audit adaptation; these records never authorize claims."""

from __future__ import annotations

import re
import copy
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any

from common_lore_index.extractors.contracts.receipt_schema import Receipt
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot import receipts
from common_lore_index.extractors.rust_pilot.docker_boundary import (
    DockerBoundary, ResidueSnapshot, RUNTIME_ROOT, journal_violations,
)
from common_lore_index.extractors.rust_pilot.selection import SelectionRecord
from common_lore_index.extractors.rust_pilot.witness_state import FileRecord

_SHA256 = re.compile(r"[0-9a-f]{64}")
SELECTION_REFUSALS = {
    "input_not_utf8": "dialect_unsupported", "resource_bound_exceeded": "resource_bound_exceeded",
    "selection_refused": "inadmissible_effects", "source_changed": "witness_unavailable",
}


@dataclass(frozen=True)
class RunSummary:
    """Informational process outcome, never admission authority."""

    run_id: str
    run_outcome: str
    refusal: str | None
    file_outcomes: tuple[tuple[str, str], ...]


def audit_snapshot(run_id: str, files: Sequence[dict[str, Any]], receipts_seen: Sequence[Receipt],
                   residue: dict[str, Any], boundary: DockerBoundary) -> dict[str, Any]:
    """Inert copies of diagnostic evidence; no callbacks or claim authority."""

    checked = (residue.get("observed") is True and not residue.get("journal_violations")
               and residue.get("attribution_basis") == "closed_command_journal_and_inspected_owned_resources")
    counts = {"containers": sum(row[:1] == ("create",) for row in boundary.journal),
              "parses": sum(row[:1] == ("exec",) and row[-1:] == (f"{RUNTIME_ROOT}/helper/parse_helper.py",)
                            for row in boundary.journal)}
    counters = {name: {"value": value, "basis": "journal-derived", "cross_checked": checked}
                for name, value in counts.items()}
    counters["containers"]["scope"] = "create_commands_attempted"
    counters["parses"]["scope"] = "fixed_parse_exec_commands_attempted"
    counters["commands"] = {"value": len(boundary.journal), "basis": "journal-derived",
                             "cross_checked": True, "scope": "controller_client_invocations_attempted"}
    counters.update({name: {"value": 0 if checked else None, "basis": "journal-derived",
                            "cross_checked": checked} for name in ("builds", "pulls", "images", "volumes")})
    return copy.deepcopy({"run_id": run_id, "files": list(files), "residue": residue,
                          "receipts": [receipt.to_dict() for receipt in receipts_seen], "counters": counters})


def observe_residue(boundary: DockerBoundary, run_id: str, start: ResidueSnapshot | None,
                    owned: Sequence[str]) -> tuple[dict[str, Any], bool]:
    try:
        end = boundary.snapshot(run_id)
    except ContractError:
        return {"observed": False}, False
    violations = journal_violations(boundary.journal)
    clear = not owned and not end.labelled
    return {
        "observed": True, "owned_containers_remaining": len(end.labelled) + len(owned),
        "journal_violations": list(violations),
        "attributable_images": 0 if not violations else None,
        "attributable_volumes": 0 if not violations else None,
        "attribution_basis": "closed_command_journal_and_inspected_owned_resources",
        "global_image_delta": None if start is None else len(end.images ^ start.images),
        "global_volume_delta": None if start is None else len(end.volumes ^ start.volumes),
    }, start is not None and clear and not violations


def refused_selection(run_id: str, seq: int, selection: SelectionRecord,
                      profile_sha256: str | None) -> tuple[Receipt, dict[str, Any]]:
    code = SELECTION_REFUSALS[selection.outcome]
    source = (selection.discovery_sha256 if _SHA256.fullmatch(selection.discovery_sha256)
              else receipts.run_source_sha256([]))
    receipt = receipts.refusal_receipt(
        run_id=run_id, seq=seq, source_sha256=source, profile_sha256=profile_sha256, code=code,
        resource_events=("input_bound",) if selection.outcome == "resource_bound_exceeded" else ())
    return receipt, {"seq": seq, "input_sha256": source, "outcome": selection.outcome, "refusal": code}


def attempted_file(run_id: str, record: FileRecord, profile_sha256: str, *,
                   constructed: bool, probe: bool = False) -> tuple[Receipt, dict[str, Any]]:
    identity = run_id + ".probe" if probe else run_id
    if constructed:
        receipt = receipts.attempt_receipt(
            run_id=identity, seq=record.seq, input_sha256=record.input_sha256,
            profile_sha256=profile_sha256, artifact_sha256=record.readback_digest,
            outcome=record.outcome, completeness=record.completeness, achieved=record.achieved,
            resource_events=record.events, exit_status=record.exit_status,
            cleanup_proven=record.absence_proven)
    else:
        receipt = receipts.refusal_receipt(
            run_id=identity, seq=record.seq, source_sha256=record.input_sha256,
            profile_sha256=profile_sha256, code="inadmissible_effects",
            cleanup="proven" if record.absence_proven else "incomplete")
    cost: dict[str, Any] = {name + "_ms": round(record.timings[name] * 1000)
                            if name in record.timings else None
                            for name in ("construction", "readback", "parse", "settlement")}
    cost.update(readback_bytes=record.readback_bytes, installed_tree_bytes=record.installed_bytes,
                stdout_bytes=len(record.stdout), memory_peak_bytes=record.memory_peak,
                memory_peak_basis="guest_reported", memory_peak_reason=record.memory_peak_reason)
    cost["construction_includes_readback"] = True
    return receipt, {
        "seq": record.seq, "invocation_role": "probe" if probe else "source",
        "input_sha256": record.input_sha256, "outcome": record.outcome,
        "completeness": record.completeness, "stdout_bytes": len(record.stdout),
        "diagnostic": "diagnostic_present" if record.stderr_bytes else "none",
        "diagnostic_sha256": record.stderr_sha256,
        "resource_stage": record.resource_stage,
        "cleanup": "proven" if record.absence_proven else "incomplete", "cost": cost,
    }
