"""One-use capability registrations bound to the exact supervised OS child."""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace
import hashlib
import itertools
import json
from pathlib import Path
import secrets
import subprocess
import sys
from typing import Any, Mapping, cast
import weakref

from repomap_kg.coordinator._control_types import ConnectionFactory, JobClaim
from repomap_kg.coordinator._publication_phase import WorkerFencingProof, _fencing_identity, _issue_fencing_proof
from repomap_kg.coordinator._refresh_capability import load_refresh_capability
from repomap_kg.coordinator.process_supervision import ManagedProcess, PosixProcessGroup, WindowsJobObject


def _refresh_attempt_supervision_limits(limits: object) -> object:
    from repomap_kg.coordinator.limits import CoordinatorLimits

    att = limits.get("refresh_attempt_deadline_seconds") if isinstance(limits, Mapping) else getattr(limits, "refresh_attempt_deadline_seconds", None)
    proc = limits.get("process_deadline_seconds") if isinstance(limits, Mapping) else getattr(limits, "process_deadline_seconds", None)
    if att is None:
        raise ValueError("refresh_attempt_deadline_seconds is required for refresh worker supervision")
    if proc is not None and att <= proc:
        raise ValueError("refresh_attempt_deadline_seconds must be greater than process_deadline_seconds")
    if isinstance(limits, CoordinatorLimits):
        return replace(limits, process_deadline_seconds=att)
    if isinstance(limits, Mapping):
        return {**limits, "process_deadline_seconds": att}
    projected = copy.copy(cast(Any, limits))
    setattr(projected, "process_deadline_seconds", att)
    return projected


def compute_supervisor_registration_digest(token: bytes, identity: Mapping[str, object]) -> str:
    payload = json.dumps(
        {
            "token_hash": hashlib.sha256(token).hexdigest(),
            "job_id": str(identity["job_id"]),
            "attempt": int(str(identity["attempt"])),
            "graph_id": str(identity["graph_id"]),
            "coordinator_instance_id": str(identity["instance"]),
            "fencing_epoch": int(str(identity["epoch"])),
            "graph_lease_fencing_epoch": int(str(identity.get("graph_lease_epoch", 0))),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class SupervisorLaunchTicket:
    token: bytes
    identity: tuple[tuple[str, object], ...]
    expected_argv: tuple[str, ...]
    capability_digest: bytes
    registration_digest: str = ""


@dataclass
class _Launch:
    ticket: SupervisorLaunchTicket
    process: ManagedProcess | None = None


_PENDING_LAUNCHES: dict[bytes, _Launch] = {}
_ACTIVE_IDENTITIES: dict[tuple[tuple[str, object], ...], bytes] = {}
_REAPED: list[tuple[weakref.ReferenceType[object], SupervisorLaunchTicket, int]] = []
_REGISTRATION_COUNTER = itertools.count(1)


def register_worker_launch(capability: object, argv: tuple[str, ...]) -> SupervisorLaunchTicket:
    """Register the sealed capability and canonical maintained worker command."""
    identity = _fencing_identity(capability)
    if (len(argv) != 9 or argv[:3] != (sys.executable, "-m", "repomap_kg.coordinator.refresh_worker")
            or argv[3] != "--capability" or argv[5] != "--job-id" or argv[7] != "--attempt"):
        raise PermissionError("unauthorized worker launch: alternate worker executable or command")
    if argv[6] != str(identity["job_id"]) or argv[8] != str(identity["attempt"]):
        raise PermissionError("unauthorized worker launch: identity mismatch")
    path = Path(argv[4])
    if load_refresh_capability(path) != capability:
        raise PermissionError("sealed capability does not match launch authority")
    frozen_identity = tuple(sorted(identity.items()))
    if frozen_identity in _ACTIVE_IDENTITIES:
        raise PermissionError("attempt already has a live launch registration")
    token = secrets.token_bytes(32)
    registration_digest = compute_supervisor_registration_digest(token, identity)
    ticket = SupervisorLaunchTicket(
        token=token,
        identity=frozen_identity,
        expected_argv=argv,
        capability_digest=hashlib.sha256(path.read_bytes()).digest(),
        registration_digest=registration_digest,
    )
    _PENDING_LAUNCHES[ticket.token] = _Launch(ticket)
    _ACTIVE_IDENTITIES[frozen_identity] = ticket.token
    return ticket


def _registered(ticket: object) -> _Launch:
    if not isinstance(ticket, SupervisorLaunchTicket):
        raise PermissionError("invalid launch registration")
    launch = _PENDING_LAUNCHES.get(ticket.token)
    if launch is None or launch.ticket is not ticket:
        raise PermissionError("fabricated, reused or stale launch registration")
    return launch


def _validate_launch(ticket: object, argv: tuple[str, ...], identity: Mapping[str, object]) -> None:
    launch = _registered(ticket)
    authority = dict(launch.ticket.identity)
    if (launch.process is not None or argv != launch.ticket.expected_argv
            or any(identity.get(key) != authority[key] for key in ("job_id", "attempt"))
            or hashlib.sha256(Path(argv[4]).read_bytes()).digest() != launch.ticket.capability_digest):
        raise PermissionError("launch command or sealed capability registration mismatch")


def _bind_launch_process(ticket: object, process: ManagedProcess) -> None:
    launch = _registered(ticket)
    if (launch.process is not None or not isinstance(process.popen, subprocess.Popen)
            or process.popen.args != launch.ticket.expected_argv):
        raise PermissionError("launch registration requires its exact real child")
    launch.process = process


def release_unlaunched_registration(ticket: object) -> None:
    """Discard an unlaunched registration; never release a still-live child."""
    if not isinstance(ticket, SupervisorLaunchTicket):
        return
    launch = _PENDING_LAUNCHES.get(ticket.token)
    if launch is not None and launch.ticket is ticket and launch.process is None:
        _PENDING_LAUNCHES.pop(ticket.token)
        _ACTIVE_IDENTITIES.pop(ticket.identity, None)


def _record_reaped_launch(result: object, process: ManagedProcess, ticket: object) -> None:
    launch = _registered(ticket)
    if (launch.process is not process or not isinstance(process.popen, subprocess.Popen)
            or not process._closed or process.popen.poll() is None
            or not isinstance(process.boundary, (PosixProcessGroup, WindowsJobObject))
            or process.boundary.tree_exists()
            or process.popen.args != launch.ticket.expected_argv
            or tuple(getattr(result, "argv", ())) != launch.ticket.expected_argv
            or not getattr(result, "waited", False) or not getattr(result, "process_group_cleaned", False)):
        raise PermissionError("exact registered child and process group have not been reaped")
    _PENDING_LAUNCHES.pop(launch.ticket.token)
    _ACTIVE_IDENTITIES.pop(launch.ticket.identity, None)
    _retain_result(result, launch.ticket)


def _retain_result(result: object, ticket: SupervisorLaunchTicket) -> None:
    reg_id = next(_REGISTRATION_COUNTER)

    def _on_collected(ref: weakref.ReferenceType[object]) -> None:
        for i, entry in enumerate(_REAPED):
            if entry[0] is ref and entry[2] == reg_id:
                _REAPED.pop(i)
                break

    try:
        ref = weakref.ref(result, _on_collected)
    except TypeError as error:
        raise PermissionError("supervisor result must be weakly referenceable") from error
    _REAPED.append((ref, ticket, reg_id))


def _transfer_reaped_result(original: object, updated: object) -> None:
    """Keep registration when the maintained adapter refines a terminal result."""
    if original is updated:
        return
    ticket: SupervisorLaunchTicket | None = None
    for i, entry in enumerate(_REAPED):
        if entry[0]() is original:
            ticket = _REAPED.pop(i)[1]
            break
    if ticket is not None:
        _retain_result(updated, ticket)


def _register_reaped_result(result: object, process: object, identity: Mapping[str, object]) -> None:
    raise PermissionError("unauthorized supervisor registration: per-launch unforgeable registration required")


def _claim_from_identity(identity: Mapping[str, object]) -> JobClaim:
    return JobClaim(
        job_id=str(identity["job_id"]), attempt=int(str(identity["attempt"])),
        graph_id=str(identity["graph_id"]), instance_id=str(identity["instance"]),
        fencing_epoch=int(str(identity["epoch"])), graph_lease_fencing_epoch=int(str(identity["graph_lease_epoch"])),
        **{key: str(identity[key]) for key in (
            "source_generation", "config_generation", "extractor_generation", "canonicalizer_generation",
        )},
    )


def bind_durable_launch(ticket: object, capability: object, connect: ConnectionFactory) -> None:
    """Reserve the exact current durable attempt before its real child is spawned."""
    from repomap_kg.coordinator._supervisor_registration import persist_supervisor_registration

    launch = _registered(ticket)
    identity = _fencing_identity(capability)
    if launch.process is not None or dict(launch.ticket.identity) != identity:
        raise PermissionError("durable registration requires the exact unlaunched capability")
    persist_supervisor_registration(connect, _claim_from_identity(identity), launch.ticket.registration_digest)


def earn_in_process_fencing_proof(result: object, capability: object, connect: ConnectionFactory) -> WorkerFencingProof:
    ticket: SupervisorLaunchTicket | None = None
    for i, entry in enumerate(_REAPED):
        if entry[0]() is result:
            ticket = _REAPED.pop(i)[1]
            break
    if ticket is None:
        raise PermissionError("unauthorized supervisor mock: no real reaped process registration")
    identity = _fencing_identity(capability)
    if dict(ticket.identity) != identity:
        raise PermissionError("supervisor identity does not match attempt and graph lease")
    claim = _claim_from_identity(identity)
    from repomap_kg.coordinator._supervisor_registration import (
        in_process_currency_context, validate_supervisor_registration,
    )

    validate_supervisor_registration(connect, claim, ticket.registration_digest)

    return _issue_fencing_proof(
        capability,
        "in_process_reaped",
        lambda: in_process_currency_context(connect, claim, ticket.registration_digest),
        registration_digest=ticket.registration_digest,
    )
