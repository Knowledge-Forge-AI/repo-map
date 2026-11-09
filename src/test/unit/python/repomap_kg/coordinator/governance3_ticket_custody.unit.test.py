"""Ticket custody: custody-first bind, exact matching, proven/unproven abnormal release."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import signal
import sys
from types import SimpleNamespace
from typing import Any, cast

import pytest
import secrets

from common_lore_index.coordinator import _supervisor_fencing as fencing
from common_lore_index.coordinator._launch_custody_steps import CustodyOutcome
from common_lore_index.coordinator._protocol_core import ProtocolError
from common_lore_index.coordinator._protocol_execution import _run_protocol_worker
from common_lore_index.coordinator.process_supervision import (
    ManagedProcess,
    PosixProcessGroup,
    launch_managed_process,
)
from common_lore_index.coordinator.refresh_adapter import RefreshCapability, create_refresh_capability
from repomap_test_support.fencing_control_fakes import FencingControl

_PROVEN = CustodyOutcome(True, -9, True, True, True, True, True, None)
_ENV = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[6] / "src/main/python")}
_LIMITS = SimpleNamespace(hello_deadline_seconds=30.0, process_deadline_seconds=30.0,
                          heartbeat_seconds=30.0, process_termination_grace_seconds=1.0,
                          cancel_deadline_seconds=1.0)


@pytest.fixture
def sealed(tmp_path):
    tmp_path.chmod(0o700)
    config = tmp_path / "ops.toml"
    config.write_text("schema_version = 1\n")
    config.chmod(0o600)
    psql = tmp_path / "psql"
    psql.touch()
    psql.chmod(0o755)
    cap = RefreshCapability(
        schema_version=1, job_id="custody-fixture", attempt=1, graph_id="fixture",
        config_path=config, psql_path=psql, postgres_user="fixture", postgres_password=secrets.token_hex(16),
        executable_search_path=(tmp_path,), source_generation="sg1:fixture", config_generation="cg1:fixture",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
        coordinator_instance_id="owner", singleton_fencing_epoch=3, graph_lease_fencing_epoch=91,
    )
    path = create_refresh_capability(tmp_path, cap)
    argv = (sys.executable, "-m", "common_lore_index.coordinator.refresh_worker", "--capability",
            str(path), "--job-id", cap.job_id, "--attempt", str(cap.attempt))
    ticket = fencing.register_worker_launch(cap, argv)
    yield cap, argv, ticket
    fencing._PENDING_LAUNCHES.pop(ticket.token, None)  # held registrations are test-owned here
    fencing._ACTIVE_IDENTITIES.pop(ticket.identity, None)


def _held(ticket: Any) -> bool:
    return fencing._PENDING_LAUNCHES.get(ticket.token) is not None


def _close_streams(process: ManagedProcess) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def _reaped_tickets() -> list[object]:
    return [entry[1] for entry in fencing._REAPED]


def test_a_fake_child_is_never_bound_and_stays_releasable_as_unlaunched(sealed) -> None:
    _cap, argv, ticket = sealed
    fake = ManagedProcess(cast(Any, SimpleNamespace(args=argv, pid=5)), PosixProcessGroup(5))
    with pytest.raises(PermissionError, match="exact real child"):
        fencing._bind_launch_process(ticket, fake)
    assert fencing._PENDING_LAUNCHES[ticket.token].process is None
    fencing.release_unlaunched_registration(ticket)
    assert not _held(ticket)


def test_a_real_mismatched_child_is_held_first_and_released_only_with_proof(sealed, tmp_path) -> None:
    _cap, _argv, ticket = sealed
    other = launch_managed_process((sys.executable, "-c", "import time; time.sleep(30)"), _ENV, tmp_path)
    try:
        with pytest.raises(PermissionError, match="exact real child"):
            fencing._bind_launch_process(ticket, other)
        assert fencing._PENDING_LAUNCHES[ticket.token].process is other, "custody bound before validation"
        fencing.release_unlaunched_registration(ticket)
        assert _held(ticket), "a bound child is never released as unlaunched"
        assert fencing._release_abnormal_launch(ticket, other, _PROVEN) is False, "status not yet owned"
        other.kill_tree()
        assert other.cleanup(0.0, 5.0) and other.owner_reaped
        unproven = replace(_PROVEN, streams_closed=False, proven=False, reason="streams_open")
        assert fencing._release_abnormal_launch(ticket, other, unproven) is False and _held(ticket)
        before = _reaped_tickets()
        assert fencing._release_abnormal_launch(ticket, other, _PROVEN) is True
        assert not _held(ticket) and ticket.identity not in fencing._ACTIVE_IDENTITIES
        assert _reaped_tickets() == before, "abnormal release retains no fencing-capable result"
    finally:
        other.cleanup(0.0, 5.0)
        _close_streams(other)


def test_release_requires_the_exact_registered_ticket_and_process(sealed, tmp_path) -> None:
    _cap, argv, ticket = sealed
    with pytest.raises(PermissionError, match="fabricated, reused or stale"):
        fencing._release_abnormal_launch(replace(ticket), object(), _PROVEN)
    with pytest.raises(PermissionError, match="exact registered child"):
        fencing._release_abnormal_launch(ticket, object(), _PROVEN)
    worker = launch_managed_process(argv, _ENV, tmp_path)
    try:
        fencing._bind_launch_process(ticket, worker)
        with pytest.raises(PermissionError, match="exact registered child"):
            fencing._release_abnormal_launch(ticket, object(), _PROVEN)
        assert _held(ticket)
    finally:
        assert worker.cleanup(0.1, 5.0)
        _close_streams(worker)


def test_fabricated_passive_status_never_records_a_reaped_result(sealed, tmp_path) -> None:
    _cap, argv, ticket = sealed
    worker = launch_managed_process(argv, _ENV, tmp_path)
    try:
        fencing._bind_launch_process(ticket, worker)
        worker.kill_tree()
        setattr(worker.popen, "returncode", 0)  # fault injection: no selected-owner status
        assert worker.cleanup(0.0, 0.2) is False and worker.reap_state() == "status_unknown"
        assert worker.returncode is None and worker.closed
        result = SimpleNamespace(argv=argv, waited=True, process_group_cleaned=True)
        with pytest.raises(PermissionError, match="have not been reaped"):
            fencing._record_reaped_launch(result, worker, ticket)
        assert fencing._release_abnormal_launch(ticket, worker, _PROVEN) is False and _held(ticket)
    finally:
        try:
            os.kill(worker.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        os.waitpid(worker.pid, 0)  # test-owned reap of the deliberately unowned child
        _close_streams(worker)


def test_ticketed_invalid_context_settles_and_releases_without_minting_proof(sealed, tmp_path) -> None:
    cap, argv, ticket = sealed
    control = FencingControl(cap)
    fencing.bind_durable_launch(ticket, cap, control.connect)
    before = _reaped_tickets()
    context = {"graph_id": cap.graph_id, "source_generation": cap.source_generation,
               "config_generation": cap.config_generation, "unexpected": "extra"}
    with pytest.raises(ProtocolError, match="invalid_job_context"):
        _run_protocol_worker(
            argv, _ENV, tmp_path, False, {"job_id": cap.job_id, "attempt": cap.attempt}, _LIMITS,
            job_context=context, cancel_event=None, _launch_ticket=ticket,
        )
    assert not _held(ticket) and _reaped_tickets() == before
    assert control.attempt["supervisor_registration_digest"] == ticket.registration_digest
    assert not control.attempt.get("supervisor_registration_consumed"), "durable digest unconsumed"
    with pytest.raises(PermissionError, match="unauthorized supervisor mock"):
        fencing.earn_in_process_fencing_proof(SimpleNamespace(argv=argv), cap, control.connect)
