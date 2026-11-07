"""Closed input shapes and command admission for Rust qualification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
import hashlib
import math
import time

from common_lore_index.extractors.contracts.vocabulary import ContractError
from typing import Any

MAX_QUALIFICATION_REPORT_BYTES = 1_048_576
GOLD_METADATA_RESERVE_BYTES = 256 * 1024
MAX_GOLD_COMPARISON_BYTES = MAX_QUALIFICATION_REPORT_BYTES - GOLD_METADATA_RESERVE_BYTES


class ShapeRefused(ValueError):
    pass


def _closed(value: object, fields: str, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(fields.split()):
        raise ShapeRefused(code)
    return value


def source_digests(closure: Mapping[str, Any]) -> dict[str, str]:
    """Read closed, uniquely named source records without path-shaped keys."""
    rows = closure.get("python_digests")
    if not isinstance(rows, list) or not rows:
        raise ShapeRefused("closure_digests")
    result: dict[str, str] = {}
    for value in rows:
        row = _closed(value, "path sha256", "closure_digest_fields")
        path, digest = row["path"], row["sha256"]
        if not isinstance(path, str) or not isinstance(digest, str) or path in result:
            raise ShapeRefused("closure_digest_identity")
        result[path] = digest
    return result


def validate_shape(document: object) -> None:
    """Reject extra fields and bool-as-int values before semantic validation."""
    top = _closed(document, "schema window candidate_binding source_checkpoint sdk closure "
                  "fixture wheels incumbent scenarios navigation budget stopping replacement",
                  "manifest_fields")
    _closed(top["source_checkpoint"], "sha tree", "checkpoint_fields")
    sdk = _closed(top["sdk"], "architecture image_id_binding recipe_sha256 recipe_files profile_sha256",
                  "sdk_fields")
    recipes = sdk["recipe_files"]
    if not isinstance(recipes, Mapping) or set(recipes) != {
            "tools/test_sandbox/Dockerfile", "tools/native_apt_prerequisites.py"}:
        raise ShapeRefused("sdk_recipe_files")
    closure = _closed(top["closure"], "python_paths python_digests guest_digests profile_digests component_lock "
                      "helper_closure_sha256", "closure_fields")
    source_digests(closure)
    _closed(closure["component_lock"], "path sha256", "component_lock_fields")
    _closed(closure["profile_digests"], "amd64 arm64", "profile_digest_fields")
    fixture = _closed(top["fixture"], "root expected_item_claims files", "fixture_fields")
    if type(fixture["expected_item_claims"]) is not int:
        raise ShapeRefused("fixture_claim_count")
    if not isinstance(fixture["files"], Mapping):
        raise ShapeRefused("fixture_files")
    for name, value in fixture["files"].items():
        fields = "bytes sha256" if name.startswith("golds/") else "bytes sha256 gold scenario"
        entry = _closed(value, fields, "fixture_entry_fields")
        if type(entry["bytes"]) is not int or entry["bytes"] <= 0:
            raise ShapeRefused("fixture_bytes")
    if not isinstance(top["wheels"], list):
        raise ShapeRefused("wheels")
    for wheel in top["wheels"]:
        _closed(wheel, "architecture name state url bytes sha256", "wheel_fields")
    _closed(top["incumbent"], "semantics report_path sha256 schema files_key items_key "
            "input_digests_key navigation_key graph_quality_key discovery_ms_key fixture_digests",
            "incumbent_fields")
    _closed(top["scenarios"], "arm64 amd64 t1", "scenario_fields")
    navigation = _closed(top["navigation"], "incumbent_key tasks", "navigation_fields")
    tasks = navigation["tasks"]
    if not isinstance(tasks, list) or len(tasks) != 5:
        raise ShapeRefused("navigation_task_count")
    namespaces, keys = set(), set()
    for task in tasks:
        row = _closed(task, "fixture name namespace incumbent_key", "navigation_task_fields")
        if any(not isinstance(value, str) or not value for value in row.values()):
            raise ShapeRefused("navigation_task_shape")
        namespaces.add(row["namespace"])
        keys.add(row["incumbent_key"])
    if namespaces != {"rust.function", "rust.trait", "rust.impl", "rust.macro", "rust.module"} or len(keys) != 5:
        raise ShapeRefused("navigation_categories")
    budget = _closed(top["budget"], "commands amd_wheel_transfers arm_wheel_transfers redirects retries", "budget_fields")
    for name, expected in (("commands", 1), ("amd_wheel_transfers", 2), ("arm_wheel_transfers", 0)):
        if type(budget[name]) is not int or budget[name] != expected:
            raise ShapeRefused("budget")
    if budget["redirects"] is not False or budget["retries"] is not False:
        raise ShapeRefused("budget")


def check_work_report_paths(work_dir: Path, report_dir: Path) -> None:
    """No acquired bytes or work cleanup may intersect uploaded evidence."""

    work, report = work_dir.resolve(), report_dir.resolve()
    if work.is_relative_to(report) or report.is_relative_to(work):
        raise ContractError("qualification_paths_overlap")


WORK_WINDOW_SECONDS = 1200.0


def command_work_deadline(deadline: float | None = None) -> float:
    """A supplied absolute cutoff can never extend a new bounded window."""

    maximum = time.monotonic() + WORK_WINDOW_SECONDS
    if deadline is None:
        return maximum
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ContractError("invalid_work_deadline")
    return min(deadline, maximum)


def require_work_deadline(deadline: float | None) -> None:
    if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
        raise ContractError("invalid_work_deadline")
    if deadline is not None and time.monotonic() >= deadline:
        raise ContractError("internal_deadline_exceeded")


def _value(item: object, name: str, default: Any = None) -> Any:
    return getattr(item, name, default)


def _claim(item: object) -> dict[str, Any]:
    metadata = dict(_value(item, "metadata", {}))
    return {"end_byte": metadata["end_byte"], "end_line": _value(item, "end_line"),
            "item_kind": metadata["item_kind"], "name": _value(item, "name"),
            "namespace": metadata["namespace"], "pointer": metadata["pointer"],
            "start_byte": metadata["start_byte"], "start_line": _value(item, "start_line"),
            "usable_scope": metadata["usable_scope"]}


def gold_document(relative: str, data: bytes, observations: Sequence[object],
                  fallback: str, scenario: str) -> dict[str, Any]:
    """Project the fixed public-fixture document; never include runtime text."""
    parse = next((item for item in observations if _value(item, "kind") == "rust.parse"), None)
    metadata = dict(_value(parse, "metadata", {})) if parse is not None else {}
    unsupported = []
    for item in observations:
        if _value(item, "kind") == "rust.unsupported":
            details = dict(_value(item, "metadata", {}))
            unsupported.append({key: details[key] for key in ("construct", "count", "scope_pointer")})
    return {
        "build_script_name": relative.rsplit("/", 1)[-1] == "build.rs",
        "completeness": metadata.get("completeness", "none"), "fixture": relative,
        "input_bytes": len(data), "input_sha256": hashlib.sha256(data).hexdigest(),
        "item_list": metadata.get("item_list"),
        "items": [_claim(item) for item in observations if _value(item, "kind") == "rust.item"],
        "line_count": metadata.get("line_count", data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)),
        "outcome": metadata.get("outcome", fallback), "scenarios": [scenario],
        "schema": "cloe-rust-pilot-gold-v1", "unsupported": unsupported,
    }
