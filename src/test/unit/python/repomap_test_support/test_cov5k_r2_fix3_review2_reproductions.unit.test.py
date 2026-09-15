from __future__ import annotations

import subprocess

import pytest

from repomap_test_support.test_cov5k_r2_fix2_catalog import CatalogEntry, build_closed_catalog
from repomap_kg.storage.authority import PublicationGenerations
from scale15_terminal_contracts import ExpectedRefreshAuthority
from repomap_test_support.test_cov5k_r2_fix2_evidence import ExecutorEvidenceError
from repomap_test_support.test_cov5k_r2_groupa_contract import group_a_public_context
from repomap_test_support.test_cov5k_r2_fix2_observer import (
    execute_observer_request,
    execute_observer_schedule,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation import (
    execute_preparation_state_path,
)
from repomap_test_support.test_cov5k_r2_fix2_registry import build_executor_registry
from repomap_test_support.test_cov5k_r2_fix2_runtime import (
    execute_container_rss_equivalence,
    execute_runtime_driver_read,
)


def _entries(group: str, operation: str):
    return tuple(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == group and entry.operation_kind == operation
    )


def _observed(evidence):
    return dict(evidence.observed_fields)


def test_review2_group_g_families_must_change_product_observations() -> None:
    representatives: dict[str, CatalogEntry] = {}
    for entry in _entries("G", "observer_schedule"):
        family = dict(entry.parameter_values)["schedule"]
        assert isinstance(family, str)
        representatives.setdefault(family, entry)
    product_shapes = {
        family: tuple(
            (key, value)
            for key, value in execute_observer_schedule(entry).observed_fields
            if key
            not in {
                "enacted_schedule",
                "enacted_schedule_index",
                "execution_parameter_digest",
            }
        )
        for family, entry in representatives.items()
    }
    assert len(set(product_shapes.values())) == 16


def test_review2_group_f_dispatch_enacts_deadline_and_product_identity() -> None:
    first = _entries("F", "observer_request")[0]
    observed = _observed(execute_observer_request(first))
    assert observed["request_deadline_ms"] == dict(first.parameter_values)[
        "request_deadline_ms"
    ]
    assert observed["operation_identity"] != first.authority_id
    assert observed["dispatch_timestamp_ns"] > 0


def test_review2_psql_categories_come_from_process_evidence() -> None:
    entries = _entries("D", "runtime_driver_read")
    psql_entries = [entry for entry in entries if dict(entry.parameter_values)["driver"] == "psql"]
    diagnostics = {
        "success": (0, "", ""),
        "class_08": (1, "", "SQLSTATE 08006 connection failure"),
        "unavailable": (127, "", "psql: command not found"),
        "authentication": (2, "", "FATAL: password authentication failed"),
        "semantic_schema": (3, "", 'ERROR: relation "missing" does not exist'),
        "transport_refusal": (4, "", "connection refused"),
    }
    observed = set()
    for entry in psql_entries:
        expected = dict(entry.parameter_values)["failure_category"]
        returncode, stdout, stderr = diagnostics[expected]

        def runner(*_args, **_kwargs):
            return subprocess.CompletedProcess((), returncode, stdout, stderr)

        evidence = execute_runtime_driver_read(
            entry,
            psql_args=(),
            expected_authority=ExpectedRefreshAuthority(
                repository_identity="repo1:public-fixture", repository_name="public-fixture",
                generations=PublicationGenerations(
                    "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer",
                ),
                execution_mode="direct", zero_state_first_publication=True,
                expected_family_counts={},
            ),
            psql_runner=runner,
        )
        observed.add(_observed(evidence)["failure_category"])
    assert observed == set(diagnostics)


def test_review2_container_pairs_enter_registered_runtime_owner(monkeypatch) -> None:
    entry = _entries("D", "container_rss_equivalence")[0]
    import repomap_test_support.test_cov5k_r2_fix2_runtime as runtime

    entered = 0

    def owner(*_args, **_kwargs):
        nonlocal entered
        entered += 1
        return object()

    monkeypatch.setattr(runtime, "capture_runtime_identity", owner)
    with pytest.raises(ExecutorEvidenceError, match="owner source path"):
        execute_container_rss_equivalence(
            entry,
            api_reader=lambda: 1,
            diagnostic_reader=lambda: 1,
        )
    assert entered == 1


def test_review2_group_a_schema_and_terminal_projection_are_observable(tmp_path) -> None:
    entries = _entries("A", "preparation_state_path")
    success = next(entry for entry in entries if entry.case_id == "attempt_one_success")
    refused = next(entry for entry in entries if entry.case_id == "final_refused_projection")
    success_result = execute_preparation_state_path(tmp_path / "success", success)
    refused_result = execute_preparation_state_path(tmp_path / "refused", refused)
    contexts = (
        group_a_public_context(success_result),
        group_a_public_context(refused_result),
    )
    assert set(_observed(success_result)) == set(success.observation_schema), contexts
    success_projection = _observed(success_result)["final_projection_category"]
    refused_projection = _observed(refused_result)["final_projection_category"]
    assert success_projection != refused_projection, contexts
    event_names = {name for name, _value in success_result.observed_product_events}
    assert "forced_tail_stdout_closed" in event_names, contexts
    assert "preparation_state_history" in event_names, contexts


def test_review2_enacted_parameters_are_independently_observed() -> None:
    entry = _entries("G", "observer_schedule")[0]
    evidence = execute_observer_schedule(entry)
    assert evidence.enacted_parameters is not entry.parameter_values
    assert evidence.observed_enacted_parameter_digest == evidence.frozen_parameter_digest


def test_review2_runtime_generic_executor_insertion_is_refused(monkeypatch) -> None:
    import repomap_test_support.test_cov5k_r2_fix2_runtime as runtime

    monkeypatch.setattr(runtime, "execute_failure_causality", lambda _entry: None)
    with pytest.raises(Exception, match="executor|owner|code"):
        build_executor_registry()


def test_review2_sibling_campaign_uses_accepted_preemption_oracle() -> None:
    from pathlib import Path

    path = Path(
        "src/test/int/python/repomap_kg/storage/"
        "scale28_backend_observer_lifetime.int.test.py"
    )
    source = path.read_text(encoding="utf-8")
    start = source.index("def test_scale28_ten_mixed_observer_success_and_failure_campaigns")
    end = source.index("\ndef test_scale28_hybrid_prior_publication", start)
    assert "_assert_observer_deadline_preemption" in source[start:end]
