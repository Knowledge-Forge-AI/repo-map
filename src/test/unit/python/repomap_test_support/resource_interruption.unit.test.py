"""TEST-HYGIENE3A operator-interruption attribution contracts."""

from __future__ import annotations

import json
from pathlib import Path

from repomap_test_support.resource_interruption import (
    InterruptionOutcome,
    classify_interruption,
)


def test_explicit_operator_marker_is_distinct_from_unattributed_mutation(tmp_path: Path):
    marker = tmp_path / "operator-marker.json"
    marker.write_text(
        json.dumps(
            {
                "schema": "repomap-test-operator-interruption-v1",
                "project": "repo-map_dev",
                "phase": "TEST-HYGIENE3A",
                "run_id": "run1",
                "operator_attributed": True,
                "observed_at_seconds": 100,
            }
        )
    )
    marker.chmod(0o600)
    assert classify_interruption(
        marker,
        project="repo-map_dev",
        phase="TEST-HYGIENE3A",
        run_id="run1",
        state_changed=True,
    ) is InterruptionOutcome.OPERATOR_INTERRUPTED
    assert classify_interruption(
        tmp_path / "missing.json",
        project="repo-map_dev",
        phase="TEST-HYGIENE3A",
        run_id="run1",
        state_changed=True,
    ) is InterruptionOutcome.EXTERNAL_UNATTRIBUTED_MUTATION


def test_malformed_or_wrong_run_marker_never_attributes_operator(tmp_path: Path):
    marker = tmp_path / "operator-marker.json"
    marker.write_text(
        json.dumps(
            {
                "schema": "repomap-test-operator-interruption-v1",
                "project": "repo-map_dev",
                "phase": "TEST-HYGIENE3A",
                "run_id": "other-run",
                "operator_attributed": True,
                "observed_at_seconds": 100,
            }
        )
    )
    marker.chmod(0o600)
    assert classify_interruption(
        marker,
        project="repo-map_dev",
        phase="TEST-HYGIENE3A",
        run_id="run1",
        state_changed=True,
    ) is InterruptionOutcome.EXTERNAL_UNATTRIBUTED_MUTATION
