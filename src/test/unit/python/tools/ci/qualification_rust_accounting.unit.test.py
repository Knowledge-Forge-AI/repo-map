"""Role totals retain command-attempt scopes and unobservable values."""

import copy
from typing import Any

import pytest

from ci.qualification_rust_accounting import (
    AccountingGap, NAMES, component_accounting, refusal_accounting, require_component_accounting,
)
from common_lore_index.extractors.rust_pilot.docker_boundary import ResidueSnapshot


def _group(containers: int, parses: int, commands: int, checked: bool = True) -> dict[str, Any]:
    values = {"containers": containers, "parses": parses, "commands": commands}
    return {name: {"value": values.get(name, 0) if checked or name in values else None,
                   "basis": "journal-derived", "cross_checked": checked} for name in NAMES}


def _native() -> dict[str, Any]:
    return {"counters": _group(13, 13, 100), "containment": {"counters": _group(4, 0, 50)},
            "preflights": {"oversized": {"passed": True, "counters": _group(1, 1, 10)},
                           "tamper": {"passed": True, "counters": _group(1, 0, 10)},
                           "missing": {"passed": True, "counters": _group(0, 0, 0, False)}}}


def test_all_independent_roles_count_and_inputs_remain_inert() -> None:
    native = _native()
    before = copy.deepcopy(native)
    accounting = component_accounting(native)
    assert native == before
    totals = accounting["totals"]
    assert totals["containers"]["value"] == 19
    assert totals["parses"]["value"] == 14
    assert totals["commands"]["value"] == 170
    assert totals["containers"]["scope"] == "all_rust_component_owned_run_groups"
    assert totals["containers"]["cross_checked"] is False
    assert "qualified" not in accounting


def test_unknown_role_resources_never_become_zero() -> None:
    accounting = component_accounting(_native())
    for name in ("builds", "pulls", "images", "volumes"):
        assert accounting["totals"][name]["value"] is None
        assert accounting["totals"][name]["cross_checked"] is False
        assert accounting["totals"][name]["unavailable_reason"] == "one_or_more_role_counters_unobservable"
        assert accounting["groups"]["source_controller"][name]["value"] == 0


@pytest.mark.parametrize("fault", ["unpassed", "boolean", "missing"])
def test_inconsistent_metrics_refuse_without_admission_credit(fault: str) -> None:
    native = _native()
    if fault == "unpassed":
        native["preflights"]["oversized"]["passed"] = False
    elif fault == "boolean":
        native["counters"]["containers"]["value"] = True
    else:
        native["containment"]["counters"].pop("commands")
    with pytest.raises(ValueError):
        component_accounting(native)


def test_unknown_totals_refuse_qualification_without_becoming_zero() -> None:
    with pytest.raises(AccountingGap) as refused:
        require_component_accounting(_native())
    assert refused.value.code == "aggregate_accounting_unproven"
    assert refused.value.evidence["accounting"]["totals"]["builds"]["value"] is None


@pytest.mark.parametrize("fault", ["builds", "pulls", "images", "volumes", "unchecked"])
def test_all_role_nonzero_or_unchecked_effects_refuse(fault: str) -> None:
    native = _native()
    native["preflights"]["missing"]["counters"] = _group(0, 0, 6)
    if fault == "unchecked":
        native["containment"]["counters"]["commands"]["cross_checked"] = False
    else:
        native["containment"]["counters"][fault]["value"] = 1
    with pytest.raises(AccountingGap):
        require_component_accounting(native)


def test_resource_observer_counts_its_commands_and_preserves_unknown_raw_audit() -> None:
    raw = _group(0, 0, 0, False)
    before_raw = copy.deepcopy(raw)
    run_id = "rp1.0123456789abcdef"
    queries = (("image", "ls", "-q", "--no-trunc"), ("volume", "ls", "-q"),
               ("container", "ls", "-a", "-q", "--no-trunc", "--filter",
                "label=org.repomap.rust-pilot.run=" + run_id))
    resources = ResidueSnapshot(frozenset({"synthetic-image"}), frozenset(), frozenset())
    observed = refusal_accounting(raw, (), queries + queries, resources, resources, run_id)
    assert raw == before_raw and raw["builds"]["value"] is None
    assert observed["commands"]["value"] == 6
    assert all(row["cross_checked"] is True for row in observed.values())
    native = _native()
    native["preflights"]["missing"]["counters"] = observed
    assert require_component_accounting(native)["totals"]["builds"]["value"] == 0
    changed = ResidueSnapshot(frozenset(), frozenset(), frozenset())
    with pytest.raises(AccountingGap):
        refusal_accounting(raw, (), queries + queries, resources, changed, run_id)
    with pytest.raises(AccountingGap):
        refusal_accounting(raw, (("build",),), queries + queries, resources, resources, run_id)
