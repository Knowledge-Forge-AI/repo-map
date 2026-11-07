"""Optional real ANN provenance; synthetic vectors confer no model acceptance."""

from pathlib import Path

import pytest

from repomap_test_support.w5_component_functional_experiment import run_functional_proof


@pytest.mark.requires_pgvector
def test_w5_functional_ann_current_publication_to_result_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Isolate this disposable diagnostic from ambient planner settings. The
    # exact-vector owner still installs and restores its fixed reader options.
    monkeypatch.delenv("PGOPTIONS",raising=False)
    proof = run_functional_proof(tmp_path)
    assert proof["ann_completed"] is True
    assert proof["worker_receipts_claimed"] is False
    assert proof["learned_attempt16"] is False
    assert proof["scientific_acceptance"] is False
