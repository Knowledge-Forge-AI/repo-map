"""Identify the canonical outer sandbox through its owned live process tree.

Global Docker set differences are conservation evidence, not ownership proof.
The phase controller supplies fresh process/inspection observations; this module
has no process signalling, Docker execution, configuration discovery or cleanup.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
from pathlib import Path
import re

_CID = re.compile(r'[0-9a-f]{64}\Z')
_IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')


class BridgeOwnershipError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RunnerIdentity:
    pid: int
    creation_time: float
    source_root: Path = field(repr=False)
    sdk_image_id: str = field(repr=False)
    expected_selectors: tuple[str, ...]


@dataclass(frozen=True)
class ProcessObservation:
    pid: int
    parent_pid: int
    creation_time: float
    argv: tuple[str, ...] = field(repr=False)
    alive: bool = True


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise BridgeOwnershipError(code)


def identify_outer_cid(owner: RunnerIdentity, observations: Sequence[ProcessObservation]) -> str:
    """Require agreeing live log-follower and wait descendants of this runner."""
    _require(type(owner.pid) is int and owner.pid > 0, 'invalid_runner_identity')
    _require(type(owner.creation_time) in (int, float) and math.isfinite(owner.creation_time)
             and owner.creation_time > 0, 'invalid_runner_identity')
    _require(bool(owner.expected_selectors) and len(set(owner.expected_selectors)) == len(owner.expected_selectors),
             'invalid_runner_selectors')
    by_pid: dict[int, ProcessObservation] = {}
    for item in observations:
        _require(type(item) is ProcessObservation and type(item.pid) is int and item.pid > 0,
                 'invalid_process_observation')
        _require(item.pid not in by_pid, 'duplicate_process_identity')
        _require(type(item.creation_time) in (int, float) and math.isfinite(item.creation_time)
                 and item.creation_time > 0 and type(item.alive) is bool, 'invalid_process_observation')
        _require(type(item.parent_pid) is int and item.parent_pid >= 0 and type(item.argv) is tuple
                 and all(type(arg) is str for arg in item.argv), 'invalid_process_observation')
        by_pid[item.pid] = item
    root = by_pid.get(owner.pid)
    _require(root is not None and root.alive and root.creation_time == owner.creation_time, 'runner_identity_changed')

    def owned(item: ProcessObservation) -> bool:
        seen: set[int] = set()
        while item.pid != owner.pid:
            if item.pid in seen or not item.alive or item.creation_time < owner.creation_time:
                return False
            seen.add(item.pid)
            parent = by_pid.get(item.parent_pid)
            if parent is None or parent.creation_time > item.creation_time:
                return False
            item = parent
        return item.alive and item.creation_time == owner.creation_time

    logs: list[str] = []
    waits: list[str] = []
    for item in observations:
        if not item.argv or not owned(item) or Path(item.argv[0]).name != 'docker':
            continue
        tail = item.argv[1:]
        if len(tail) == 3 and tail[:2] == ('logs', '--follow'):
            _require(_CID.fullmatch(tail[2]) is not None, 'invalid_outer_cid')
            logs.append(tail[2])
        elif len(tail) == 2 and tail[0] == 'wait':
            _require(_CID.fullmatch(tail[1]) is not None, 'invalid_outer_cid')
            waits.append(tail[1])
    _require(len(logs) == len(waits) == 1 and logs[0] == waits[0], 'outer_process_attribution_unavailable')
    return logs[0]


def verify_outer_inspection(owner: RunnerIdentity, cid: str, inspection: Mapping[str, object]) -> None:
    """Cross-check exact process-attributed CID, SDK, source mount and selector."""
    _require(_CID.fullmatch(cid) is not None and _IMAGE.fullmatch(owner.sdk_image_id) is not None,
             'invalid_outer_identity')
    _require(inspection.get('Id') == cid and inspection.get('Image') == owner.sdk_image_id, 'outer_image_mismatch')
    config, state, mounts = inspection.get('Config'), inspection.get('State'), inspection.get('Mounts')
    _require(isinstance(config, Mapping) and isinstance(state, Mapping) and isinstance(mounts, list),
             'invalid_outer_inspection')
    assert isinstance(config, Mapping) and isinstance(state, Mapping) and isinstance(mounts, list)
    _require(state.get('Running') is True, 'outer_not_running')
    labels, command = config.get('Labels'), config.get('Cmd')
    _require(isinstance(labels, Mapping) and isinstance(command, list) and all(type(arg) is str for arg in command),
             'invalid_outer_config')
    assert isinstance(labels, Mapping) and isinstance(command, list)
    _require(labels.get('org.repomap.test.sandbox') == 'true'
             and labels.get('org.repomap.test.sandbox.backend') == 'monolithic-dind-v1', 'outer_labels_mismatch')
    prefix = ['docker-init', '--', 'python3', '/workspace-ro/tools/test_sandbox_entrypoint.py', '--docker-group']
    _require(command[:5] == prefix and len(command) > 7 and type(command[5]) is str
             and command[5].isdigit() and command[6] == '--', 'outer_command_mismatch')
    arguments = command[7:]
    _require('--' in arguments, 'outer_selector_boundary_missing')
    selector_args = arguments[arguments.index('--') + 1:]
    # The supervisor owns a scoped canonical invocation. Require the exact
    # declared test files and permit only pytest output flags after them.
    actual_selectors = tuple(arg for arg in selector_args if not arg.startswith('-'))
    _require(actual_selectors == owner.expected_selectors, 'outer_selectors_mismatch')
    for option, expected in (('--suite', 'int'), ('--jobs', '1')):
        _require(option in arguments and arguments.index(option) + 1 < len(arguments)
                 and arguments[arguments.index(option) + 1] == expected, 'outer_scope_mismatch')
    _require('--no-coverage' in arguments, 'outer_coverage_mismatch')
    _require('--pg-test-profile' in arguments and arguments.index('--pg-test-profile') + 1 < len(arguments)
             and arguments[arguments.index('--pg-test-profile') + 1] == 'pgvector', 'outer_profile_mismatch')
    bind_mounts = []
    for mount in mounts:
        _require(isinstance(mount, Mapping), 'invalid_outer_mount')
        if mount.get('Type') == 'bind':
            bind_mounts.append(mount)
    _require(len(bind_mounts) == 1, 'outer_bind_mounts_mismatch')
    source_mount = bind_mounts[0]
    _require(source_mount.get('Source') == str(owner.source_root.resolve())
             and source_mount.get('Destination') == '/workspace-ro'
             and source_mount.get('RW') is False, 'outer_source_mount_mismatch')
