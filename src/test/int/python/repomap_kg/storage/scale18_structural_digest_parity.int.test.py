from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_build_profile

from repomap_test_support.postgres_harness import require_postgres_binaries
from repomap_test_support.scale15_runtime_campaign import (
    expected_authority,
    run_ordinary_refresh,
    start_scale15_runtime,
    stop_scale15_runtime,
)
from scale13_actual_path_readback import read_actual_path_state
from scale15_actual_path_readback import read_scale15_terminal_state
from scale15_terminal_contracts import PublicationState


GRAPH_IDS = ("scale18-reference", "scale18-repeat")


def test_prelaunch_and_streaming_readback_digest_parity_repeats_exactly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    require_postgres_binaries()
    fixture = start_scale15_runtime(tmp_path, GRAPH_IDS)
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", fixture.password)
    monkeypatch.setenv("PGPASSWORD", fixture.password)
    try:
        states = []
        for graph_id in GRAPH_IDS:
            completed = run_ordinary_refresh(fixture, graph_id)
            assert completed.returncode == 0, completed.stderr
            state = read_actual_path_state(fixture.psql_args(graph_id))
            structural_digest = state["structural_digest"]
            assert isinstance(structural_digest, str)
            expected = expected_authority(
                fixture,
                graph_id,
                state["family_counts"],
                structural_digest,
            )
            terminal = read_scale15_terminal_state(
                fixture.psql_args(graph_id),
                expected,
            )
            assert terminal.publication_state is PublicationState.PUBLISHED
            states.append(state)

        assert states[0]["family_counts"] == states[1]["family_counts"]
        assert states[0]["structural_digest"] == states[1]["structural_digest"]
    finally:
        stop_scale15_runtime(fixture)
