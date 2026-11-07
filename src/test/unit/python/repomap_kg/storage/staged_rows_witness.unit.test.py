"""Witnessed staged-row boundary: no direct row authority or tuple replacement."""

from __future__ import annotations

from pathlib import Path

import pytest

from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.staged_rows import build_staged_rows
from repomap_test_support.rust_pilot_semantic_fixtures import live_pilot


def test_witnessed_rows_retain_continuous_ordinals_and_rust_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with live_pilot(tmp_path, monkeypatch) as live:
        prepared = build_staged_rows(
            live.witnessed.observations, repository_name="synthetic",
            stage_id="stage-test", witnessed=live.witnessed,
        )
        try:
            raw = tuple(prepared.family_rows["raw_observations"])
            assert [row["source_ordinal"] for row in raw] == list(range(len(raw)))
            assert any(str(row["kind"]).startswith("rust.") for row in raw)
            assert any(str(row["canonical_key"]).startswith("rust.") for row in prepared.family_rows["canonical_nodes"])
        finally:
            prepared.close()
        with pytest.raises(StorageSchemaError):
            build_staged_rows(list(live.witnessed.observations), repository_name="synthetic",
                              stage_id="stage-test", witnessed=live.witnessed)
