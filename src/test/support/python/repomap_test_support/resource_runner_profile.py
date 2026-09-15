"""Closed runner-suite to hygiene-profile resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass

from repomap_test_support.resource_hygiene_policy import HygieneProfile


_CAMPAIGN_PLAN = re.compile(r"^[A-Z][A-Z0-9-]{2,127}$")


class RunnerProfileError(RuntimeError):
    """The requested suite and hygiene authority are incompatible."""


@dataclass(frozen=True)
class RunnerProfileSelection:
    selected_profile: HygieneProfile
    explicit_selection_required: bool
    declared_complete_gates: int
    campaign_plan_id: str | None
    operator_attested_exclusive: bool
    operator_attested_pressure_degradation: bool


def resolve_runner_profile(
    suite: str,
    *,
    requested_profile: HygieneProfile | None,
    declared_complete_gates: int,
    campaign_plan_id: str | None,
    operator_attested_exclusive: bool,
    operator_attested_pressure_degradation: bool,
) -> RunnerProfileSelection:
    if suite not in {"unit", "int", "smoke", "staging", "system", "build", "qualification"}:
        raise RunnerProfileError("unsupported runner work class")
    if type(declared_complete_gates) is not int or declared_complete_gates < 0:
        raise RunnerProfileError("declared complete-gate count is invalid")
    if type(operator_attested_exclusive) is not bool:
        raise RunnerProfileError("exclusive attestation is invalid")
    if type(operator_attested_pressure_degradation) is not bool:
        raise RunnerProfileError("pressure-degradation attestation is invalid")
    if campaign_plan_id is not None and (
        type(campaign_plan_id) is not str or not _CAMPAIGN_PLAN.fullmatch(campaign_plan_id)
    ):
        raise RunnerProfileError("campaign-plan identity is invalid")

    explicit_required = suite in {"staging", "system", "build", "qualification"}
    if requested_profile is None:
        if explicit_required:
            raise RunnerProfileError("work class requires an explicit hygiene profile")
        selected = (
            HygieneProfile.ORDINARY
            if suite == "unit"
            else HygieneProfile.INTEGRATION
        )
    else:
        selected = HygieneProfile(requested_profile)

    if suite == "staging" and selected not in {
        HygieneProfile.EXHAUSTIVE,
        HygieneProfile.HEAVY,
        HygieneProfile.QUALIFICATION,
    }:
        raise RunnerProfileError(
            "staging suite requires exhaustive, heavy, or qualification"
        )
    if suite == "system" and selected not in {
        HygieneProfile.EXHAUSTIVE,
        HygieneProfile.HEAVY,
    }:
        raise RunnerProfileError(
            "system suite requires exhaustive or heavy"
        )
    if suite == "build" and selected is not HygieneProfile.BUILD:
        raise RunnerProfileError("build work requires the build profile")
    if suite == "qualification" and selected is not HygieneProfile.QUALIFICATION:
        raise RunnerProfileError("qualification work requires the qualification profile")
    if suite in {"int", "smoke", "staging", "system"} and selected is HygieneProfile.ORDINARY:
        raise RunnerProfileError("integration work cannot use the ordinary profile")
    if suite != "build" and selected is HygieneProfile.BUILD:
        raise RunnerProfileError("build profile cannot run non-build work")
    if suite not in {"staging", "system"} and selected is HygieneProfile.EXHAUSTIVE:
        raise RunnerProfileError("exhaustive profile cannot run partial work")

    if suite == "staging":
        if selected is HygieneProfile.EXHAUSTIVE and declared_complete_gates != 1:
            raise RunnerProfileError("exhaustive complete work requires exactly one gate")
        if selected is HygieneProfile.HEAVY and declared_complete_gates != 1:
            raise RunnerProfileError("heavy complete work requires exactly one gate")
        if selected is HygieneProfile.QUALIFICATION and declared_complete_gates not in {1, 2}:
            raise RunnerProfileError("qualification complete work requires one or two gates")
    elif suite == "system":
        if selected is HygieneProfile.EXHAUSTIVE and declared_complete_gates != 1:
            raise RunnerProfileError("exhaustive complete work requires exactly one gate")
        if selected is HygieneProfile.HEAVY and declared_complete_gates != 0:
            raise RunnerProfileError("heavy complete work requires zero declared gates")
    elif selected is not HygieneProfile.QUALIFICATION and declared_complete_gates != 0:
        raise RunnerProfileError("complete-gate count is not allowed for this work")

    if selected is HygieneProfile.QUALIFICATION:
        if campaign_plan_id is None:
            raise RunnerProfileError("qualification requires a campaign-plan identity")
        if declared_complete_gates not in {1, 2}:
            raise RunnerProfileError("qualification requires one or two declared gates")
        if not operator_attested_exclusive:
            raise RunnerProfileError("qualification requires exclusive attestation")
    elif campaign_plan_id is not None:
        raise RunnerProfileError("campaign-plan identity requires qualification")

    return RunnerProfileSelection(
        selected,
        explicit_required,
        declared_complete_gates,
        campaign_plan_id,
        operator_attested_exclusive,
        operator_attested_pressure_degradation,
    )


__all__ = ["RunnerProfileError", "RunnerProfileSelection", "resolve_runner_profile"]
