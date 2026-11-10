"""Every section-10.4 reconciliation category over a synthetic server-owner bundle."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

import pytest

from installed_experience_domains import SCHEMA_OBSERVATION, observation_name
from installed_experience_reconcile import check_bundle, reconcile
from installed_experience_records import (
    decode_intent, decode_observation, encode_index, encode_intent, encode_observation, index_payload,
)
from installed_experience_recipe import owner_scenarios
from installed_experience_validation import closure_categories
from installed_experience_source_identity import Preparation, owner_intent

ATTEMPT = "a" * 32
CENSUS = "5" * 64
SOURCE = {"S02": {"graph_catalog_sha256": "a" * 64, "control_catalog_sha256": "b" * 64},
          "S04": {"tools_sha256": "c" * 64}}
ORIGINS = {"base-stdlib": 2, "base-dynload": 1, "env-purelib": 1, "system-site": 1}
PURE_ORIGINS = {"base-stdlib": 2, "base-dynload": 1, "env-purelib": 1}
Mutator = Callable[[list[dict[str, Any]]], None]


def _intent() -> bytes:
    return owner_intent("server", Preparation("1" * 64, 3, "2" * 64, 10, 5, "3" * 64), SOURCE,
                        fixture_digest="4" * 64, candidate_census=CENSUS, python="3.13.12",
                        platform="aarch64")


def _rows(intent: bytes) -> list[dict[str, Any]]:
    decoded = decode_intent(intent)
    digest = hashlib.sha256(intent).hexdigest()
    rows = []
    for seq, row in enumerate(decoded["scenarios"], start=1):
        source = "filesystem" if row["id"] == "X01" else "child-stdout"
        rows.append({
            "schema": SCHEMA_OBSERVATION, "owner": "server", "attempt": ATTEMPT, "intent": digest,
            "scenario": row["id"], "seq": seq, "env_class": row["env_class"], "family": row["family"],
            "exit": 0, "outcome": "passed" if row["expectation"] == "pass" else "expected-refusal",
            "stderr_class": "empty",
            "facts": {key: {"value": value, "source": source} for key, value in row["expected"].items()},
            "origin_classes": ORIGINS if row["id"] == "S01" else None, "projection": None,
            "cleanup": "removed" if row["id"] == "X01" else "not-applicable", "failure_code": None,
        })
    return rows


def _bundle(mutate: Mutator | None = None, *, index: bool = True) -> dict[str, bytes]:
    intent = _intent()
    rows = _rows(intent)
    if mutate is not None:
        mutate(rows)
    files = {"intent.json": intent}
    for position, row in enumerate(rows, start=1):
        files[observation_name(position)] = encode_observation(row)
    if index:
        members = [[name, hashlib.sha256(data).hexdigest(), len(data)] for name, data in files.items()]
        files["index.json"] = encode_index(index_payload("server", ATTEMPT, hashlib.sha256(intent).hexdigest(),
                                                         members))
    return files


def _fact(rows: list[dict[str, Any]], scenario: str, key: str, **changes: Any) -> None:
    row = next(item for item in rows if item["scenario"] == scenario)
    row["facts"][key].update(changes)


def test_synthetic_bundle_is_accepted_and_host_check_binds_candidate() -> None:
    files = _bundle()
    verdict = reconcile(files)
    assert verdict.outcome == "accepted" and verdict.categories == ()
    assert verdict.counts == {"passed": 5} and len(verdict.rows) == 5
    files["verdict.json"] = verdict.encoded()
    assert check_bundle(files, candidate_source_sha256=CENSUS).outcome == "accepted"
    stale = check_bundle(files, candidate_source_sha256="6" * 64)
    assert stale.outcome == "rejected" and "binding-mismatch" in stale.categories


@pytest.mark.parametrize(("mutate", "category"), [
    (lambda rows: _fact(rows, "S01", "psycopg_version", value="3.2.12"), "fact-mismatch"),
    (lambda rows: _fact(rows, "S01", "psycopg_version", source="intent"), "witness-missing"),
    (lambda rows: rows[0]["facts"].pop("label"), "witness-missing"),
    (lambda rows: rows[0]["facts"].update(extra={"value": 1, "source": "child-stdout"}), "malformed"),
    (lambda rows: rows[0].update(outcome="failed", failure_code="child-exit-nonzero"), "unexpected-outcome"),
    (lambda rows: rows[0].update(exit=7), "unexpected-outcome"),
    (lambda rows: rows[0].update(env_class="pure-local"), "class-mismatch"),
    (lambda rows: rows[0].update(origin_classes={**ORIGINS, "checkout": 1}), "class-mismatch"),
    (lambda rows: rows[0].update(origin_classes=None), "witness-missing"),
    (lambda rows: rows[-1].update(cleanup="not-applicable"), "cleanup-missing"),
    (lambda rows: rows[-1].update(cleanup="retained-reported"), "unexpected-outcome"),
    (lambda rows: rows[1].update(intent="0" * 64), "binding-mismatch"),
    (lambda rows: rows[1].update(attempt="b" * 32), "binding-mismatch"),
])
def test_each_rejecting_category(mutate: Mutator, category: str) -> None:
    verdict = reconcile(_bundle(mutate))
    assert verdict.outcome == "rejected" and category in verdict.categories, verdict.categories


def test_order_duplicate_and_missing_cleanup() -> None:
    def swap(rows: list[dict[str, Any]]) -> None:
        rows[0], rows[1] = rows[1], rows[0]
        rows[0]["seq"], rows[1]["seq"] = 1, 2

    assert "order-violation" in reconcile(_bundle(swap)).categories

    def duplicate(rows: list[dict[str, Any]]) -> None:
        rows.insert(1, dict(rows[0], seq=2))
        for seq, row in enumerate(rows, start=1):
            row["seq"] = seq

    assert "duplicate" in reconcile(_bundle(duplicate)).categories

    def truncate(rows: list[dict[str, Any]]) -> None:
        del rows[-1]

    verdict = reconcile(_bundle(truncate))
    assert {"cleanup-missing", "incomplete-step"} <= set(verdict.categories)


def test_not_reached_or_unknown_is_incomplete_never_accepted() -> None:
    def unknown(rows: list[dict[str, Any]]) -> None:
        rows[2].update(outcome="unknown", failure_code="child-deadline", facts={})
        rows[3].update(outcome="not-reached", facts={})

    verdict = reconcile(_bundle(unknown))
    assert verdict.outcome == "incomplete" and verdict.categories == ("incomplete-step",)


def test_index_tampering_and_member_rules() -> None:
    files = _bundle()
    files["observation-02-1.json"] = files["observation-02-1.json"].replace(b'"exit":0', b'"exit":1')
    assert "binding-mismatch" in reconcile(files).categories
    assert "incomplete-step" in reconcile(_bundle(index=False)).categories
    stray = dict(_bundle(), **{"notes.txt": b"x"})
    assert reconcile(stray).categories == ("unsafe-member",)
    huge = dict(_bundle(), **{f"observation-{seq:02d}-1.json": b"x" for seq in range(6, 20)})
    assert reconcile(huge).categories == ("bound-exceeded",)
    assert reconcile({}).categories == ("binding-mismatch",)
    assert reconcile({"intent.json": b"{}\n"}).categories == ("malformed",)


def test_stale_recipe_and_tampered_verdict_are_rejected() -> None:
    files = _bundle()
    verdict = reconcile(files)
    files["verdict.json"] = verdict.encoded().replace(b'"accepted"', b'"rejected"')
    checked = check_bundle(files, candidate_source_sha256=CENSUS)
    assert checked.outcome == "rejected" and "binding-mismatch" in checked.categories
    rows = owner_scenarios("server")
    assert rows[-1].id == "X01"


def test_each_pure_owner_origin_row_rejudges_isolated_counts() -> None:
    for scenario, owner in (("L00", "local"), ("M00", "mcp"), ("R00", "migration")):
        row = {"id": scenario, "env_class": "pure-local"}
        observed = {"outcome": "passed", "env_class": "pure-local", "origin_classes": PURE_ORIGINS}
        assert closure_categories(row, observed) == set()
        observed["origin_classes"] = {**PURE_ORIGINS, "system-site": 1}
        assert closure_categories(row, observed) == {"class-mismatch"}


def test_exit_contract_allows_only_declared_partial_pack() -> None:
    from installed_experience_validation import exit_holds

    assert exit_holds({"id": "L06", "expectation": "pass"}, 3)
    assert not exit_holds({"id": "S03", "expectation": "pass"}, 3)
    assert not exit_holds({"id": "L10", "expectation": "refusal"}, 7)


@pytest.mark.parametrize("drift", ["recipe", "catalog"])
def test_rehashed_bundle_still_refuses_stale_recipe_or_catalog(drift: str) -> None:
    files = _bundle()
    payload = decode_intent(files["intent.json"])
    if drift == "recipe":
        payload["recipe_digest"] = "0" * 64
    else:
        payload["scenarios"][0]["expected"]["psycopg_version"] = "0.0.0"
    files["intent.json"] = encode_intent(payload)
    digest = hashlib.sha256(files["intent.json"]).hexdigest()
    for name in list(files):
        if name.startswith("observation-"):
            row = decode_observation(files[name])
            row["intent"] = digest
            files[name] = encode_observation(row)
    members = [[name, hashlib.sha256(data).hexdigest(), len(data)]
               for name, data in files.items() if name != "index.json"]
    files["index.json"] = encode_index(index_payload("server", ATTEMPT, digest, members))
    verdict = reconcile(files)
    assert verdict.outcome == "rejected" and "binding-mismatch" in verdict.categories
