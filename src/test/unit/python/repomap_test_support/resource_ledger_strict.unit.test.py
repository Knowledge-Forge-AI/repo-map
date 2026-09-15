"""TEST-HYGIENE3A red-first contracts for strict ledger authority."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Literal, TypedDict, cast


class RegistrationFlags(TypedDict):
    created_before_run: bool
    creation_observed: bool
    cleanup_required: bool
    retained: bool


class LedgerPayload(TypedDict, total=False):
    schema: str
    created_at_seconds: object
    identity: dict[str, object]
    resources: list[dict[str, object]]
    checkpoints: list[dict[str, object]]
    facts: dict[str, object]
    lifecycle: dict[str, object]
    surprise: int


import pytest

from repomap_test_support.resource_ledger import (
    ResourceKind,
    ResourceLedger,
    ResourceLedgerError,
    RunIdentity,
)
from repomap_test_support.resource_projection import (
    ResourceProjectionError,
    resource_count_projection,
)


def _identity() -> RunIdentity:
    return RunIdentity("repo-map_dev", "TEST-HYGIENE3A", "run1")


def _ledger(tmp_path: Path) -> ResourceLedger:
    return ResourceLedger.create(tmp_path / "ledger.json", _identity())


def _registered_payload(tmp_path: Path) -> tuple[Path, LedgerPayload]:
    ledger = _ledger(tmp_path)
    ledger.register(
        ResourceKind.SCRATCH_DIRECTORY,
        "scratch-1",
        creation_owner="fixture",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=True,
    )
    return ledger.path, json.loads(ledger.path.read_text())


@pytest.mark.parametrize("value", ["false", "true", 0, 1, [], {}, None, object()])
def test_set_fact_requires_exact_boolean(tmp_path, value):
    ledger = _ledger(tmp_path)
    with pytest.raises(ResourceLedgerError, match="exact Boolean"):
        ledger.set_fact("pre_existing_objects_mutated", value)


@pytest.mark.parametrize(
    "field",
    ["created_before_run", "creation_observed", "cleanup_required", "retained"],
)
@pytest.mark.parametrize("value", ["false", 0, 1, [], {}, None])
def test_registration_booleans_require_exact_boolean(
    tmp_path,
    field: Literal["created_before_run", "creation_observed", "cleanup_required", "retained"],
    value,
):
    ledger = _ledger(tmp_path)
    values: RegistrationFlags = {
        "created_before_run": False,
        "creation_observed": True,
        "cleanup_required": True,
        "retained": False,
    }
    values[field] = value
    with pytest.raises(ResourceLedgerError, match="exact Boolean"):
        ledger.register(
            ResourceKind.SCRATCH_DIRECTORY,
            f"scratch-{field}-{type(value).__name__}",
            creation_owner="fixture",
            **values,
        )


@pytest.mark.parametrize(
    "field",
    [
        "created_before_run",
        "creation_observed",
        "cleanup_required",
        "cleanup_attempted",
        "retained",
    ],
)
def test_open_refuses_persisted_non_boolean_resource_fields(tmp_path, field):
    path, payload = _registered_payload(tmp_path)
    payload["resources"][0][field] = "false"
    path.write_text(json.dumps(payload))
    with pytest.raises(ResourceLedgerError, match="invalid"):
        ResourceLedger.open(path, _identity())


@pytest.mark.parametrize(
    "field", ["pre_existing_objects_mutated", "foreign_scratch_runs_mutated"]
)
def test_open_refuses_persisted_non_boolean_facts(tmp_path, field):
    path, payload = _registered_payload(tmp_path)
    payload["facts"][field] = "false"
    path.write_text(json.dumps(payload))
    with pytest.raises(ResourceLedgerError, match="invalid"):
        ResourceLedger.open(path, _identity())


@pytest.mark.parametrize("value", [True, 1.5, -1, "1"])
def test_checkpoint_integer_fields_require_exact_nonnegative_integer(tmp_path, value):
    ledger = _ledger(tmp_path)
    with pytest.raises(ResourceLedgerError, match="nonnegative integer"):
        ledger.add_checkpoint("entry", {"allocated_bytes": value})


@pytest.mark.parametrize("mutation", ["missing", "unknown", "duplicate"])
def test_open_requires_exact_schema_and_unique_resources(tmp_path, mutation):
    path, payload = _registered_payload(tmp_path)
    if mutation == "missing":
        del payload["checkpoints"]
    elif mutation == "unknown":
        payload["surprise"] = 1
    else:
        payload["resources"].append(deepcopy(payload["resources"][0]))
    path.write_text(json.dumps(payload))
    with pytest.raises(ResourceLedgerError, match="invalid"):
        ResourceLedger.open(path, _identity())


def test_host_restoration_requires_two_observed_false_facts(tmp_path):
    ledger = _ledger(tmp_path)
    assert ledger.host_restoration_proved() is False
    ledger.set_fact("pre_existing_objects_mutated", False)
    assert ledger.host_restoration_proved() is False
    ledger.set_fact("foreign_scratch_runs_mutated", False)
    assert ledger.host_restoration_proved() is True


def _invalid_fact_value(value: str) -> bool:
    """Narrow runtime-invalid fact value builder for negative controls."""
    return cast(bool, value)


def test_public_projection_rejects_arbitrary_fact_values(tmp_path):
    ledger = _ledger(tmp_path)
    ledger._facts["pre_existing_objects_mutated"] = _invalid_fact_value("false")
    with pytest.raises(ResourceLedgerError, match="mutation fact"):
        ledger.public_projection()


def test_projection_boundary_rejects_arbitrary_fact_values():
    with pytest.raises(ResourceProjectionError, match="mutation fact"):
        resource_count_projection(
            (), {"pre_existing_objects_mutated": _invalid_fact_value("private-arbitrary-value")}
        )


@pytest.mark.parametrize("mutation", ["resource_missing", "resource_unknown", "identity_unknown"])
def test_open_rejects_unknown_or_missing_nested_fields(tmp_path, mutation):
    path, payload = _registered_payload(tmp_path)
    if mutation == "resource_missing":
        del payload["resources"][0]["creation_owner"]
    elif mutation == "resource_unknown":
        payload["resources"][0]["surprise"] = False
    else:
        payload["identity"]["surprise"] = "value"
    path.write_text(json.dumps(payload))
    with pytest.raises(ResourceLedgerError, match="invalid"):
        ResourceLedger.open(path, _identity())


@pytest.mark.parametrize(
    ("path_parts", "value"),
    [
        (("created_at_seconds",), True),
        (("resources", 0, "size_bytes"), 1.5),
        (("resources", 0, "inode_count"), "1"),
        (("checkpoints",), {}),
        (("facts",), []),
        (("lifecycle", "terminal_at_seconds"), True),
    ],
)
def test_open_rejects_malformed_numeric_and_container_shapes(
    tmp_path, path_parts, value
):
    path, payload = _registered_payload(tmp_path)
    target: object = payload
    for part in path_parts[:-1]:
        if isinstance(target, dict) and isinstance(part, str):
            target = target[part]
        elif isinstance(target, list) and isinstance(part, int):
            target = target[part]
        else:
            raise AssertionError("malformed fixture traversal")
    last = path_parts[-1]
    if isinstance(target, dict) and isinstance(last, str):
        target[last] = value
    elif isinstance(target, list) and isinstance(last, int):
        target[last] = value
    else:
        raise AssertionError("malformed fixture destination")
    path.write_text(json.dumps(payload))
    with pytest.raises(ResourceLedgerError, match="invalid"):
        ResourceLedger.open(path, _identity())


def test_legacy_v1_is_refused_read_only_without_rewrite(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "schema": "repomap-test-resource-ledger-v1",
                "identity": {"project": "repo-map_dev", "phase": "TEST-HYGIENE3A", "run_id": "run1"},
                "resources": [],
                "checkpoints": [],
                "facts": {},
            },
            sort_keys=True,
        )
    )
    path.chmod(0o600)
    before = path.read_bytes()
    with pytest.raises(ResourceLedgerError, match="legacy evidence is ambiguous"):
        ResourceLedger.open(path, _identity())
    assert path.read_bytes() == before


def test_terminal_stamp_uses_injected_time_not_file_mtime(tmp_path):
    ledger = _ledger(tmp_path)
    os.utime(ledger.path, (999, 999))
    lifecycle = ledger.stamp_terminal("passed", 123)
    payload = json.loads(ledger.path.read_text())
    assert lifecycle.terminal_at_seconds == 123
    assert payload["lifecycle"] == {
        "retention_class": "successful-evidence",
        "terminal_at_seconds": 123,
        "terminal_outcome": "passed",
    }


def test_open_rejects_inconsistent_terminal_retention(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.stamp_terminal("passed", 123)
    payload = json.loads(ledger.path.read_text())
    payload["lifecycle"]["retention_class"] = "failed-evidence"
    ledger.path.write_text(json.dumps(payload))

    with pytest.raises(ResourceLedgerError, match="invalid"):
        ResourceLedger.open(ledger.path, _identity())
