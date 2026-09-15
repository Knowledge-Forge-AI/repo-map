from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support import test_cov5k_r2_fix1_executors as owner_fixtures
from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_process_recorder import (
    execute_zero_process_boundary,
)


_H_ENTRIES = tuple(
    entry for entry in build_closed_catalog() if entry.semantic_group == "H"
)


@pytest.mark.parametrize("entry", _H_ENTRIES, ids=lambda entry: entry.condition_id)
def test_all_group_h_axes_use_complete_creation_boundary(
    tmp_path: Path,
    entry,
) -> None:
    evidence = execute_zero_process_boundary(
        entry,
        lambda: owner_fixtures.execute_group_h(tmp_path, entry),
    )
    observed = dict(evidence.observed_fields)

    assert evidence.owner_entered
    assert evidence.model_rehearsal_only
    assert evidence.qualification_status == "unqualified"
    operation_started_ns = observed["operation_started_ns"]
    operation_ended_ns = observed["operation_ended_ns"]
    host_process_count = observed["host_process_count"]
    assert isinstance(operation_started_ns, int)
    assert isinstance(operation_ended_ns, int)
    assert isinstance(host_process_count, int)
    assert operation_started_ns <= operation_ended_ns
    assert host_process_count >= int(entry.condition_id == "H08")
    assert observed["nested_psql_intent_count"] == int(
        entry.condition_id == "H05"
    )
