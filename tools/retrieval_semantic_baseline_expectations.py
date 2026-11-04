"""Versioned baseline capability expectations; historical tables stay immutable."""
from __future__ import annotations
from collections.abc import Mapping
from types import MappingProxyType

_COMMON_NON_VERIFIED: dict[str, tuple[str, str]] = {
    **{t: ("not_applicable", "file_metric_not_applicable") for t in ("cal-09", "cal-10", "cal-12", "cal-24")},
    **{t: ("gap", "refused:binding_privacy_not_authorized") for t in ("cal-21", "cal-22")},
}
_GRAPH_UNAVAILABLE_BODY: dict[str, tuple[str, str]] = {
    tid: ("gap", "unavailable:captured_text_surface_unsupported_by_metadata_graph")
    for tid in ("cal-04", "cal-05", "cal-06", "cal-07", "cal-08", "cal-11", "cal-14", "cal-15", "cal-18", "cal-19", "cal-20")
}
# The approved W5 public-only graph does not declare the denied mailbox.
# Its graph arm cannot attest a privacy refusal for an absent binding.
_GRAPH_ABSENT_MAILBOX = {t: ("gap", "unavailable:captured_text_surface_unsupported_by_metadata_graph") for t in ("cal-21", "cal-22")}
_REF_UNAVAILABLE_FEEDS: dict[str, tuple[str, str]] = {
    t: ("gap", "unavailable:non_body_feed_or_mailbox_excluded_from_text_projection") for t in ("cal-16", "cal-17")
}
_FTS_UNAVAILABLE_FEEDS: dict[str, tuple[str, str]] = {
    t: ("gap", "unavailable:non_body_feed_or_mailbox_excluded_from_lexical_index") for t in ("cal-16", "cal-17")
}
W5_EXPECTED_BASELINE_GAPS_BY_ARM_V1: Mapping[str, Mapping[str, tuple[str, str]]] = MappingProxyType({
    "native_tools_baseline": MappingProxyType(dict(_COMMON_NON_VERIFIED)),
    "current_graph_baseline:sqlite": MappingProxyType({**_COMMON_NON_VERIFIED, **_GRAPH_UNAVAILABLE_BODY, **_GRAPH_ABSENT_MAILBOX}),
    "current_graph_baseline:postgresql": MappingProxyType({**_COMMON_NON_VERIFIED, **_GRAPH_UNAVAILABLE_BODY, **_GRAPH_ABSENT_MAILBOX}),
    "captured_projection_reference:sqlite": MappingProxyType({**_COMMON_NON_VERIFIED, **_REF_UNAVAILABLE_FEEDS}),
    "captured_projection_reference:postgresql": MappingProxyType({**_COMMON_NON_VERIFIED, **_REF_UNAVAILABLE_FEEDS}),
    "postgres_native_fts:postgresql": MappingProxyType({**_COMMON_NON_VERIFIED, **_FTS_UNAVAILABLE_FEEDS}),
})
# Historical expectations stay available; current W5 prechecks use the policy
# declaration for the two private mailbox body requests. Feed metadata keeps
# its historical capability outcome.
W5_EXPECTED_BASELINE_GAPS_BY_ARM_V2: Mapping[str, Mapping[str, tuple[str, str]]] = MappingProxyType({
    arm: MappingProxyType({**table, **{task: ("gap", "refused:binding_privacy_not_authorized")
        for task in ("cal-21", "cal-22")}})
    for arm, table in W5_EXPECTED_BASELINE_GAPS_BY_ARM_V1.items()
})
W5_EXPECTED_BASELINE_GAPS_BY_ARM = W5_EXPECTED_BASELINE_GAPS_BY_ARM_V1


def is_expected_baseline_gap(
    arm_id: str, task_id: str, status: str, gap_reason: str | None,
    *, policy_version: str = "cloe-w5-baseline-correspondence-v1",
) -> bool:
    """Preserve the historical default; current admission expectations are explicit."""
    if policy_version == "cloe-w5-baseline-correspondence-v1":
        tables = W5_EXPECTED_BASELINE_GAPS_BY_ARM_V1
    elif policy_version == "cloe-w5-admission-v1":
        tables = W5_EXPECTED_BASELINE_GAPS_BY_ARM_V2
    else:
        raise ValueError("unknown W5 expected-gap policy version")
    arm_table = tables.get(arm_id)
    if arm_table is None:
        return False
    expected = arm_table.get(task_id)
    return expected is not None and expected == (status, str(gap_reason or ""))
