"""TEST-HYGIENE3B3 O1/O4/O25 maintenance CLI contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import test_hygiene_maintenance as maintenance_tool
import repomap_test_support.resource_operator_reclamation as reclamation
from repomap_test_support.resource_operator_reclamation import CONFIRMATION_LITERAL
from repomap_test_support.resource_operator_reclamation_test_support import (
    add_run,
    private_root,
)


def test_o1_operator_reclaim_action_is_explicit() -> None:
    arguments = maintenance_tool.parser().parse_args(
        ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
    )
    assert arguments.command == "operator-reclaim"
    assert arguments.confirm == CONFIRMATION_LITERAL
    assert arguments.force_live is False
    assert arguments.override_pins is False


def test_o4_cli_has_no_path_project_or_run_scope_argument() -> None:
    parser = maintenance_tool.parser()
    for option in ("--path", "--root", "--project", "--run-id", "--glob"):
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "operator-reclaim",
                    "--confirm",
                    CONFIRMATION_LITERAL,
                    option,
                    "/tmp/foreign",
                ]
            )


def test_explicit_preexisting_scratch_root_is_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("REPOMAP_TEST_SCRATCH_ROOT", raising=False)
    assert maintenance_tool.main(
        ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
    ) == 2
    assert "explicit_scratch_root_required" in capsys.readouterr().out

    missing = tmp_path / "must-not-be-created"
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(missing))
    assert maintenance_tool.main(
        ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
    ) == 2
    assert not missing.exists()


def test_cli_missing_confirmation_cannot_use_environment_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = private_root(tmp_path)
    run_root = add_run(root, "cli-no-self-authority")
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))
    monkeypatch.setenv("REPOMAP_TEST_OPERATOR_CONFIRMATION", CONFIRMATION_LITERAL)

    assert maintenance_tool.main(["operator-reclaim"]) == 2
    assert "confirmation_refused" in capsys.readouterr().out
    assert run_root.exists()


def test_pre_record_failure_uses_stable_closed_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = private_root(tmp_path)
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(root))
    error_type = getattr(
        reclamation, "OperatorReclamationPreflightError", RuntimeError
    )

    def fail(*_args, **_kwargs):
        raise error_type("scratch_root_authority_unavailable")

    monkeypatch.setattr(maintenance_tool, "reclaim_run_population", fail)

    assert maintenance_tool.main(
        ["operator-reclaim", "--confirm", CONFIRMATION_LITERAL]
    ) == 2
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "category": "scratch_root_authority_unavailable",
        "outcome": "operator_reclamation_refused",
        "physical_mutation_performed": False,
    }
