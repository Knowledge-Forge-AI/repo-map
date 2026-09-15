"""REPOMAP-CI0B-FIX1 exhaustive profile in the closed suite/profile mapping."""

from __future__ import annotations

import pytest

from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_runner_profile import (
    RunnerProfileError,
    resolve_runner_profile,
)


def resolve(
    suite: str = "staging",
    *,
    requested_profile: HygieneProfile | None = HygieneProfile.EXHAUSTIVE,
    declared_complete_gates: int = 1,
    campaign_plan_id: str | None = None,
    operator_attested_exclusive: bool = True,
    operator_attested_pressure_degradation: bool = True,
):
    return resolve_runner_profile(
        suite,
        requested_profile=requested_profile,
        declared_complete_gates=declared_complete_gates,
        campaign_plan_id=campaign_plan_id,
        operator_attested_exclusive=operator_attested_exclusive,
        operator_attested_pressure_degradation=operator_attested_pressure_degradation,
    )


def test_complete_suite_accepts_the_exhaustive_profile():
    selection = resolve()

    assert selection.selected_profile is HygieneProfile.EXHAUSTIVE
    assert selection.explicit_selection_required is True
    assert selection.declared_complete_gates == 1


def test_exhaustive_complete_work_requires_exactly_one_gate():
    for gates in (0, 2):
        with pytest.raises(RunnerProfileError, match="exactly one gate"):
            resolve(declared_complete_gates=gates)


@pytest.mark.parametrize(
    "suite", ["unit", "int", "smoke", "build", "qualification"]
)
def test_exhaustive_profile_cannot_run_non_complete_work(suite):
    with pytest.raises(RunnerProfileError):
        resolve(suite=suite, declared_complete_gates=0)


def test_exhaustive_rejects_a_campaign_plan_identity():
    with pytest.raises(RunnerProfileError, match="requires qualification"):
        resolve(campaign_plan_id="REPOMAP-CI0B")


def test_complete_suite_still_accepts_heavy_and_qualification():
    heavy = resolve(requested_profile=HygieneProfile.HEAVY)
    qualification = resolve(
        requested_profile=HygieneProfile.QUALIFICATION,
        campaign_plan_id="REPOMAP-CI0B",
        declared_complete_gates=2,
    )

    assert heavy.selected_profile is HygieneProfile.HEAVY
    assert qualification.selected_profile is HygieneProfile.QUALIFICATION


def test_complete_suite_still_refuses_unrelated_profiles():
    for profile in (
        HygieneProfile.ORDINARY,
        HygieneProfile.INTEGRATION,
        HygieneProfile.BUILD,
    ):
        with pytest.raises(RunnerProfileError):
            resolve(requested_profile=profile)


def test_complete_suite_still_requires_an_explicit_profile():
    with pytest.raises(RunnerProfileError, match="explicit hygiene profile"):
        resolve(requested_profile=None)


def test_system_suite_profile_resolution():
    system_exhaustive = resolve(
        suite="system",
        requested_profile=HygieneProfile.EXHAUSTIVE,
        declared_complete_gates=1,
    )
    assert system_exhaustive.selected_profile is HygieneProfile.EXHAUSTIVE
    assert system_exhaustive.explicit_selection_required is True

    system_heavy = resolve(
        suite="system",
        requested_profile=HygieneProfile.HEAVY,
        declared_complete_gates=0,
    )
    assert system_heavy.selected_profile is HygieneProfile.HEAVY

    with pytest.raises(RunnerProfileError, match="exactly one gate"):
        resolve(
            suite="system",
            requested_profile=HygieneProfile.EXHAUSTIVE,
            declared_complete_gates=0,
        )

    with pytest.raises(RunnerProfileError, match="zero declared gates"):
        resolve(
            suite="system",
            requested_profile=HygieneProfile.HEAVY,
            declared_complete_gates=1,
        )

    for profile in (
        HygieneProfile.ORDINARY,
        HygieneProfile.INTEGRATION,
        HygieneProfile.BUILD,
        HygieneProfile.QUALIFICATION,
    ):
        with pytest.raises(RunnerProfileError, match="system suite requires exhaustive or heavy"):
            resolve(suite="system", requested_profile=profile)
