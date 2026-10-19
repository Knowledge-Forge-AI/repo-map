"""Persisted JSON readback preserves numeric/escape semantics and refuses invalid flags."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.sqlite_local.investigation_queries import observation_search
from repomap_kg.storage.sqlite_local.nix_summary_queries import nix_summary
from repomap_kg.storage.sqlite_local.summary_queries import python_summary
from repomap_kg.storage.sqlite_local.connection import read_transaction
from repomap_test_support.sqlite_local_fixtures import local_binding, published_sqlite_database, sqlite_logical_dump

BINDING = local_binding()


def _stored_payload(path: Path, kind: str, payload: str) -> None:
    """Supply exact persisted JSON text, including numbers outside bundle fixtures."""
    with closing(sqlite3.connect(path, autocommit=True)) as writer:
        changed = writer.execute(
            "UPDATE raw_observations SET kind = ?, payload_json = ? WHERE ordinal = "
            "(SELECT min(ordinal) FROM raw_observations)", (kind, payload),
        ).rowcount
    assert changed == 1


def test_observation_search_matches_jsonb_numeric_and_control_character_spelling(tmp_path: Path) -> None:
    path = published_sqlite_database(tmp_path / "store")
    text = 'back\bform\ffeed\nline\rreturn\ttab\x01slash\\quote"'
    payload = ('{"metadata":{"text":' + json.dumps(text) + '},"number":1.25000e2,"zero":-0.000}')
    _stored_payload(path, "custom.note", payload)
    before = sqlite_logical_dump(path)
    needles = ('"number": 125.000', '"zero": 0.000', json.dumps(text))
    with read_transaction(path, BINDING) as reader:
        for query in needles:
            page = observation_search(reader, query=query, kind="custom.note", path=None,
                                      limit=1, offset=0, include_raw=True)
            assert page["total"] == 1 and page["has_more"] is False
            row, = page["results"]
            assert row["metadata"] == {"text": text}
            assert row["payload"] == {"metadata": {"text": text}, "number": 125, "zero": 0}
        compact = observation_search(reader, query='"number":1.25000e2', kind="custom.note", path=None,
                                     limit=1, offset=0, include_raw=False)
        assert compact == {"results": [], "total": 0, "has_more": False}
    assert sqlite_logical_dump(path) == before


@pytest.mark.parametrize("flag", [" \t\n", "o"], ids=["blank", "ambiguous-prefix"])
def test_invalid_persisted_boolean_refuses_summary_and_a_corrected_retry_succeeds(tmp_path: Path, flag: str) -> None:
    path = published_sqlite_database(tmp_path / "store")
    payload = {"metadata": {"not_fetched": flag, "reference_kind": "direct_url"}}
    _stored_payload(path, "python.reference", json.dumps(payload))
    before = sqlite_logical_dump(path)
    with pytest.raises(StorageSchemaError, match="^stored raw observation flag is not a boolean$"):
        with read_transaction(path, BINDING) as reader:
            python_summary(reader, root_path=BINDING.root_path)
    assert sqlite_logical_dump(path) == before
    payload["metadata"]["not_fetched"] = "false"
    _stored_payload(path, "python.reference", json.dumps(payload))
    with read_transaction(path, BINDING) as reader:
        summary = asdict(python_summary(reader, root_path=BINDING.root_path))
    assert summary["references"]["total"] == 1
    assert summary["references"]["direct_urls_not_fetched"] == 0


@pytest.mark.parametrize(
    ("metadata", "programs"), [(["program"], 1), ("program", 1), (7, 0)],
    ids=["array-key", "scalar-key", "non-container"],
)
def test_non_object_metadata_retains_jsonb_key_semantics_in_persisted_summary(
    tmp_path: Path, metadata: Any, programs: int,
) -> None:
    path = published_sqlite_database(tmp_path / "store")
    _stored_payload(path, "nix.app", json.dumps({"metadata": metadata}))
    before = sqlite_logical_dump(path)
    with read_transaction(path, BINDING) as reader:
        summary = asdict(nix_summary(reader, root_path=BINDING.root_path))
    assert summary["programs"]["app_programs_total"] == programs
    assert summary["diagnostics"]["missing_output_identity"] == 1
    assert sqlite_logical_dump(path) == before
