from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.test_cov5k_r2_fix2_administrative import (
    rehearse_actual_administrative_operation,
)
from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog


_K_ENTRIES = tuple(
    entry for entry in build_closed_catalog() if entry.semantic_group == "K"
)
_K_PARAMETERS = tuple(
    pytest.param(
        entry,
        id=entry.condition_id,
        marks=(
            pytest.mark.requires_build_profile
            if entry.condition_id == "K07"
            else ()
        ),
    )
    for entry in _K_ENTRIES
)


@pytest.mark.parametrize("entry", _K_PARAMETERS)
def test_all_group_k_operations_use_actual_disposable_routes(
    tmp_path: Path,
    entry,
) -> None:
    receipt = rehearse_actual_administrative_operation(
        Path.cwd(), tmp_path, entry
    )

    assert receipt.execution_disposition == entry.expected_execution_disposition
    assert receipt.shell is False
    assert receipt.timeout_seconds == 10
    assert len(receipt.effective_argv_digest) == 64
    assert receipt.process_evidence.host_process_count >= 1
    assert receipt.cleanup_contract == entry.cleanup_contract
    assert receipt.disposable_identity_digest
    assert receipt.cleanup_proved is True
    assert receipt.purpose == "qualification_executor_enactment_rehearsal"
    assert receipt.model_rehearsal_only is True
    assert receipt.qualification_status == "unqualified"
    assert receipt.process_evidence.nested_psql_intent_count == int(
        entry.condition_id == "K06"
    )
