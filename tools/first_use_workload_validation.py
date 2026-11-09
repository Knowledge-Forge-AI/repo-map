"""Closed per-action fact shapes (contract section 8).

Shape validation proves only that each fact object has exactly its declared
keys and well-typed, bounded, path-free values. Nulls are admitted for witness
fields so that reconciliation can classify a missing witness as
``witness_missing`` instead of hiding it inside ``malformed``. Truth of a value
is a separate reconciliation rule.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from first_use_workload_census import valid_relative
from first_use_workload_domains import (
    ALIASES, FACT_BACKENDS, INIT_ACTIONS, LEXICAL_ACTIONS, MAX_LEFTOVERS, MAX_LOCATION_REFS,
    MAX_REF_BYTES, PACK_ACTIONS, REFRESH_ACTIONS, REFUSAL_ACTIONS, REFUSAL_CODES,
    UNRESOLVED_ALIAS, WorkloadError,
)
from first_use_workload_encoding import closed, is_count, is_hex64, require
from first_use_workload_pins import validate_pin
from first_use_workload_recipe_shapes import RecipeStep

TOKEN = re.compile(r"[a-z0-9_:\-]{1,64}\Z")
FACT_KEYS: dict[str, tuple[str, ...]] = {
    "census": ("C", "S", "aliases", "files", "generation", "inventory_sha256"),
    "init": ("backend", "initialized"),
    "plan": ("inventory_bytes", "inventory_files", "planned_min_read_bytes"),
    "refresh": (
        "attempt_root_fresh", "inventory_sha256", "manifest_bytes", "outcome", "pin_after",
        "pin_before", "preparation_pin",
    ),
    "refusal": ("code", "pin_after", "pin_before"),
    "pack": (
        "canary_free", "encoded_bytes", "investigation_supported", "max_bytes",
        "observed_locations", "reason", "status",
    ),
    "lexical": ("hits", "observed_locations", "result", "revoked_generations", "unavailable_reason"),
    "snapshot": (
        "backend", "incumbent_snapshot_sha256", "inventory_sha256", "manifest_snapshot_sha256",
    ),
    "cleanup": ("forbidden_events", "leftovers", "shim_invocations"),
}


def fact_class(action: str) -> str:
    if action == "census_verify":
        return "census"
    if action in INIT_ACTIONS:
        return "init"
    if action == "sealing_plan":
        return "plan"
    if action in REFRESH_ACTIONS:
        return "refresh"
    if action in REFUSAL_ACTIONS:
        return "refusal"
    if action in PACK_ACTIONS:
        return "pack"
    if action in LEXICAL_ACTIONS:
        return "lexical"
    if action == "snapshot_equivalence":
        return "snapshot"
    if action == "cleanup":
        return "cleanup"
    raise WorkloadError("invalid_domain")


def _nullable(value: object, predicate: Any) -> bool:
    return value is None or bool(predicate(value))


def _token(value: object) -> bool:
    return type(value) is str and TOKEN.fullmatch(value) is not None


def _ref_ok(alias: object, rel: object) -> bool:
    return (
        (alias in ALIASES or alias == UNRESOLVED_ALIAS)
        and valid_relative(rel)
        and isinstance(rel, str)
        and len(rel.encode("utf-8")) <= MAX_REF_BYTES
    )


def _refs(raw: object, *, tags: Sequence[str] | None) -> list[list[str]]:
    require(type(raw) is list, "malformed")
    assert isinstance(raw, list)
    width = 2 if tags is None else 3
    for item in raw:
        require(type(item) is list and len(item) == width, "malformed")
        if tags is not None:
            require(item[0] in tags)
        require(_ref_ok(item[-2], item[-1]))
    require(raw == sorted(raw) and len({tuple(item) for item in raw}) == len(raw), "not_canonical")
    return raw


def _tagged(raw: object, tags: Sequence[str], predicate: Any) -> None:
    require(type(raw) is list, "malformed")
    assert isinstance(raw, list)
    seen = []
    for item in raw:
        require(type(item) is list and len(item) == 2, "malformed")
        require(item[0] in tags and predicate(item[1]))
        seen.append(item[0])
    require(seen == sorted(set(seen)), "not_canonical")


def _one(kind: str, raw: object, step: RecipeStep) -> dict[str, Any]:
    facts = closed(raw, FACT_KEYS[kind])
    if kind == "census":
        require(facts["aliases"] == list(step.aliases))
        require(all(_nullable(facts[key], is_count) for key in ("C", "S", "files", "generation")))
        require(_nullable(facts["inventory_sha256"], is_hex64))
    elif kind == "init":
        require(facts["backend"] in FACT_BACKENDS)
        require(_nullable(facts["initialized"], lambda v: type(v) is bool))
    elif kind == "plan":
        require(all(_nullable(facts[key], is_count) for key in FACT_KEYS["plan"]))
    elif kind == "refresh":
        require(_nullable(facts["attempt_root_fresh"], lambda v: type(v) is bool))
        require(_nullable(facts["inventory_sha256"], is_hex64))
        require(_nullable(facts["manifest_bytes"], is_count) and _nullable(facts["outcome"], _token))
        for key in ("pin_after", "pin_before", "preparation_pin"):
            validate_pin(facts[key])
    elif kind == "refusal":
        require(_nullable(facts["code"], lambda v: v in REFUSAL_CODES))
        validate_pin(facts["pin_before"])
        validate_pin(facts["pin_after"])
    elif kind == "pack":
        tags = [item.tag for item in step.packs]
        _tagged(facts["status"], tags, _token)
        _tagged(facts["reason"], tags, lambda v: _nullable(v, _token))
        _tagged(facts["encoded_bytes"], tags, is_count)
        _refs(facts["observed_locations"], tags=tags)
        require(_nullable(facts["canary_free"], lambda v: type(v) is bool))
        require(_nullable(facts["investigation_supported"], lambda v: type(v) is bool))
        require(_nullable(facts["max_bytes"], is_count))
    elif kind == "lexical":
        _refs(facts["observed_locations"], tags=None)
        require(_nullable(facts["hits"], is_count) and _nullable(facts["revoked_generations"], is_count))
        require(_nullable(facts["result"], _token) and _nullable(facts["unavailable_reason"], _token))
    elif kind == "snapshot":
        require(facts["backend"] in FACT_BACKENDS)
        for key in ("incumbent_snapshot_sha256", "inventory_sha256", "manifest_snapshot_sha256"):
            require(_nullable(facts[key], is_hex64))
    else:
        leftovers = facts["leftovers"]
        require(type(leftovers) is list and len(leftovers) <= MAX_LEFTOVERS, "malformed")
        require(all(_token(item) or (type(item) is str and _safe_name(item)) for item in leftovers))
        require(_nullable(facts["forbidden_events"], is_count))
        require(_nullable(facts["shim_invocations"], is_count))
    return facts


def _safe_name(name: str) -> bool:
    return 0 < len(name.encode("utf-8")) <= MAX_REF_BYTES and "/" not in name and name.isprintable()


def fact_objects(step: RecipeStep, raw: object) -> list[tuple[str | None, dict[str, Any]]]:
    """Validate ``facts`` and return ``(backend, object)`` pairs; null means none."""
    if raw is None:
        return []
    kind = fact_class(step.action)
    if not step.fact_backends:
        return [(None, _one(kind, raw, step))]
    container = closed(raw, step.fact_backends)
    return [(backend, _one(kind, container[backend], step)) for backend in step.fact_backends]


def location_count(pairs: Sequence[tuple[str | None, dict[str, Any]]]) -> int:
    return sum(len(facts.get("observed_locations", ())) for _backend, facts in pairs)


def check_location_bound(pairs: Sequence[tuple[str | None, dict[str, Any]]]) -> None:
    if location_count(pairs) > MAX_LOCATION_REFS:
        raise WorkloadError("unbounded")


__all__ = [
    "FACT_KEYS", "TOKEN", "check_location_bound", "fact_class", "fact_objects", "location_count",
]
