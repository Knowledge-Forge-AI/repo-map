"""Retained-byte reprojection refuses incomplete or invented historical evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from retrieval_evaluation_historical_evidence import verify_completed_attempt
from retrieval_evaluation_reprojection import load_journal_envelopes, reproject_attempt7_files
from retrieval_evaluation_schema import load_task_catalog
from retrieval_evaluation_slots_v2 import upgrade_slot_to_v2

_BASE = MIXED_V1_FIXTURE_ROOT / "baseline"
_RAW = _BASE / "w3" / "historical-attempt-7"


def _project(directory: Path) -> dict:
    report, _ = reproject_attempt7_files(
        attempt7_report_path=_BASE / "calibration-attempt-7.json",
        attempt7_declaration_path=_BASE / "attempt-declaration-7.json",
        catalog_path=MIXED_V1_FIXTURE_ROOT / "tasks/catalog-v1.json",
        freeze_path=MIXED_V1_FIXTURE_ROOT / "freeze-v1.json",
        attempt_directory=directory,
    )
    return report


def _copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(_RAW, tmp_path / "retained"))


@pytest.mark.parametrize("filename", ["observations.jsonl", "sources.zip", "source-manifest.json", "report.json"])
def test_historical_projection_requires_every_original_raw_file(tmp_path: Path, filename: str) -> None:
    retained = _copy(tmp_path)
    (retained / filename).unlink()
    with pytest.raises(ValueError, match="six regular evidence files"):
        _project(retained)


@pytest.mark.parametrize("filename", ["observations.jsonl", "declaration.json", "sources.zip", "report.json"])
def test_terminal_verification_uses_raw_bytes_not_reserialized_payload(tmp_path: Path, filename: str) -> None:
    retained = _copy(tmp_path)
    with (retained / filename).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="mismatch"):
        verify_completed_attempt(retained)


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "boolean_repetition", "fallback_string"])
def test_observation_population_and_wire_types_are_strict(tmp_path: Path, mutation: str) -> None:
    declaration = json.loads((_RAW / "declaration.json").read_bytes())
    events = [json.loads(line) for line in (_RAW / "observations.jsonl").read_bytes().splitlines()]
    observed = next(event for event in events if event["event"] == "query_observed")
    if mutation == "duplicate":
        events.append(observed)
    elif mutation == "missing":
        events.remove(observed)
    elif mutation == "boolean_repetition":
        observed["repetition"] = True
    else:
        fallback = next(event for event in events if event.get("envelope", {}).get("fallback"))
        fallback["envelope"]["fallback"]["caller_selected"] = "true"
    journal = tmp_path / "journal.jsonl"
    journal.write_text("".join(json.dumps(event) + "\n" for event in events))
    with pytest.raises(ValueError):
        load_journal_envelopes(
            journal, expected_arms=tuple(declaration["arms"]),
            expected_tasks=tuple(declaration["ordered_task_ids"]), repetitions=3,
        )


def test_reprojection_preserves_observed_fallbacks_and_original_raw_identity() -> None:
    report = _project(_RAW)
    slots = [slot for arm in report["arms"].values() for slot in arm["slots"]]
    body_fallbacks = [slot for slot in slots if slot["fallback"] is not None
                      and slot["comparability_stratum"] == "metadata"
                      and slot["match_surface"] == "captured_text"]
    assert len(body_fallbacks) == 15
    assert all(slot["fallback"]["caller_selected"] is True for slot in body_fallbacks)
    assert all(slot["omission_count"] == len(slot["omissions"]) for slot in slots)
    provenance = report["reprojection_provenance"]
    assert provenance["source_journal_sha256"] == "sha256:" + hashlib.sha256((_RAW / "observations.jsonl").read_bytes()).hexdigest()
    assert provenance["retained_raw_file_sha256"]["report.json"] != provenance["source_attempt_report_sha256"]
    assert len(report["repetition_observations"]) == 360


def test_v2_slot_never_invents_missing_envelope_fields() -> None:
    task = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks/catalog-v1.json").calibration_tasks()[0]
    with pytest.raises(ValueError, match="retained query envelope evidence"):
        upgrade_slot_to_v2(
            {"task_id": task.task_id}, task, arm_id="native_tools_baseline",
            backend="native_filesystem", comparator_exposure="unknown",
        )
