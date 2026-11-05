"""Live witness identity, mutation and refusal owners."""

from __future__ import annotations

import copy
import pickle
from pathlib import Path
from typing import Any, cast

import pytest

from common_lore_index.canonicalization.rust_pilot_family import (
    WitnessedCanonicalization,
    canonicalize_rust_pilot,
)
from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.staged_rows import build_staged_rows
from repomap_test_support.rust_pilot_semantic_fixtures import live_pilot


def test_positive_witness_is_bound_to_exact_controller_and_tuple(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with live_pilot(tmp_path, monkeypatch) as live:
        assert getattr(live.witnessed, "_run") is live.controller
        assert live.witnessed.verify_live()
        replacement = (*live.witnessed.observations,)
        with pytest.raises(StorageSchemaError, match="identity"):
            build_staged_rows(replacement, repository_name="synthetic", stage_id="stage-test",
                              witnessed=live.witnessed)
        with pytest.raises(ContractError):
            canonicalize_rust_pilot(cast(Any, object()), live.legacy_observations)


def test_exposed_result_and_raw_metadata_mutations_invalidate_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with live_pilot(tmp_path, monkeypatch) as live:
        cast(dict[str, Any], live.witnessed.result.graph.nodes[0].metadata)["tampered"] = True
        assert not live.witnessed.verify_live()
    with live_pilot(tmp_path / "raw", monkeypatch) as live:
        cast(dict[str, Any], live.witnessed.observations[0].metadata)["tampered"] = True
        assert not live.witnessed.verify_live()


def test_closed_controller_copy_pickle_and_forged_missing_slots_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with live_pilot(tmp_path, monkeypatch) as live:
        for action in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(ContractError):
                action(live.witnessed)
        forged = object.__new__(WitnessedCanonicalization)
        assert forged.verify_live() is False
        live.controller.close()
        assert not live.witnessed.verify_live()
        with pytest.raises(StorageSchemaError, match="live"):
            build_staged_rows(live.witnessed.observations, repository_name="synthetic",
                              stage_id="stage-test", witnessed=live.witnessed)
