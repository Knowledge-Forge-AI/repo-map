"""Closed source audits, per-role metrics and aggregate component admission."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from common_lore_index.extractors.rust_pilot.controller import RustPilotController
    from common_lore_index.extractors.rust_pilot.docker_boundary import ResidueSnapshot

NAMES = ("containers", "parses", "commands", "builds", "pulls", "images", "volumes")


def component_accounting(native: Mapping[str, Any]) -> dict[str, Any]:
    """Sum independent run counts without converting unknowns to zero."""
    groups: dict[str, Any] = {"source_controller": native["counters"],
                               "containment": native["containment"]["counters"]}
    for name, scenario in native["preflights"].items():
        if not isinstance(name, str) or not isinstance(scenario, Mapping) or scenario.get("passed") is not True:
            raise ValueError("unproven_metric_group")
        groups["preflight:" + name] = scenario["counters"]
    totals = {}
    for name in NAMES:
        rows = []
        for group in groups.values():
            if not isinstance(group, Mapping) or not isinstance(group.get(name), Mapping):
                raise ValueError("metric_group_shape")
            row = group[name]
            value = row.get("value")
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("metric_value_shape")
            if type(row.get("cross_checked")) is not bool or row.get("basis") != "journal-derived":
                raise ValueError("metric_basis_shape")
            rows.append(row)
        known = all(row["value"] is not None for row in rows)
        totals[name] = {"value": sum(row["value"] for row in rows) if known else None,
                        "basis": "sum-of-role-journal-derived-counters",
                        "cross_checked": known and all(row["cross_checked"] for row in rows),
                        "scope": "all_rust_component_owned_run_groups",
                        "unavailable_reason": None if known else "one_or_more_role_counters_unobservable"}
    return {"groups": groups, "totals": totals,
            "container_and_parse_unit": "command_attempts; successful_native_admission_is_separate"}


class AccountingGap(ValueError):
    """Closed aggregate admission refusal, with inert diagnostic evidence."""

    code = "aggregate_accounting_unproven"

    def __init__(self, evidence: Mapping[str, Any] | None = None) -> None:
        super().__init__(self.code)
        self.evidence = dict(evidence or {})


def require_component_accounting(native: Mapping[str, Any]) -> dict[str, Any]:
    accounting = component_accounting(native)
    totals = accounting["totals"]
    if (any(type(totals[name]["value"]) is not int or totals[name]["value"] < 0
            or totals[name]["cross_checked"] is not True for name in NAMES)
            or any(totals[name]["value"] != 0 for name in ("builds", "pulls", "images", "volumes"))):
        raise AccountingGap({"accounting": accounting})
    return accounting


def refusal_accounting(raw: Mapping[str, Any], source_journal: Sequence[tuple[str, ...]],
                       observer_journal: Sequence[tuple[str, ...]], before: ResidueSnapshot,
                       after: ResidueSnapshot, run_id: str) -> dict[str, Any]:
    """Cross-check a no-create refusal without rewriting its raw audit."""

    version = ("version", "--format", "{{json .Server}}")
    queries = (("image", "ls", "-q", "--no-trunc"), ("volume", "ls", "-q"),
               ("container", "ls", "-a", "-q", "--no-trunc", "--filter",
                "label=org.repomap.rust-pilot.run=" + run_id))
    if (any(not isinstance(raw.get(name), Mapping) for name in NAMES)
            or any(type(raw[name].get("value")) is not int for name in ("containers", "parses", "commands"))
            or tuple(source_journal) not in ((), (version,))
            or tuple(observer_journal) != queries + queries
            or before != after or before.labelled or after.labelled
            or any(raw.get(name, {}).get("value") != 0 for name in ("containers", "parses"))
            or raw.get("commands", {}).get("value") != len(source_journal)):
        raise AccountingGap()
    values = {"containers": 0, "parses": 0,
              "commands": len(source_journal) + len(observer_journal)}
    return {name: {"value": values.get(name, 0), "basis": "journal-derived", "cross_checked": True,
                   "scope": "refusal_controller_and_resource_observer_client_invocations_attempted",
                   "cross_check_method": "closed_read_only_journals_and_resource_snapshots"}
            for name in NAMES}


class AuditGap(RuntimeError):
    def __init__(self, code: str, evidence: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code, self.evidence = code, evidence


def audit_snapshot(controller: RustPilotController, source_paths: Sequence[str],
           fixture: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = controller.audit_snapshot()
    if not isinstance(snapshot, Mapping) or set(snapshot) != {"run_id", "files", "receipts", "residue", "counters"}:
        raise AuditGap("audit_snapshot_shape")
    files, receipts = snapshot["files"], snapshot["receipts"]
    residue = snapshot["residue"]
    if (not isinstance(files, Sequence) or isinstance(files, (str, bytes))
            or not isinstance(receipts, Sequence) or isinstance(receipts, (str, bytes))
            or not isinstance(residue, Mapping)
            or residue.get("observed") is not True
            or residue.get("owned_containers_remaining") != 0
            or residue.get("journal_violations") != []
            or residue.get("attribution_basis") != "closed_command_journal_and_inspected_owned_resources"
            or residue.get("attributable_images") != 0
            or residue.get("attributable_volumes") != 0
            or residue.get("global_image_delta") != 0
            or residue.get("global_volume_delta") != 0):
        raise AuditGap("audit_residue_unproven", snapshot)
    if any(not isinstance(row, Mapping) for row in files) or any(
            not isinstance(receipt, Mapping) for receipt in receipts):
        raise AuditGap("audit_record_shape")
    if len(receipts) != len(files):
        raise AuditGap("audit_receipt_cardinality")
    def digest(value: object) -> bool:
        return (isinstance(value, str) and len(value) == 64
                and all(char in "0123456789abcdef" for char in value))
    def receipt_for(identity: str) -> list[Mapping[str, Any]]:
        return [receipt for receipt in receipts if receipt.get("run_id") == identity]
    seen_seq: set[int] = set()
    costs: dict[str, Any] = {}
    executed = 0
    probes = 0
    for row in files:
        seq, value = row.get("seq"), row.get("input_sha256")
        if type(seq) is not int or seq < 0 or seq in seen_seq or not digest(value):
            raise AuditGap("audit_record_identity")
        seen_seq.add(seq)
        role = row.get("invocation_role")
        if role in ("source", "probe"):
            probes += role == "probe"
            cost = row.get("cost")
            required = ("construction_ms", "readback_ms", "parse_ms", "settlement_ms",
                        "readback_bytes", "installed_tree_bytes", "stdout_bytes",
                        "memory_peak_bytes", "memory_peak_reason", "memory_peak_basis",
                        "construction_includes_readback")
            if (not isinstance(cost, Mapping) or row.get("cleanup") != "proven"
                    or any(key not in cost for key in required)
                    or cost["memory_peak_basis"] != "guest_reported"
                    or cost["construction_includes_readback"] is not True
                    or not isinstance(cost["memory_peak_reason"], str)
                    or cost["memory_peak_bytes"] is not None
                    and (type(cost["memory_peak_bytes"]) is not int or cost["memory_peak_bytes"] < 0)
                    or row.get("stdout_bytes") != cost["stdout_bytes"]):
                raise AuditGap("audit_cost_shape")
            measured = ("construction_ms", "readback_ms", "parse_ms", "settlement_ms",
                        "readback_bytes", "installed_tree_bytes", "stdout_bytes")
            if any(type(cost[key]) not in (int, float) or isinstance(cost[key], bool) or cost[key] < 0
                   for key in measured):
                raise AuditGap("audit_cost_unobservable")
            expected = f"{snapshot['run_id']}.probe.{seq}" if role == "probe" else f"{snapshot['run_id']}.{seq}"
            matches = receipt_for(expected)
            observed = matches[0].get("observed") if len(matches) == 1 else None
            if (len(matches) != 1 or matches[0].get("state") != "complete"
                    or matches[0].get("source_sha256") != value
                    or not isinstance(observed, Mapping) or observed.get("verification") != "unverified"):
                raise AuditGap("audit_receipt_binding")
            executed += 1
        elif role is None and "invocation_role" not in row:
            if ("cost" in row or not isinstance(row.get("outcome"), str)
                    or not isinstance(row.get("refusal"), str)):
                raise AuditGap("audit_unexecuted_cost")
            matches = receipt_for(f"{snapshot['run_id']}.{seq}")
            observed = matches[0].get("observed") if len(matches) == 1 else None
            if (len(matches) != 1 or matches[0].get("state") != "refused"
                    or matches[0].get("source_sha256") != value
                    or not isinstance(observed, Mapping) or observed.get("verification") != "refused"):
                raise AuditGap("audit_refusal_binding")
        else:
            raise AuditGap("audit_role_shape")
    if probes != 1:
        raise AuditGap("audit_probe_receipt")
    source_digests = {relative: fixture["files"][relative]["sha256"] for relative in source_paths}
    for relative, expected in source_digests.items():
        rows = [row for row in files if row.get("input_sha256") == expected]
        if len(rows) != 1 or rows[0].get("invocation_role") == "probe":
            raise AuditGap("audit_input_witness")
        costs[relative] = dict(rows[0]["cost"]) if rows[0].get("invocation_role") == "source" else None
    raw = snapshot["counters"]
    names = ("containers", "parses", "builds", "pulls", "images", "volumes", "commands")
    if not isinstance(raw, Mapping) or set(raw) != set(names):
        raise AuditGap("audit_counter_shape")
    counters = {}
    for name in names:
        value = raw[name]
        if (not isinstance(value, Mapping) or value.get("basis") != "journal-derived"
                or value.get("cross_checked") is not True or type(value.get("value")) is not int
                or value["value"] < 0):
            raise AuditGap("audit_counter_unobservable")
        counters[name] = dict(value)
    if (counters["containers"].get("scope") != "create_commands_attempted"
            or counters["parses"].get("scope") != "fixed_parse_exec_commands_attempted"
            or counters["commands"].get("scope") != "controller_client_invocations_attempted"):
        raise AuditGap("audit_counter_scope")
    if (counters["containers"]["value"] != executed or counters["parses"]["value"] != executed
            or counters["commands"]["value"] < executed or counters["commands"]["value"] == 0
            or any(counters[name]["value"] != 0 for name in ("builds", "pulls", "images", "volumes"))):
        raise AuditGap("audit_counter_mismatch")
    return dict(snapshot), {"costs": costs, "counters": counters}
