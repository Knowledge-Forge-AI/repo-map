"""Frozen installed-experience catalog, digest, pins and section-6 rules."""

from __future__ import annotations

from dataclasses import replace

import pytest

from installed_experience_domains import OWNERS, InstalledError, observation_name, outcome_for
from installed_experience_pins import TE_MODULE_SHA256, TE_RECORD_SHA256
from installed_experience_recipe import (
    RECIPE, SOURCE, catalog, owner_scenarios, recipe_digest, resolve_expected, validate_recipe,
)
from installed_experience_rules import (
    classify_environment, closure_holds, label_refusal, module_violations, path_violations,
)

PURE_NORMAL = {"base-stdlib": 2, "base-dynload": 1, "env-purelib": 1, "owned-cwd": 1}
PURE_ISOLATED = {"base-stdlib": 2, "base-dynload": 1, "env-purelib": 1}
MODULES = {"common_lore_index": "env-purelib", "repomap_kg": "env-purelib", "typing_extensions": "env-purelib"}


def test_catalog_shape_owner_order_and_bounds() -> None:
    validate_recipe()
    assert len(RECIPE) == 45
    for owner in OWNERS:
        rows = owner_scenarios(owner)
        assert rows[-1].id == "X01" and len(rows) <= 16
        assert len({row.id for row in rows}) == len(rows)
    assert [row.id for row in owner_scenarios("environment")] == [
        "A01", "A02", "A03", "A04", "A05", "A06", "A07", "X01"]
    assert [row.id for row in owner_scenarios("server")][-1] == "X01"
    assert [row.id for row in owner_scenarios("local")][:2] == ["L00", "L01"]
    assert [row.id for row in owner_scenarios("mcp")][:2] == ["M00", "M01"]
    assert [row.id for row in owner_scenarios("migration")][:2] == ["R00", "R01"]
    assert len(owner_scenarios("local")) == 13
    with pytest.raises(InstalledError):
        owner_scenarios("release")


def test_declared_negatives_are_refusal_rows() -> None:
    refusals = {row.id for row in RECIPE if row.expectation == "refusal"}
    assert refusals == {"A05", "A06", "A07", "L10", "L11", "R07"}
    m06 = next(row for row in RECIPE if row.id == "M06")
    assert dict(m06.expected)["malformed_code"] == "-32700"


def test_digest_is_stable_and_binds_every_row() -> None:
    first = recipe_digest()
    assert first == recipe_digest() and len(first) == 64
    changed = (replace(RECIPE[0], action="candidate-assembly-2"), *RECIPE[1:])
    assert recipe_digest(changed) != first
    rows = catalog()
    assert rows[0][0] == "A01" and ["inventory_sha256", "source"] in rows[0][6]


def test_projection_constants_are_the_reviewed_parent_observation() -> None:
    a02 = dict(next(row for row in RECIPE if row.id == "A02").expected)
    assert a02["projection_module_sha256"] == TE_MODULE_SHA256
    assert a02["projection_record_sha256"] == TE_RECORD_SHA256
    assert TE_MODULE_SHA256 == "4040ca1a1ecbee00d1385c12a93084d1c5bd46f0b774f07e5ae7e91c4f55e696"
    assert TE_RECORD_SHA256 == "d7a220918ed91a6af1abf9508f734fe5d2c2f6b438ee519cc73ee4e60e6e665d"


def test_resolve_expected_requires_every_source_value() -> None:
    row = next(item for item in RECIPE if item.id == "L05")
    assert row.source_keys() == ("code_line",)
    resolved = resolve_expected(row, {"code_line": 15})
    assert resolved["code_line"] == 15 and resolved["code_kind"] == "python.function"
    with pytest.raises(InstalledError) as missing:
        resolve_expected(row, {})
    assert missing.value.category == "witness-missing"
    with pytest.raises(InstalledError):
        resolve_expected(row, {"code_line": 1.5})
    assert repr(SOURCE) == "SOURCE"


@pytest.mark.parametrize("mutation", [
    {"id": "Q01"}, {"action": "Bad Action"}, {"env_class": "release"}, {"family": "cli_module"},
    {"expectation": "skip"}, {"expected": ()}, {"expected": (("Bad-Key", 1),)},
    {"expected": (("value", 1.5),)}, {"expected": (("value", 1), ("value", 2))},
])
def test_invalid_catalog_rows_refuse(mutation: dict) -> None:
    broken = (replace(RECIPE[0], **mutation), *RECIPE[1:])
    with pytest.raises(InstalledError):
        validate_recipe(broken)


def test_cleanup_row_must_close_each_owner() -> None:
    environment = [row for row in RECIPE if row.owner == "environment"]
    reordered = (*environment[:-2], environment[-1], environment[-2],
                 *[row for row in RECIPE if row.owner != "environment"])
    with pytest.raises(InstalledError) as error:
        validate_recipe(reordered)
    assert error.value.category == "cleanup-missing"


def test_observation_names_and_outcome_precedence() -> None:
    assert observation_name(1) == "observation-01-1.json"
    assert observation_name(16) == "observation-16-1.json"
    with pytest.raises(InstalledError):
        observation_name(17)
    assert outcome_for(set()) == "accepted"
    assert outcome_for({"incomplete-step"}) == "incomplete"
    assert outcome_for({"incomplete-step", "fact-mismatch"}) == "rejected"


def test_pure_closure_admits_only_the_owned_cwd_on_the_normal_probe() -> None:
    assert path_violations("pure-local", PURE_NORMAL, isolated=False) == []
    assert path_violations("pure-local", PURE_ISOLATED, isolated=True) == []
    assert "isolated-cwd-entry" in path_violations("pure-local", PURE_NORMAL, isolated=True)
    assert "multiple-cwd-entries" in path_violations(
        "pure-local", {**PURE_NORMAL, "owned-cwd": 2}, isolated=False)
    assert "origin-checkout" in path_violations("pure-local", {**PURE_ISOLATED, "checkout": 1}, isolated=True)
    assert "foreign-path-class" in path_violations(
        "pure-local", {**PURE_ISOLATED, "system-site": 1}, isolated=True)
    assert "env-purelib-missing" in path_violations("pure-local", {"base-stdlib": 1}, isolated=True)
    assert path_violations("provisioned-server", {**PURE_ISOLATED, "system-site": 1}, isolated=True) == []
    assert "unknown-class" in path_violations("pure-local", {**PURE_ISOLATED, "tmp": 1}, isolated=True)


def test_module_resource_and_label_rules() -> None:
    assert module_violations("pure-local", MODULES, "env-data") == []
    assert module_violations("pure-local", {**MODULES, "common_lore_index": "checkout"}, "env-data") == [
        "module-origin"]
    assert module_violations("pure-local", MODULES, "checkout") == ["resource-origin"]
    assert module_violations("provisioned-server", {**MODULES, "typing_extensions": "system-site"},
                             "env-data") == []
    assert classify_environment(True, False) == "provisioned"
    assert classify_environment(False, True) == "provisioned"
    assert classify_environment(False, False) == "pure"
    assert label_refusal("pure-local", "provisioned") == "environment-class-mismatch"
    assert label_refusal("provisioned-server", "pure") == "environment-class-mismatch"
    assert label_refusal("pure-local", "pure") is None


def test_closure_requires_agreement_customize_and_absent_families() -> None:
    customize = {"sitecustomize": "absent", "usercustomize": "absent"}
    assert closure_holds("pure-local", PURE_NORMAL, PURE_ISOLATED, MODULES, "env-data", customize, True)
    assert not closure_holds("pure-local", PURE_NORMAL, {**PURE_ISOLATED, "env-purelib": 2}, MODULES,
                             "env-data", customize, True)
    assert not closure_holds("pure-local", PURE_NORMAL, PURE_ISOLATED, MODULES, "env-data",
                             {**customize, "sitecustomize": "other"}, True)
    assert not closure_holds("pure-local", PURE_NORMAL, PURE_ISOLATED, MODULES, "env-data", customize, False)
