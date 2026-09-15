from __future__ import annotations


_REQUIRED_BOUNDARIES = frozenset(
    {
        "observer_active_summary",
        "observer_connection_lost",
        "observer_event_apply",
    }
)


class SiblingCampaignOracleError(AssertionError):
    """Raised when the ten-campaign causal oracle is weakened."""


def validate_sibling_campaign_oracle(
    *,
    published: int,
    observed_injected_boundaries: set[str],
    source_owned_preemptions: int,
) -> None:
    if published < 1:
        raise SiblingCampaignOracleError("sibling campaign has no publication")
    if observed_injected_boundaries != _REQUIRED_BOUNDARIES:
        raise SiblingCampaignOracleError("sibling campaign lost an injected boundary")
    if source_owned_preemptions > 1:
        raise SiblingCampaignOracleError("sibling campaign admits excess preemption")
