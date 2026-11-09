"""Reproducible Server first-use workload over a disposable PostgreSQL cluster.

Deltas over ``first_use_server``: the exact recipe order including the expanded
lexical query row (symbol, generation-2 marker present, deleted generation-1
token absent), the repeat pin relation, the planned refusal's complete pin
digest, graph investigation support, ``m_c``/``r`` gating, a single cluster exit
timed in the cleanup row, and reconciled evidence with real negatives.
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
from repomap_test_support.first_use_workload_mutations import drop_member, flip_byte, mutated_categories
from repomap_test_support.first_use_workload_server_steps import build_server_plans
from repomap_test_support.first_use_workload_session import execute_scenario


def _facts(rows: list[dict[str, Any]], step: int, sub: int = 0) -> dict[str, Any]:
    row = next(item for item in rows if (item["step"], item["sub"]) == (step, sub))
    facts = row["facts"]
    assert isinstance(facts, dict)
    return facts


def test_first_use_workload_server_recipe_reconciles_with_real_negatives(tmp_path: Path) -> None:
    bundle, verdict, _run = execute_scenario("server", tmp_path, build_server_plans)
    assert verdict.outcome == "accepted", verdict.categories
    assert bundle.parent.name == BUNDLE_CHILD
    rows = verdict.observations
    assert [(row["step"], row["sub"], row["action"]) for row in rows] == [
        (1, 0, "census_verify"), (2, 0, "migrate"), (3, 0, "sealing_plan"), (4, 0, "refresh_cold"),
        (5, 0, "pack_current"), (6, 0, "refresh_repeat"), (7, 0, "refresh_generation"),
        (8, 0, "stale_investigation"), (9, 0, "planned_refusal"), (10, 0, "lexical_build"),
        (11, 0, "lexical_query"), (11, 1, "lexical_query"), (11, 2, "lexical_query"),
        (12, 0, "lexical_revoke"), (13, 0, "cleanup"),
    ]
    assert verdict.counts == {"pass": 14, "expected_refusal": 1}

    assert [_facts(rows, step)["pin_after"]["generation"] for step in (4, 6, 7)] == [1, 2, 3]
    assert _facts(rows, 9)["pin_after"] == _facts(rows, 9)["pin_before"]
    assert _facts(rows, 9)["code"] == "resource_budget_exceeded"
    investigation = _facts(rows, 8)
    assert investigation["investigation_supported"] is True
    assert {tag: status for tag, status in investigation["status"]}["stale"] == "stale"

    symbol, marker, absent = (_facts(rows, 11, sub) for sub in (0, 1, 2))
    assert ["core", "pkg/pipeline.py"] in symbol["observed_locations"]
    assert ["core", "pkg/gen2_extension.py"] in marker["observed_locations"]
    assert ["core", "pkg/legacy_deprecated.py"] not in absent["observed_locations"]
    revoke = _facts(rows, 12)
    assert revoke["revoked_generations"] >= 1 and revoke["unavailable_reason"] == "projection_absent"
    assert _facts(rows, 13) == {"leftovers": [], "forbidden_events": None, "shim_invocations": None}
    assert type(rows[-1]["spans"]["cleanup_ns"]) is int

    census, intent = load_census(), current_intent()
    assert check_bundle(intent, read_bundle(bundle), census).outcome == "accepted"
    output = io.StringIO()
    assert run(["check", "--bundle", str(bundle)], out=output, err=io.StringIO()) == EXIT_ACCEPTED
    assert output.getvalue() == "accepted server -\n"
    for index, (mutation, category) in enumerate(((flip_byte(), "tampered_member"),
                                                  (drop_member(), "partial_bundle"))):
        found = mutated_categories(bundle, tmp_path / f"negative-{index}", mutation, intent, census)
        assert category in found, found
