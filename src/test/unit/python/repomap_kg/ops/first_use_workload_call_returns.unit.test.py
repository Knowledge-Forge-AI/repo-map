"""Call-return witnesses remain independent of contradictory resource reports."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from typing import Any

import pytest

from repomap_test_support.first_use_workload_call_results import (
    ReturnedPublication, local_cli_publication, local_inprocess_publication,
    revocation_result, server_publication,
)
from common_lore_index.ops.resource_reports._codec import encode_report
from common_lore_index.ops.resource_view import ResourceObserver
from first_use_workload_census import load_census
from first_use_workload_recipe import scenario_steps
from repomap_test_support.first_use_workload_driver import CallOutcome, CleanupRegistry
from repomap_test_support.first_use_workload_session import Backend, ScenarioContext
from repomap_test_support.first_use_workload_local_steps import LocalSession
from repomap_test_support.first_use_workload_samples import pin
from repomap_test_support import first_use_workload_rows as rows
from repomap_test_support import first_use_workload_server_steps as server_steps
from repomap_test_support import first_use_workload_session as session_module


def test_local_cli_records_actual_generation_and_validates_success() -> None:
    returned = local_cli_publication({
        "result": "success", "storage_backend": "sqlite", "accepted_generation": 7,
    })
    assert (returned.outcome, returned.generation) == ("published", 7)
    for changed in ({"result": "failure"}, {"storage_backend": "postgresql"}):
        payload = {"result": "success", "storage_backend": "sqlite", "accepted_generation": 7}
        payload.update(changed)
        with pytest.raises(AssertionError, match="first-use-refresh-return-invalid"):
            local_cli_publication(payload)


@pytest.mark.parametrize("generation", [None, True, False, 0, -1, "7", 2**63])
def test_local_cli_never_coerces_a_returned_generation(generation: object) -> None:
    with pytest.raises(AssertionError, match="first-use-refresh-return-invalid"):
        local_cli_publication({
            "result": "success", "storage_backend": "sqlite", "accepted_generation": generation,
        })


@pytest.mark.parametrize(("reconciled", "expected"), [(False, "published"), (True, "reconciled_replay")])
def test_inprocess_local_uses_the_returned_replay_flag(reconciled: bool, expected: str) -> None:
    returned = local_inprocess_publication(SimpleNamespace(generation=3, reconciled=reconciled))
    assert (returned.outcome, returned.generation) == (expected, 3)


@pytest.mark.parametrize("reconciled", [None, "true", 1])
def test_inprocess_local_refuses_nonboolean_replay_flags(reconciled: object) -> None:
    with pytest.raises(AssertionError, match="first-use-refresh-return-invalid"):
        local_inprocess_publication(SimpleNamespace(generation=3, reconciled=reconciled))


def test_server_uses_returned_commit_state_without_inventing_a_generation() -> None:
    returned = server_publication(SimpleNamespace(
        result="success", error_category=None, publication_state="committed",
    ))
    assert (returned.outcome, returned.generation) == ("committed", None)
    for result, category, state in (
        ("failure", None, "committed"), ("success", "unexpected", "committed"),
        ("success", None, "not_started"),
    ):
        with pytest.raises(AssertionError, match="first-use-refresh-return-invalid"):
            server_publication(SimpleNamespace(
                result=result, error_category=category, publication_state=state,
            ))


def test_revocation_requires_an_actual_positive_effect() -> None:
    assert revocation_result(2) == "revoked"
    assert revocation_result(0) is None
    for bad in (None, True, -1, "2", 2**63):
        with pytest.raises(AssertionError, match="first-use-revoke-return-invalid"):
            revocation_result(bad)


@pytest.mark.parametrize("returned_generation", [3, 4])
def test_refresh_facts_use_call_return_and_cross_check_the_actual_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returned_generation: int,
) -> None:
    context = ScenarioContext(tmp_path, load_census(), CleanupRegistry())
    backend = Backend("sqlite", tmp_path)
    pins = iter((pin(2), pin(3)))
    monkeypatch.setattr(Backend, "publication", lambda *_args: next(pins))
    monkeypatch.setattr(rows, "pin_witness", lambda _home, value: (value, 12))
    monkeypatch.setattr(rows, "attempt_roots", lambda _home: set())
    monkeypatch.setattr(rows, "fresh_attempt", lambda *_args: True)
    monkeypatch.setattr(rows, "inventory_sha256", lambda *_args: "a" * 64)
    step = next(item for item in scenario_steps("local") if item.action == "refresh_repeat")
    # This valid report says not_recorded. The call says published: retaining
    # that disagreement is essential; the report must not supply both facts.
    report = encode_report(ResourceObserver(report_schema="cloe-resource-view-v2").report())
    returned = CallOutcome(detail=ReturnedPublication("published", returned_generation))
    plan = rows.refresh_plan(context, step, backend, lambda: (returned, report))
    plan.prepare()
    outcome = plan.call()
    if returned_generation != 3:
        with pytest.raises(AssertionError, match="first-use-refresh-return-pin-mismatch"):
            plan.observe(outcome)
    else:
        observed = plan.observe(outcome)
        assert observed.facts is not None and observed.facts["outcome"] == "published"
        assert list(observed.members.values()) == [report]


@pytest.mark.parametrize("count", [0, 2])
def test_revoke_facts_use_actual_effects_with_a_contradictory_report(
    monkeypatch: pytest.MonkeyPatch, count: int,
) -> None:
    monkeypatch.setattr(server_steps, "revoke_graph_lexical_generation",
                        lambda *_args, **_kw: SimpleNamespace(revoked_generation_count=count))
    after = SimpleNamespace(capability_state=server_steps.CapabilityState.UNAVAILABLE,
                            unavailable_reason="projection_absent")
    monkeypatch.setattr(server_steps, "_query", lambda *_args: after)
    step = next(item for item in scenario_steps("server") if item.action == "lexical_revoke")
    fake: Any = SimpleNamespace(config=object())
    plan = server_steps.lexical_revoke_row(fake, step)
    observed = plan.observe(plan.call())
    assert observed.facts is not None
    assert observed.facts["result"] == ("revoked" if count else None)
    assert observed.facts["revoked_generations"] == count


def test_server_selection_never_discards_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_module, "capture_cli", lambda _args: (
        0, '{"schema":"cloe-source-selection-v1"}', "unexpected diagnostic",
    ))
    with pytest.raises(AssertionError, match="first-use-cli-stderr-unexpected"):
        Backend("postgresql", tmp_path).select(tmp_path / "selection.json", ("core",), pin=True)


@pytest.mark.parametrize("action", ["init", "plan"])
def test_local_setup_and_plan_never_discard_child_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str,
) -> None:
    context = ScenarioContext(tmp_path, load_census(), CleanupRegistry())
    session = LocalSession(context)
    monkeypatch.setattr(LocalSession, "cli", lambda *_args: SimpleNamespace(
        returncode=0, stdout='{"result":"initialized"}\n', stderr="unexpected diagnostic",
    ))
    with pytest.raises(AssertionError, match="first-use-cli-stderr-unexpected"):
        getattr(session, action)()
