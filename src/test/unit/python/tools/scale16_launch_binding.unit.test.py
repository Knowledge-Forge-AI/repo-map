from __future__ import annotations

import pytest

from repomap_kg.storage.authority import AttemptNumber, JobId
from repomap_kg.storage.publication import RunPublicationAttempt
from repomap_kg.storage.staging_event_transport import StagingEventFrame
from repomap_kg.storage.staging_launch_authority import DirectLaunchAuthorityEvent
from scale16_launch_binding import LaunchBindingError, LaunchBindingState


def _frame(identity: str = "direct-scale16", attempt: int = 1) -> StagingEventFrame:
    event = DirectLaunchAuthorityEvent.from_attempt(
        RunPublicationAttempt(JobId(identity), AttemptNumber(attempt)),
        19,
    )
    return StagingEventFrame(3, "authority", event.to_payload())


def test_launch_binding_freezes_exact_attempt_once() -> None:
    binding = LaunchBindingState()

    binding.accept(_frame())

    assert binding.bound_attempt == RunPublicationAttempt(JobId("direct-scale16"), AttemptNumber(1))
    assert binding.public_state == "launch_authority_bound"
    assert "direct-scale16" not in repr(binding)


@pytest.mark.parametrize(
    ("second", "category"),
    (
        (_frame(), "launch_authority_duplicate"),
        (_frame("direct-changed"), "launch_authority_duplicate"),
    ),
)
def test_launch_binding_rejects_duplicate_identical_or_changed(second, category) -> None:
    binding = LaunchBindingState()
    binding.accept(_frame())

    with pytest.raises(LaunchBindingError) as caught:
        binding.accept(second)

    assert caught.value.category == category
    assert "direct-" not in str(caught.value)


def test_launch_binding_rejects_malformed_and_late_events() -> None:
    malformed = LaunchBindingState()
    with pytest.raises(LaunchBindingError) as caught:
        malformed.accept(StagingEventFrame(1, "authority", {}))
    assert caught.value.category == "launch_authority_invalid"

    late = LaunchBindingState()
    late.mark_late()
    with pytest.raises(LaunchBindingError) as caught:
        late.accept(_frame())
    assert caught.value.category == "launch_authority_late"


def test_launch_binding_missing_is_closed_without_identity() -> None:
    binding = LaunchBindingState()

    with pytest.raises(LaunchBindingError) as caught:
        binding.require_bound()

    assert caught.value.category == "launch_authority_missing"
    assert binding.public_state == "launch_authority_missing"
