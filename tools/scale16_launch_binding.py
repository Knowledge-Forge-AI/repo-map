"""Immutable private binding for one child-created direct launch attempt."""

from __future__ import annotations

from repomap_kg.storage.publication import RunPublicationAttempt
from repomap_kg.storage.staging_launch_authority import DirectLaunchAuthorityEvent


class LaunchBindingError(RuntimeError):
    """One closed launch-binding violation without private values."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class LaunchBindingState:
    """Accept and freeze exactly one private direct publication attempt."""

    def __init__(self) -> None:
        self._state = "awaiting"
        self._attempt: RunPublicationAttempt | None = None
        self._frame_sequence: int | None = None
        self._event_offset_ns: int | None = None

    @property
    def bound_attempt(self) -> RunPublicationAttempt | None:
        return self._attempt

    @property
    def public_state(self) -> str:
        return {
            "awaiting": "launch_authority_missing",
            "bound": "launch_authority_bound",
            "invalid": "launch_authority_invalid",
            "late": "launch_authority_late",
            "missing": "launch_authority_missing",
        }[self._state]

    def accept(self, frame) -> None:
        """Semantically validate and freeze one authority frame before ACK."""

        if self._state == "bound":
            raise LaunchBindingError("launch_authority_duplicate")
        if self._state == "late":
            raise LaunchBindingError("launch_authority_late")
        if self._state != "awaiting" or frame.category != "authority":
            self._state = "invalid"
            raise LaunchBindingError("launch_authority_invalid")
        try:
            event = DirectLaunchAuthorityEvent.from_payload(frame.payload)
        except (TypeError, ValueError) as error:
            self._state = "invalid"
            raise LaunchBindingError("launch_authority_invalid") from error
        self._attempt = event.publication_attempt
        self._frame_sequence = frame.sequence
        self._event_offset_ns = event.monotonic_offset_ns
        self._state = "bound"

    def mark_late(self) -> None:
        """Close an unbound state after a mutation-capable boundary."""

        if self._state == "awaiting":
            self._state = "late"

    def require_bound(self) -> RunPublicationAttempt:
        """Return the frozen attempt or fail with a closed missing category."""

        if self._state != "bound" or self._attempt is None:
            if self._state == "awaiting":
                self._state = "missing"
            raise LaunchBindingError(self.public_state)
        return self._attempt

    def __repr__(self) -> str:
        return f"LaunchBindingState(public_state={self.public_state!r})"


__all__ = ["LaunchBindingError", "LaunchBindingState"]
