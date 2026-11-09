"""Private, process-free lifecycle observations for owned usage launches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class UsageSettlement:
    """Facts reported only after the native owner has settled a child."""

    pid: int
    returncode: int | None
    waited: bool
    process_group_cleaned: bool
    readers_closed: bool
    streams_closed: bool
    proven: bool


class UsageObserver(Protocol):
    """Notification-only observer; process objects never cross this seam."""

    def launched(self, pid: int) -> None: ...

    def settled(self, facts: UsageSettlement) -> None: ...


def usage_streams_closed(process: object) -> bool:
    """Require actual closed stream state, rather than a successful close call."""
    return all(getattr(getattr(process, name, None), "closed", False) is True
               for name in ("stdin", "stdout", "stderr"))


def validate_usage_observer(observer: object | None, collect_usage: bool,
                            launch_process: object | None, launch_ticket: object | None) -> None:
    """Validate observer ownership before any child is created."""

    if observer is None:
        return
    if not collect_usage:
        raise ValueError("usage observer requires owned usage collection")
    if launch_process is not None or launch_ticket is not None:
        raise ValueError("usage observer requires owned launch")
    if (not callable(getattr(observer, "launched", None))
            or not callable(getattr(observer, "settled", None))):
        raise TypeError("usage observer must provide launched and settled")


def settlement_for_process(process: object, *, waited: bool, process_group_cleaned: bool,
                           readers_closed: bool, streams_closed: bool) -> UsageSettlement:
    """Build facts from native-owned observations; never infer from PID absence."""

    pid = getattr(process, "pid", None)
    if type(pid) is not int or pid <= 0:
        raise ValueError("usage settlement requires a native pid")
    returncode = getattr(process, "returncode", None)
    proven = (
        type(returncode) is int and waited and process_group_cleaned
        and readers_closed and streams_closed
    )
    return UsageSettlement(
        pid=pid,
        returncode=returncode,
        waited=bool(waited),
        process_group_cleaned=bool(process_group_cleaned),
        readers_closed=bool(readers_closed),
        streams_closed=bool(streams_closed),
        proven=proven,
    )


__all__ = ("UsageObserver", "UsageSettlement", "settlement_for_process",
           "usage_streams_closed", "validate_usage_observer")
