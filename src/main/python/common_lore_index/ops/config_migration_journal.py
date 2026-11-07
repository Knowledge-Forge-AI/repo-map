"""CLOE migration journal schema and backend-neutral effective-configuration digest (ADR 0114)."""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import tomllib
from typing import Any, Sequence

from common_lore_index.ops.config_helpers import unknown_file_field_diagnostics, unknown_top_level_diagnostics
from common_lore_index.ops.config_layout import plan_cloe_config_filenames, portable_config_name
from common_lore_index.ops.config_loading import validate_file_schema
from common_lore_index.ops.config_loading_records import merge_ops_config_payloads
from common_lore_index.ops.config_migration_fs import (
    JOURNAL_NAME, JOURNAL_TEMP_NAME, MAX_CONFIG_FILES, MAX_FILE_BYTES, MAX_JOURNAL_BYTES, MAX_TOTAL_BYTES,
    Home, MigrationRefusal, owned_regular, valid_name,
)
from common_lore_index.ops.config_records import OpsConfigError
from common_lore_index.ops.config_storage import parse_storage_section

JOURNAL_SCHEMA = "cloe-config-migration-journal-v1"
STATES = ("preparing", "prepared", "publishing", "applied", "rolling-back", "rolled-back", "finalizing")
_JOURNAL_KEYS = frozenset((
    "schema", "operation_id", "state", "home", "source_format", "source_order", "proposed_order",
    "effective_sha256", "entries",
))
_ENTRY_KEYS = frozenset((
    "index", "source", "target", "layer", "size", "sha256", "mode", "dev", "ino", "restored_dev", "restored_ino",
))
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX32 = re.compile(r"[0-9a-f]{32}")


def _toml_value(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return {"toml": type(value).__name__, "value": value.isoformat()}
    raise TypeError("unsupported configuration value")


def effective_sha256(named_bytes: Sequence[tuple[str, bytes]]) -> str:
    """Digest the merged payload and diagnostic codes; filenames in paths/messages are excluded."""
    file_payloads: list[tuple[str, dict[str, Any]]] = []
    diagnostics = []
    for name, data in named_bytes:
        try:
            payload = tomllib.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            raise MigrationRefusal("invalid-toml", name) from None
        try:
            validate_file_schema(payload, name)
        except OpsConfigError as error:
            raise MigrationRefusal(error.diagnostics[0].code, name) from None
        diagnostics.extend(unknown_top_level_diagnostics(payload, source=name))
        diagnostics.extend(unknown_file_field_diagnostics(payload, name))
        file_payloads.append((name, payload))
    merged, merge_diagnostics = merge_ops_config_payloads(file_payloads)
    diagnostics.extend(merge_diagnostics)
    diagnostics.extend(parse_storage_section(merged.get("storage"))[1])
    errors = sorted({item.code for item in diagnostics if item.severity == "error"})
    if errors:
        raise MigrationRefusal(errors[0], more=tuple({"code": code, "file": ""} for code in errors[1:]))
    canonical = json.dumps(
        {"merged": merged, "diagnostics": [[item.severity, item.code] for item in diagnostics]},
        sort_keys=True, separators=(",", ":"), default=_toml_value,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_journal(home: Home, operation_id: str, plan: dict[str, Any], records: Sequence[Any], digest: str) -> dict[str, Any]:
    entries = []
    for index, (change, record) in enumerate(zip(plan["changes"], records)):
        entries.append({
            "index": index, "source": change["source"], "target": change["target"], "layer": change["layer"],
            "size": len(record.data), "sha256": record.sha256, "mode": record.mode,
            "dev": record.info.st_dev, "ino": record.info.st_ino, "restored_dev": None, "restored_ino": None,
        })
    return {
        "schema": JOURNAL_SCHEMA, "operation_id": operation_id, "state": "preparing",
        "home": {"dev": home.dev, "ino": home.ino}, "source_format": "legacy",
        "source_order": list(plan["source_order"]), "proposed_order": list(plan["proposed_order"]),
        "effective_sha256": digest, "entries": entries,
    }


def _integer(value: Any, *, low: int = 0, high: int | None = None) -> bool:
    return type(value) is int and value >= low and (high is None or value <= high)


def _valid_entry(entry: Any, index: int) -> bool:
    if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS or entry["index"] != index:
        return False
    restored = (entry["restored_dev"], entry["restored_ino"])
    return (
        _integer(entry["index"]) and all(isinstance(entry[key], str) and valid_name(entry[key]) for key in ("source", "target"))
        and entry["layer"] in ("base", "local") and _integer(entry["size"], high=MAX_FILE_BYTES)
        and isinstance(entry["sha256"], str) and _HEX64.fullmatch(entry["sha256"]) is not None
        and _integer(entry["mode"], high=0o777) and _integer(entry["dev"]) and _integer(entry["ino"])
        and (restored == (None, None) or all(_integer(value) for value in restored))
    )


def _valid_home(recorded: Any, home: Home) -> bool:
    """Bind on the home inode; the recorded device is evidence only, as st_dev may change across reboot."""
    return (
        isinstance(recorded, dict) and set(recorded) == {"dev", "ino"} and _integer(recorded["dev"])
        and _integer(recorded["ino"]) and recorded["ino"] == home.ino
    )


def validate_journal(document: Any, home: Home) -> dict[str, Any]:
    """Strict v1 validation, including a fresh planner recomputation of the recorded mapping."""
    try:
        if not isinstance(document, dict) or set(document) != _JOURNAL_KEYS:
            raise ValueError
        entries = document["entries"]
        if (
            document["schema"] != JOURNAL_SCHEMA or document["state"] not in STATES
            or not isinstance(document["operation_id"], str) or not _HEX32.fullmatch(document["operation_id"])
            or not _valid_home(document["home"], home) or document["source_format"] != "legacy"
            or not isinstance(document["effective_sha256"], str) or not _HEX64.fullmatch(document["effective_sha256"])
            or not isinstance(entries, list) or not 0 < len(entries) <= MAX_CONFIG_FILES
            or not all(_valid_entry(entry, index) for index, entry in enumerate(entries))
            or sum(entry["size"] for entry in entries) > MAX_TOTAL_BYTES
        ):
            raise ValueError
        sources = [entry["source"] for entry in entries]
        plan = plan_cloe_config_filenames(sources)
        names = sources + [entry["target"] for entry in entries]
        if (
            plan["refusals"] or plan["source_format"] != "legacy" or document["source_order"] != sources
            or document["proposed_order"] != plan["proposed_order"]
            or plan["changes"] != [{key: entry[key] for key in ("source", "target", "layer")} for entry in entries]
            or len({portable_config_name(name) for name in names}) != len(names)
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise MigrationRefusal("config-migration-journal-invalid") from None
    return document


def read_journal(home: Home) -> dict[str, Any] | None:
    if home.lstat(JOURNAL_NAME, in_op=True) is None:
        return None
    data, info = home.read(JOURNAL_NAME, MAX_JOURNAL_BYTES, "config-migration-journal-invalid", in_op=True)
    if not owned_regular(info):
        raise MigrationRefusal("config-migration-journal-invalid")
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MigrationRefusal("config-migration-journal-invalid") from None
    return validate_journal(document, home)


def write_journal(home: Home, journal: dict[str, Any], state: str | None = None) -> None:
    """Durably publish one journal state: private temp, fsync, rename, directory fsync."""
    if state is not None:
        journal["state"] = state
    data = json.dumps(journal, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_JOURNAL_BYTES:
        raise MigrationRefusal("config-migration-limit-exceeded")
    stale = home.lstat(JOURNAL_TEMP_NAME, in_op=True)
    if stale is not None:
        if not owned_regular(stale):
            raise MigrationRefusal("config-migration-residue-unsafe", JOURNAL_TEMP_NAME)
        home.unlink(JOURNAL_TEMP_NAME, in_op=True)
    home.create(JOURNAL_TEMP_NAME, data)
    home.replace_in_op(JOURNAL_TEMP_NAME, JOURNAL_NAME)
    home.sync(in_op=True)
