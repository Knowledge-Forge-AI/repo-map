"""Reproducible Local first-use workload: the frozen recipe, reconciled evidence, real negatives.

Deltas over ``first_use_local``: the exact recipe order, the repeat pin relation
(an unchanged tree still publishes before+1), replay preparation committing
one armed generation that the replay call leaves unchanged, ``m_c``/``r``
gating on a fresh attempt store, scoped spans/CPU, cleanup accounting and an
inspectable bundle that a pure reconciler accepts and its mutated copies do
not. Incumbent JSON, table and provenance checks are not re-asserted.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from first_use_workload_bundle import read_bundle
from first_use_workload_census import load_census
from first_use_workload_cli_views import EXIT_ACCEPTED, run
from first_use_workload_reconcile import check_bundle
from first_use_workload_source_identity import current_intent
from repomap_test_support.first_use_workload_driver import BUNDLE_CHILD
from repomap_test_support.first_use_workload_local_steps import build_local_plans
from repomap_test_support.first_use_workload_mutations import drop_member, flip_byte, mutated_categories
from repomap_test_support.first_use_workload_session import execute_scenario


def _facts(rows: list[dict[str, Any]], step: int) -> dict[str, Any]:
    row = next(item for item in rows if (item["step"], item["sub"]) == (step, 0))
    facts = row["facts"]
    assert isinstance(facts, dict)
    return facts


def test_first_use_workload_local_recipe_reconciles_with_real_negatives(tmp_path: Path) -> None:
    bundle, verdict, _run = execute_scenario("local", tmp_path, build_local_plans)
    assert verdict.outcome == "accepted", verdict.categories
    assert bundle.parent.name == BUNDLE_CHILD
    rows = verdict.observations
    assert [(row["step"], row["action"], row["result"]) for row in rows] == [
        (1, "census_verify", "pass"), (2, "sqlite_init", "pass"), (3, "sealing_plan", "pass"),
        (4, "refresh_cold", "pass"), (5, "pack_current", "pass"), (6, "refresh_repeat", "pass"),
        (7, "refresh_generation", "pass"), (8, "pack_stale", "pass"),
        (9, "planned_refusal", "expected_refusal"), (10, "missing_refusal", "expected_refusal"),
        (11, "refresh_recovery", "pass"), (12, "replay_refresh", "pass"), (13, "cleanup", "pass"),
    ]

    # Repeat, generation and recovery each publish exactly before+1; refusals keep the pin.
    generations = [_facts(rows, step)["pin_after"]["generation"] for step in (4, 6, 7, 11)]
    assert generations == [1, 2, 3, 4]
    assert _facts(rows, 9)["pin_after"] == _facts(rows, 9)["pin_before"]
    assert _facts(rows, 10)["pin_after"] == _facts(rows, 9)["pin_after"]
    replay = _facts(rows, 12)
    assert replay["preparation_pin"]["generation"] == 5 and replay["pin_after"] == replay["preparation_pin"]
    assert replay["outcome"] == "reconciled_replay" and replay["attempt_root_fresh"] is None
    assert all(_facts(rows, step)["attempt_root_fresh"] is True for step in (4, 6, 7, 11))
    assert _facts(rows, 13) == {"leftovers": [], "forbidden_events": 0, "shim_invocations": 0}

    # Spans are scoped per phase; CLI children are reaped inside the call span.
    for row in rows:
        assert all(type(value) is int for value in row["spans"].values()), row["step"]
    assert all(rows[index]["cpu"]["waited_descendants_ns"] is not None for index in (1, 3, 5))

    census, intent = load_census(), current_intent()
    assert check_bundle(intent, read_bundle(bundle), census).outcome == "accepted"
    out = io.StringIO()
    assert run(["check", "--bundle", str(bundle)], out=out, err=io.StringIO()) == EXIT_ACCEPTED
    assert out.getvalue() == "accepted local -\n"

    for index, (mutation, category) in enumerate(((flip_byte(), "tampered_member"),
                                                  (drop_member(), "partial_bundle"))):
        found = mutated_categories(bundle, tmp_path / f"negative-{index}", mutation, intent, census)
        assert category in found, found
    assert check_bundle(intent, read_bundle(bundle), census).outcome == "accepted"
