"""Container-safe finalization proof with real six-member attempt artifacts."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import sys
from typing import Any

import pytest

from repomap_test_support.w5_experiment_results import (
    ResultV2Run,
    finalize_attempt_evidence,
)
from retrieval_semantic_experiment_artifacts import (
    decode_attempt_artifacts,
    emit_attempt_artifacts,
)
from retrieval_evaluation_attempts import admit_attempt
from retrieval_semantic_experiment_contracts import (
    ExperimentCostLedger,
    ExperimentPlan,
    ExperimentRefusal,
)


_DIGEST = "sha256:" + "a" * 64
_ATTEMPTS = ("w5-semantic-g1", "w5-semantic-g2")
_MEMBERS = (
    "declaration.json",
    "source-manifest.json",
    "sources.zip",
    "observations.jsonl",
    "report.json",
    "terminal.json",
)


def _plan(attempt_id: str) -> ExperimentPlan:
    return ExperimentPlan(
        attempt_id=attempt_id,
        generation=1 if attempt_id.endswith("g1") else 2,
        task_ids=("cal-01",),
        task_digests=(_DIGEST,),
        input_identity=_DIGEST,
        representation_report_identity=_DIGEST,
        publication_identity=_DIGEST,
        artifact_profile_identity=_DIGEST,
        controller_admission_sha256=_DIGEST,
        source_closure=(("tools/frozen.py", _DIGEST),),
        fixture_id="mixed-v1",
        freeze_sha256=_DIGEST,
        policy_digest=_DIGEST,
        arms=("exact_vector",),
    ).validate()


def _journal(root: Path, attempt_id: str) -> Any:
    raw = b"pass\n"
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    journal = admit_attempt(
        root,
        {
            "attempt_id": attempt_id,
            "candidate_closure_digests": {"tools/frozen.py": digest},
        },
        {"tools/frozen.py": raw},
    )
    journal.append({"event": "attempt_started"})
    return journal


@pytest.mark.parametrize("failure_mode", ("primary", "cleanup", "v2"))
def test_shared_finalizer_retains_legacy_members_before_v2_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    """Primary, cleanup-only, and V2 rejection all retain both six-file journals."""
    attempts_root = tmp_path / "attempts"
    result_v2 = ResultV2Run(enabled=True)
    journals = []
    reports: list[dict[str, object]] = []
    for attempt_id in _ATTEMPTS:
        result_v2.register(_plan(attempt_id))
        journal = _journal(attempts_root, attempt_id)
        status = "failed" if failure_mode == "primary" else "completed"
        report: dict[str, object] = {
            "status": status,
            "generation": 1 if attempt_id.endswith("g1") else 2,
        }
        if failure_mode == "primary":
            report.update(
                failure_type="ExperimentRefusal",
                failure_code="attempt_failed",
            )
        reports.append(report)
        journals.append((journal, ExperimentCostLedger(), status, report))

    cleanup_error = (
        ExperimentRefusal("cleanup_failed") if failure_mode == "cleanup" else None
    )
    legacy_stream = io.StringIO()
    v2_stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", v2_stream)
    attribution, v2_errors = finalize_attempt_evidence(
        journals,
        result_v2=result_v2,
        cleanup_status="failed" if cleanup_error is not None else "verified",
        cleanup_error=cleanup_error,
        attribution_error=None,
        emit_legacy=lambda paths: emit_attempt_artifacts(paths, stream=legacy_stream),
    )
    decoded = decode_attempt_artifacts(legacy_stream.getvalue().encode("ascii"))
    assert attribution is None
    assert set(decoded) == {
        f"{attempt_id}/{member}" for attempt_id in _ATTEMPTS for member in _MEMBERS
    }
    if failure_mode == "v2":
        assert len(v2_errors) == 2
        assert v2_stream.getvalue() == ""
    else:
        assert v2_errors == ()
        assert "REPO_MAP_W5_RESULT_V2 " in v2_stream.getvalue()
    if failure_mode == "cleanup":
        assert all(report["status"] == "failed" for report in reports)
        assert all(report["failure_code"] == "cleanup_failed" for report in reports)
