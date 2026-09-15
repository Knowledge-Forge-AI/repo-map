"""TEST-HYGIENE3B3 O2-O6 and O9-O12 authorization boundaries."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repomap_test_support.resource_operator_reclamation import (
    CONFIRMATION_LITERAL,
    OperatorReclamationRequest,
    reclaim_run_population,
)
from repomap_test_support.resource_operator_reclamation_test_support import (
    add_pin,
    add_run,
    dead,
    live,
    private_root,
    unknown,
)


def request(
    confirmation: str | None,
    *,
    force_live: bool = False,
    override_pins: bool = False,
) -> OperatorReclamationRequest:
    return OperatorReclamationRequest(
        confirmation=confirmation,
        force_live=force_live,
        override_pins=override_pins,
    )


def reclaim(
    root: Path,
    value: OperatorReclamationRequest,
    *,
    liveness=dead,
):
    return reclaim_run_population(
        root,
        value,
        now_seconds=100,
        process_is_live=liveness,
    )


def test_o2_missing_confirmation_refuses_before_mutation(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "missing-confirmation")

    result = reclaim(root, request(None))

    assert result.outcome == "confirmation_refused"
    assert run.exists()
    assert result.physical_mutation_performed is False


@pytest.mark.parametrize(
    "value",
    [
        "wrong",
        "irreversibly reclaim all contents of the selected scratch run directory including non-repomap and retained evidence",
        CONFIRMATION_LITERAL[:-1],
        CONFIRMATION_LITERAL + "!",
        " " + CONFIRMATION_LITERAL,
        CONFIRMATION_LITERAL + " ",
        f"prefix {CONFIRMATION_LITERAL} suffix",
    ],
)
def test_o3_confirmation_requires_exact_cli_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "exact-confirmation")
    monkeypatch.setenv("REPOMAP_OPERATOR_CONFIRMATION", CONFIRMATION_LITERAL)

    result = reclaim(root, request(value))

    assert result.outcome == "confirmation_refused"
    assert run.exists()
    assert "REPOMAP_OPERATOR_CONFIRMATION" in os.environ


def test_o4_request_has_no_arbitrary_scope_field() -> None:
    fields = set(OperatorReclamationRequest.__dataclass_fields__)
    assert fields == {"confirmation", "force_live", "override_pins"}
    assert not fields & {"path", "root", "glob", "regex", "project", "run_id"}


def test_o5_live_run_refuses_without_force(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "live-default", state="running", pid=123)

    result = reclaim(root, request(CONFIRMATION_LITERAL), liveness=live)

    assert result.outcome == "live_run_refused"
    assert result.live_count == 1
    assert run.exists()


def test_o6_unknown_liveness_refuses_even_with_force(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "unknown-live", state="running", pid=123)

    result = reclaim(
        root,
        request(CONFIRMATION_LITERAL, force_live=True),
        liveness=unknown,
    )

    assert result.outcome == "unknown_liveness_refused"
    assert result.unknown_count == 1
    assert run.exists()


def test_o9_pin_refuses_by_default_and_malformed_pin_is_conservative(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "pinned-default")
    add_pin(root, run.name, valid=False)

    result = reclaim(root, request(CONFIRMATION_LITERAL))

    assert result.outcome == "operator_pin_refused"
    assert result.pin_count == 1
    assert run.exists()


def test_o10_explicit_pin_override_can_proceed(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "pinned-override")
    pin = add_pin(root, run.name)

    result = reclaim(
        root,
        request(CONFIRMATION_LITERAL, override_pins=True),
    )

    assert result.outcome == "completed"
    assert not run.exists()
    assert not pin.exists()


def test_o11_force_live_does_not_imply_pin_override(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "live-and-pinned", state="running", pid=123)
    add_pin(root, run.name)

    result = reclaim(
        root,
        request(CONFIRMATION_LITERAL, force_live=True),
        liveness=live,
    )

    assert result.outcome == "operator_pin_refused"
    assert run.exists()


def test_o12_pin_override_does_not_imply_live_force(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "pinned-and-live", state="running", pid=123)
    add_pin(root, run.name)

    result = reclaim(
        root,
        request(CONFIRMATION_LITERAL, override_pins=True),
        liveness=live,
    )

    assert result.outcome == "live_run_refused"
    assert run.exists()


def test_o25_environment_and_defaults_cannot_self_authorize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "no-self-authority")
    monkeypatch.setenv("REPOMAP_TEST_OPERATOR_CONFIRMATION", CONFIRMATION_LITERAL)

    result = reclaim(root, request(None))

    assert result.outcome == "confirmation_refused"
    assert run.exists()


def test_r1_foreign_running_missing_pid_no_longer_vetoes(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run = add_run(
        root,
        "foreign-missing-pid",
        project="other-project",
        state="running",
        pid=None,
    )

    result = reclaim(root, request(CONFIRMATION_LITERAL), liveness=live)

    assert result.outcome == "completed"
    assert (result.live_count, result.unknown_count) == (0, 0)
    assert not run.exists()


def test_r2_exact_valid_missing_pid_still_refuses(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run = add_run(root, "valid-missing-pid", state="running", pid=None)

    result = reclaim(root, request(CONFIRMATION_LITERAL), liveness=dead)

    assert result.outcome == "unknown_liveness_refused"
    assert result.unknown_count == 1
    assert run.exists()


def test_r5_foreign_live_metadata_does_not_require_force(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    run = add_run(
        root,
        "foreign-live-metadata",
        project="other-project",
        state="running",
        pid=123,
    )

    result = reclaim(root, request(CONFIRMATION_LITERAL), liveness=live)

    assert result.outcome == "completed"
    assert result.live_count == 0
    assert not run.exists()
