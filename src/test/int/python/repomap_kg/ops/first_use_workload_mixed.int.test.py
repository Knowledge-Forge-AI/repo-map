"""Reproducible mixed first-use workload on SQLite and PostgreSQL homes of one working copy.

Deltas over ``first_use_mixed``: per-home snapshot equivalence as distinct
per-backend facts, alias-qualified packs for implementation, docs and messages
on each current pin, subset scope limited to ``core`` on both backends, the
metadata-only privacy refusal with its complete pin digest, and all six real
bundle negatives of contract section 9.3 on the only two-backend bundle.
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
from repomap_test_support.first_use_workload_mixed_steps import build_mixed_plans
from repomap_test_support.first_use_workload_mutations import (
    drop_member, flip_byte, mutated_categories, other_attempt, reencode_intent, reencode_observation,
)
from repomap_test_support.first_use_workload_session import execute_scenario


def _facts(rows: list[dict[str, Any]], step: int) -> dict[str, Any]:
    row = next(item for item in rows if (item["step"], item["sub"]) == (step, 0))
    facts = row["facts"]
    assert isinstance(facts, dict)
    return facts


def test_first_use_workload_mixed_recipe_reconciles_with_all_real_negatives(tmp_path: Path) -> None:
    bundle, verdict, _run = execute_scenario("mixed", tmp_path, build_mixed_plans)
    assert verdict.outcome == "accepted", verdict.categories
    assert bundle.parent.name == BUNDLE_CHILD
    rows = verdict.observations
    assert [(row["step"], row["backend"], row["action"]) for row in rows] == [
        (1, "mixed", "census_verify"), (2, "sqlite", "sqlite_initial"),
        (3, "postgresql", "postgres_initial"), (4, "mixed", "snapshot_equivalence"),
        (5, "mixed", "pack_mixed"), (6, "mixed", "pack_subset"), (7, "mixed", "privacy_refusal"),
        (8, "mixed", "cleanup"),
    ]

    snapshots = _facts(rows, 4)
    assert set(snapshots) == {"sqlite", "postgresql"}
    for backend, facts in snapshots.items():
        assert facts["backend"] == backend
        assert facts["manifest_snapshot_sha256"] == facts["incumbent_snapshot_sha256"]
    assert snapshots["sqlite"]["inventory_sha256"] == snapshots["postgresql"]["inventory_sha256"]

    packs = _facts(rows, 5)
    for backend in ("sqlite", "postgresql"):
        tags = {tag for tag, _alias, _rel in packs[backend]["observed_locations"]}
        assert ["implementation", "core", "pkg/pipeline.py"] in packs[backend]["observed_locations"]
        assert tags <= {"implementation", "docs", "messages"}
    subset = _facts(rows, 6)
    for backend in ("sqlite", "postgresql"):
        assert {alias for _tag, alias, _rel in subset[backend]["observed_locations"]} == {"core"}

    privacy = _facts(rows, 7)["postgresql"]
    assert privacy["code"] in {"graph_privacy_not_authorized", "retention_not_authorized"}
    assert privacy["pin_after"] == privacy["pin_before"]
    assert _facts(rows, 8) == {"leftovers": [], "forbidden_events": 0, "shim_invocations": 0}

    census, intent = load_census(), current_intent()
    assert check_bundle(intent, read_bundle(bundle), census).outcome == "accepted"
    output = io.StringIO()
    assert run(["check", "--bundle", str(bundle)], out=output, err=io.StringIO()) == EXIT_ACCEPTED
    assert output.getvalue() == "accepted mixed -\n"
    negatives = (
        (flip_byte(), "tampered_member"),
        (drop_member(), "partial_bundle"),
        (reencode_observation("observation-03-0.json", attempt=other_attempt()), "cross_attempt"),
        (reencode_observation("observation-02-0.json", backend="postgresql"), "cross_backend"),
        (reencode_intent("candidate_census"), "candidate_mismatch"),
        (reencode_intent("product_digest"), "candidate_mismatch"),
    )
    for index, (mutation, category) in enumerate(negatives):
        found = mutated_categories(bundle, tmp_path / f"negative-{index}", mutation, intent, census)
        assert category in found, (index, found)
    assert check_bundle(intent, read_bundle(bundle), census).outcome == "accepted"
