"""Append-only, source/test-bound history for dynamic retention contracts."""

from __future__ import annotations

from typing import Any, Mapping


SCHEMA = "repomap-python-retention-dynamic-v1"
KEYS = {"id", "owner", "owner_sha256", "test", "test_sha256", "kind",
        "symbol", "fingerprint", "recipe", "targets", "parameters", "supersedes"}


def active_boundaries(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate a closed schema and return the active heads without erasing history."""
    if "dynamic_boundaries" not in document and "dynamic_schema" not in document:
        return []
    if document.get("dynamic_schema") != SCHEMA:
        raise ValueError("invalid dynamic boundary schema")
    records = document.get("dynamic_boundaries")
    if not isinstance(records, list):
        raise ValueError("dynamic boundaries must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    retired: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != KEYS:
            raise ValueError("invalid dynamic boundary keys")
        for key in KEYS - {"targets", "parameters", "supersedes"}:
            if not isinstance(record[key], str) or not record[key]:
                raise ValueError("invalid dynamic boundary string")
        for key in ("owner_sha256", "test_sha256", "fingerprint"):
            value = record[key]
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("invalid dynamic boundary digest")
        if record["id"] in by_id or not isinstance(record["targets"], list):
            raise ValueError("duplicate dynamic id or invalid targets")
        if not isinstance(record["parameters"], dict):
            raise ValueError("invalid dynamic parameters")
        previous = record["supersedes"]
        if previous is not None:
            if not isinstance(previous, str) or previous not in by_id or previous in retired:
                raise ValueError("invalid dynamic predecessor")
            old = by_id[previous]
            if (old["owner"] != record["owner"] or old["test"] != record["test"]
                    or old["owner_sha256"] == record["owner_sha256"]
                    or old["test_sha256"] == record["test_sha256"]):
                raise ValueError("dynamic replacement requires changed owner and test evidence")
            retired.add(previous)
        by_id[record["id"]] = record
    active = [record for key, record in by_id.items() if key not in retired]
    identities = [(r["owner"], r["symbol"], r["kind"], r["fingerprint"]) for r in active]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate dynamic operation declaration")
    return sorted(active, key=lambda r: r["id"])


def validate_dynamic_transition(older: Mapping[str, Any], newer: Mapping[str, Any]) -> None:
    """Published declaration bytes remain an exact prefix, including retired records."""
    active_boundaries(older)
    active_boundaries(newer)
    old = older.get("dynamic_boundaries", [])
    new = newer.get("dynamic_boundaries", [])
    if "dynamic_schema" in older and newer.get("dynamic_schema") != older["dynamic_schema"]:
        raise ValueError("dynamic boundary authority cannot disappear")
    if new[:len(old)] != old:
        raise ValueError("dynamic boundary history is not append-only")
