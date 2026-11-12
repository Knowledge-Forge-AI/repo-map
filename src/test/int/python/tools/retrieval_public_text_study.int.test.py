"""The single learned public-text study owner (``PUBLICTEXT-CAL1``, study section 19.2).

NOT a source-proof selector: it is excluded from every scoped proof list and
from ordinary core CI. It is selected only by the private host, after source
acceptance, independent review and native admission, with the existing
``requires_pgvector`` profile. It runs the same driver with
``functional_only: false`` and never installs the synthetic supplier; without
the external private supervisor it stops at the unchanged controller-admission
wait and fails with a private failure receipt, never an empty success.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.w5_public_text_study import StudyEnvironment, run_public_text_study
from test_sandbox_contract import INNER_REPORT_ROOT

EXPORT_ROOT = INNER_REPORT_ROOT / "public-text-study"


@pytest.mark.requires_pgvector
def test_public_text_semantic_study(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[5]
    work = tmp_path.resolve()
    with temporary_postgres() as database:
        outcome = run_public_text_study(StudyEnvironment(
            database=database, repo_root=repo, workspace=work / "workspace",
            journal_root=EXPORT_ROOT / "w5-semantic-attempts", report_root=EXPORT_ROOT, functional_only=False))
    assert outcome.failure_code is None, (outcome.state, outcome.failure_code)
    assert outcome.diagnostic_errors == ()
    assert outcome.state == "REPORTED" and outcome.observed_cells == 864
    assert outcome.verification == "raw_evidence_verified" and outcome.native_reservations == 0
    assert outcome.cleanup is not None and outcome.cleanup["status"] == "clean"
