"""Unit tests for the retrieval evaluation harness, CLI subcommands, and held-out execution refusal (S3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
from retrieval_evaluation import main as cli_main
from retrieval_evaluation_harness import (
    verify_fixture_freeze_guard,
)
from retrieval_evaluation_schema import (
    load_freeze_manifest,
    load_task_catalog,
)


@pytest.mark.parametrize("command", ["freeze", "propose-criteria"])
def test_cli_frozen_inputs_and_criteria_never_overwrite_existing_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str,
) -> None:
    output = tmp_path / "existing.json"
    output.write_bytes(b"retained pre-existing bytes\n")
    args = [command, "--output", str(output)]
    if command == "propose-criteria":
        args += ["--baseline", str(tmp_path / "never-read.json")]
    assert cli_main(args) == 2
    assert "refusing to overwrite" in capsys.readouterr().err
    assert output.read_bytes() == b"retained pre-existing bytes\n"


def test_cli_validate_succeeds_on_committed_catalog_and_freeze(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI `validate` verifies catalog-v1.json and freeze-v1.json without executing queries."""
    rc = cli_main(
        [
            "validate",
            "--catalog",
            str(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json"),
            "--freeze",
            str(MIXED_V1_FIXTURE_ROOT / "freeze-v1.json"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert '"status": "valid"' in out
    assert '"total_tasks": 36' in out
    assert '"calibration_tasks": 24' in out
    assert '"held_out_tasks": 12' in out


def test_cli_refuses_held_out_execution_in_w2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI refuses any attempt to declare or execute the held-out split in W2."""
    rc = cli_main(
        [
            "declare-attempt",
            "--attempt-id",
            "illegal-held-out-1",
            "--split",
            "held_out",
            "--output",
            str(tmp_path / "decl.json"),
        ]
    )
    assert rc != 0
    err = capsys.readouterr().err
    assert "held_out" in err

    existing = tmp_path / "existing-decl.json"
    existing.write_text("{}", encoding="utf-8")
    rc_overwrite = cli_main(
        [
            "declare-attempt",
            "--attempt-id",
            "calibration-attempt-overwrite",
            "--split",
            "calibration",
            "--output",
            str(existing),
        ]
    )
    assert rc_overwrite != 0
    assert "refusing to overwrite" in capsys.readouterr().err


def test_fixture_freeze_guard_detects_tampered_catalog_or_working_copy(
    tmp_path: Path,
) -> None:
    """verify_fixture_freeze_guard refuses drifted catalog digests or mutated fixture files."""
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
    freeze = load_freeze_manifest(MIXED_V1_FIXTURE_ROOT / "freeze-v1.json")
    verify_fixture_freeze_guard(catalog, freeze, work_dir=tmp_path / "guard_ok")

    drifted_freeze = load_freeze_manifest(MIXED_V1_FIXTURE_ROOT / "freeze-v1.json")
    object.__setattr__(drifted_freeze, "catalog_sha256", "sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="catalog digest mismatch"):
        verify_fixture_freeze_guard(catalog, drifted_freeze, work_dir=tmp_path / "guard_bad")


@pytest.mark.parametrize("requested", ["ranked_discovery", "current_literal_enumeration", "literal_captured_text"])
def test_projection_adapter_preserves_requested_mode_and_discloses_literal_fallback(
    tmp_path: Path, requested: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace
    from common_lore_index.retrieval.projection_build import build_captured_text_projection
    from common_lore_index.retrieval.query_contracts import MatchSurface, QueryEnvelope, QueryMode
    from repomap_test_support.retrieval_evaluation_query_fixture import build_fixture_projection
    from retrieval_evaluation_grading import ExecutionState
    from retrieval_evaluation_reference import execute_projection_reference_task

    inputs, policy = build_fixture_projection(spool_dir=tmp_path / "spool")
    import retrieval_evaluation_reference as reference_adapter

    def fixture_binding(alias: str, graph_id: str) -> str:
        assert alias == "core" and graph_id == inputs.accepted_reference.graph_id
        return inputs.manifest.bindings[0].binding_id

    monkeypatch.setattr(reference_adapter, "binding_id_for_alias", fixture_binding)
    projection = build_captured_text_projection(inputs, policy)
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks/catalog-v1.json")
    task = replace(
        catalog.calibration_tasks()[0], graph_id=inputs.accepted_reference.graph_id,
        selected_bindings=("core",), requested_mode=requested,
        permitted_query_plan={"query": "BOUNDARY_START_TOKEN", "limit": 10},
    )
    state, envelope, _, accounting = execute_projection_reference_task(
        task, projection, current_accepted=inputs.accepted_reference,
    )
    assert state == ExecutionState.COMPLETED and envelope.hits
    assert envelope.requested_mode == QueryMode(requested)
    assert envelope.effective_mode == QueryMode.LITERAL_CAPTURED_TEXT
    assert envelope.match_surface == MatchSurface.CAPTURED_TEXT
    assert QueryEnvelope.from_mapping(envelope.to_dict()) == envelope
    if requested == "literal_captured_text":
        assert envelope.fallback is None
    else:
        assert envelope.fallback is not None
        assert envelope.fallback.caller_selected is True
        assert envelope.fallback.from_mode == QueryMode(requested)
        assert envelope.fallback.to_mode == QueryMode.LITERAL_CAPTURED_TEXT
    import json
    assert accounting.observed_output_payload_bytes == len(json.dumps(envelope.to_dict(), sort_keys=True).encode())
