"""Closed owner-status and group-probe vocabularies plus native launch provenance.

The original ``subprocess.Popen`` class is captured when this module is first
imported. Genuine native provenance requires that exact factory to have created
an instance of that exact class; a runtime-patched or injected factory still
receives every launch (so fake unit models never spawn a real child) but never
earns native custody, owned group signals or ticket proof.
"""

from __future__ import annotations

import subprocess

from common_lore_index.coordinator._protocol_validation import ProtocolError

LIVE = "live"
REAPED = "reaped"
STATUS_UNKNOWN = "status_unknown"
REAP_STATES = frozenset({LIVE, REAPED, STATUS_UNKNOWN})

MEMBERS = "members"
EMPTY = "empty"
UNPROBEABLE = "unprobeable"
GROUP_STATES = frozenset({MEMBERS, EMPTY, UNPROBEABLE})

STATUS_UNKNOWN_CODE = "worker_status_unknown"

ORIGINAL_POPEN = subprocess.Popen


def status_unknown_error() -> ProtocolError:
    return ProtocolError(STATUS_UNKNOWN_CODE)


def is_status_unknown(error: BaseException) -> bool:
    """True only for the selected owner's fail-closed unknown-status refusal."""
    return isinstance(error, ProtocolError) and error.code == STATUS_UNKNOWN_CODE


def group_state_from_tree(exists: bool) -> str:
    """Map a legacy ``tree_exists`` answer onto the closed group vocabulary."""
    return MEMBERS if exists else EMPTY


def original_popen_launch(popen_factory: object, process: object) -> bool:
    """The captured factory created an instance of the captured class."""
    return popen_factory is ORIGINAL_POPEN and type(process) is ORIGINAL_POPEN


__all__ = (
    "EMPTY",
    "GROUP_STATES",
    "LIVE",
    "MEMBERS",
    "ORIGINAL_POPEN",
    "REAPED",
    "REAP_STATES",
    "STATUS_UNKNOWN",
    "STATUS_UNKNOWN_CODE",
    "UNPROBEABLE",
    "group_state_from_tree",
    "is_status_unknown",
    "original_popen_launch",
    "status_unknown_error",
)
