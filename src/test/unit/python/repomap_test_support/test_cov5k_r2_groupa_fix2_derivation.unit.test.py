from __future__ import annotations

import ast
import inspect

import pytest

from repomap_test_support.test_cov5k_r2_groupa_contract import (
    derive_expected_group_a_state_history,
    derive_forced_tail_policy,
    derive_observed_cleanup_disposition,
    derive_observed_group_a_contract_category,
    derive_observed_retry_disposition,
)


def _history(attempts: int, *, released: bool) -> tuple[str, ...]:
    history = ["unprepared"]
    history.extend("preparing" for _ in range(attempts))
    if released:
        history.extend(
            (
                "worker_settled",
                "freshness_validated",
                "final_readiness_open",
                "transient_ownership_clear",
                "stable_sample_one",
                "stable_sample_two",
                "ready_to_release",
                "child_released",
            )
        )
    else:
        history.append("refused")
    history.append("settled")
    return tuple(history)


@pytest.mark.parametrize(
    ("outcomes", "categories", "boundaries", "projection", "expected"),
    (
        (("success",), ("none",), ("none",), "released", "success"),
        (
            ("failure", "success"),
            ("resource_unavailable", "none"),
            ("container_rss_read", "none"),
            "released",
            "success",
        ),
        (
            ("failure", "success"),
            ("preparation_timeout", "none"),
            ("worker", "none"),
            "released",
            "success",
        ),
        (
            ("failure", "failure"),
            ("worker_failed", "worker_failed"),
            ("worker", "worker"),
            "refused",
            "failed",
        ),
        (
            ("failure", "failure"),
            ("worker_failed", "preparation_timeout"),
            ("worker", "worker"),
            "refused",
            "failed",
        ),
        (
            ("failure", "failure"),
            ("preparation_timeout", "worker_failed"),
            ("worker", "worker"),
            "refused",
            "failed",
        ),
        (
            ("failure", "failure"),
            ("preparation_timeout", "preparation_timeout"),
            ("worker", "worker"),
            "refused",
            "failed",
        ),
        (
            ("failure",),
            ("preparation_timeout",),
            ("worker",),
            "refused",
            "refused",
        ),
        (("success",), ("none",), ("none",), "refused", "refused"),
    ),
)
def test_runtime_contract_category_covers_all_group_a_shapes(
    outcomes: tuple[str, ...],
    categories: tuple[str, ...],
    boundaries: tuple[str, ...],
    projection: str,
    expected: str,
) -> None:
    history = derive_expected_group_a_state_history(
        tuple(zip(outcomes, categories, boundaries, strict=True)), projection
    )
    assert history is not None
    assert derive_observed_group_a_contract_category(
        outcomes,
        categories,
        boundaries,
        history,
        projection,
        2,
    ) == expected


def test_runtime_contract_category_rejects_shape_beyond_frozen_policy() -> None:
    assert derive_observed_group_a_contract_category(
        ("failure", "failure", "failure"),
        ("worker_failed",) * 3,
        ("worker",) * 3,
        _history(3, released=False),
        "refused",
        2,
    ) == "unrecognized"


def test_parent_settlement_category_is_derived_from_raw_facts() -> None:
    outcomes = ("failure",)
    categories = ("cleanup_limitation",)
    boundaries = ("process_settlement",)
    history = _history(1, released=False)
    assert derive_observed_group_a_contract_category(
        outcomes,
        categories,
        boundaries,
        history,
        "refused",
        2,
    ) == "refused"
    assert derive_observed_retry_disposition(
        outcomes,
        categories,
        boundaries,
        history,
    ) == "retry_not_observed_after_parent_settlement_failure"


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    (
        (("success",), "retry_not_applicable_after_success"),
        (("failure",), "retry_not_observed_after_failure"),
        (("failure", "success"), "retry_observed"),
    ),
)
def test_retry_disposition_is_runtime_derived(
    outcomes: tuple[str, ...], expected: str
) -> None:
    categories = tuple(
        "none" if outcome == "success" else "worker_failed"
        for outcome in outcomes
    )
    boundaries = tuple(
        "none" if outcome == "success" else "worker"
        for outcome in outcomes
    )
    assert derive_observed_retry_disposition(
        outcomes,
        categories,
        boundaries,
        _history(len(outcomes), released=outcomes[-1] == "success"),
    ) == expected


def test_tail_policy_is_derived_from_raw_categories() -> None:
    assert derive_forced_tail_policy(("none",)) == (False, False)
    assert derive_forced_tail_policy(("preparation_timeout",)) == (True, False)
    assert derive_forced_tail_policy(
        ("preparation_timeout", "preparation_timeout")
    ) == (True, True)
    assert derive_forced_tail_policy(("cleanup_limitation",)) == (False, False)


@pytest.mark.parametrize(
    ("categories", "expected"),
    (
        (("none",), "not_required"),
        (("resource_unavailable", "none"), "completed"),
        (("cleanup_limitation",), "limited"),
    ),
)
def test_cleanup_disposition_is_runtime_derived(
    categories: tuple[str, ...], expected: str
) -> None:
    assert derive_observed_cleanup_disposition(categories) == expected


@pytest.mark.parametrize(
    "helper",
    (
        derive_observed_retry_disposition,
        derive_observed_group_a_contract_category,
        derive_forced_tail_policy,
        derive_observed_cleanup_disposition,
    ),
)
def test_runtime_derivers_do_not_reference_expectation_authorities(helper) -> None:
    tree = ast.parse(inspect.getsource(helper))
    references = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert references.isdisjoint(
        {"scenario_id", "case_id", "catalog", "expected_contract_category"}
    )
