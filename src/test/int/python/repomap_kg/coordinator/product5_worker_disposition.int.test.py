"""Integration tests for worker disposition, supervision timeouts, and protocol execution.

Behavioral coverage for refresh_worker.py, _refresh_execution.py, and _protocol_execution.py
under REPOMAP-PRODUCT5-HOSTED-CI-REPAIR2.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest
from repomap_kg.coordinator.protocol import (
    ProtocolError,
    run_refresh_worker,
)
from repomap_kg.coordinator.refresh_adapter import (
    RefreshCapability,
    create_refresh_capability,
)
from repomap_kg.ops.config import load_ops_config
from repomap_kg.runtime.postgres_route import effective_postgres_route
from repomap_test_support.portable_worker_scenarios import coordinator_test_limits
from repomap_test_support.startup_recovery_scenarios import (
    _make_refresh_fixture,
    _refresh_harness,
    _req_norm,
    _search_path,
)


def _make_worker_capability(
    postgres: object,
    cap_dir: Path,
    config: Path,
    claim: object,
    sg: str,
    cg: str,
    eg: str,
    kg: str,
    *,
    postgres_host: str | None = None,
    postgres_password: str | None = None,
) -> tuple[Path, RefreshCapability]:
    route = effective_postgres_route(load_ops_config(config))
    cap = RefreshCapability(
        schema_version=1,
        job_id=getattr(claim, "job_id"),
        attempt=getattr(claim, "attempt"),
        graph_id=getattr(claim, "graph_id"),
        config_path=config,
        psql_path=Path(getattr(postgres, "psql_command")),
        postgres_user=getattr(postgres, "user"),
        postgres_host=postgres_host or route.host,
        postgres_port=route.port,
        postgres_route_kind=route.kind,
        postgres_password=postgres_password or getattr(postgres, "password"),
        executable_search_path=_search_path(),
        source_generation=sg,
        config_generation=cg,
        extractor_generation=eg,
        canonicalizer_generation=kg,
        coordinator_instance_id=getattr(claim, "instance_id"),
        singleton_fencing_epoch=getattr(claim, "fencing_epoch"),
        graph_lease_fencing_epoch=getattr(claim, "graph_lease_fencing_epoch"),
    )
    sealed_path = create_refresh_capability(cap_dir, cap)
    return sealed_path, cap


@pytest.mark.parametrize("pause_hint", ["none", "relative", "symlink", "insecure-parent", "parent-symlink"])
def test_worker_successful_execution_and_cleanup_lifecycle(monkeypatch: pytest.MonkeyPatch, pause_hint: str) -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        store.submit(_req_norm("ok-1", sg, cg, eg, kg))
        epoch = store.acquire_singleton("inst-ok", timedelta(seconds=300))
        claim = store.claim_next("inst-ok", epoch, timedelta(seconds=300))
        assert claim is not None

        assert store.compare_and_set_state(
            claim.job_id, expected_state="claimed", new_state="starting",
            attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=epoch,
        )
        assert store.compare_and_set_state(
            claim.job_id, expected_state="starting", new_state="running",
            attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=epoch,
        )

        trigger: Path | None = None
        ready: Path | None = None
        target: Path | None = None
        if pause_hint != "none":
            if pause_hint == "relative":
                monkeypatch.chdir(cap_dir)
                hint = Path("relative-worker-trigger")
                trigger = cap_dir / hint
                trigger.touch()
                ready = cap_dir / f"{hint.name}.ready"
            elif pause_hint == "symlink":
                target = cap_dir / "pause-target"
                target.touch()
                hint = cap_dir / "symlink-trigger"
                hint.symlink_to(target)
                trigger = hint
                ready = Path(f"{hint}.ready")
            else:
                parent = cap_dir / "pause-parent"
                parent.mkdir(mode=0o755 if pause_hint == "insecure-parent" else 0o700)
                if pause_hint == "parent-symlink":
                    linked = cap_dir / "linked"
                    linked.symlink_to(parent, target_is_directory=True)
                    parent = linked
                hint = parent / "trigger"
                hint.touch()
                trigger = hint
                ready = Path(f"{hint}.ready")
            monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_PAUSE_PATH", str(hint))

        cap_path, _ = _make_worker_capability(postgres, cap_dir, config, claim, sg, cg, eg, kg)
        try:
            res = run_refresh_worker(
                cap_path,
                {"job_id": claim.job_id, "attempt": claim.attempt},
                coordinator_test_limits(),
                job_context={"graph_id": claim.graph_id, "source_generation": sg, "config_generation": cg},
                fencing_prover=store.in_process_fencing_proof,
                launch_registrar=store.register_supervisor_launch,
            )
            assert res.waited is True
            assert res.process_group_cleaned is True
            assert res.returncode == 0
            assert res.terminal["status"] == "succeeded"
            assert res.terminal["phase"] == "complete"
            assert res.terminal["publication_state"] == "committed"
            assert not cap_path.exists()

            if pause_hint != "none":
                assert trigger is not None and trigger.exists()
                assert ready is not None and not ready.exists()
        finally:
            if trigger is not None:
                trigger.unlink(missing_ok=True)
            if ready is not None:
                ready.unlink(missing_ok=True)
            if target is not None:
                target.unlink(missing_ok=True)

        with psycopg.connect(
            host=postgres.host, port=postgres.port, user=postgres.user, dbname=graph_db, password=postgres.password,
        ) as conn:
            with conn.cursor() as cur:
                count = cur.execute("SELECT count(*) FROM runs").fetchone()
                assert count is not None and count[0] >= 1


def test_worker_cancellation_disposition() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        store.submit(_req_norm("cancel-1", sg, cg, eg, kg))
        epoch = store.acquire_singleton("inst-cancel", timedelta(seconds=300))
        claim = store.claim_next("inst-cancel", epoch, timedelta(seconds=300))
        assert claim is not None

        cap_path, _ = _make_worker_capability(postgres, cap_dir, config, claim, sg, cg, eg, kg)
        cancel_event = threading.Event()
        cancel_event.set()

        res = run_refresh_worker(
            cap_path,
            {"job_id": claim.job_id, "attempt": claim.attempt},
            coordinator_test_limits(),
            job_context={"graph_id": claim.graph_id, "source_generation": sg, "config_generation": cg},
            cancel_event=cancel_event,
        )
        assert res.waited is True
        assert res.process_group_cleaned is True
        assert res.terminal["status"] == "cancelled"
        assert res.terminal["error_category"] == "cancelled"
        assert not cap_path.exists()

        with psycopg.connect(
            host=postgres.host, port=postgres.port, user=postgres.user, dbname=graph_db, password=postgres.password,
        ) as conn:
            with conn.cursor() as cur:
                count = cur.execute("SELECT count(*) FROM runs").fetchone()
                assert count == (0,)


@pytest.mark.parametrize("failure", ["configuration", "generation_changed"])
def test_worker_configuration_and_route_failure_disposition(failure: str) -> None:
    with _refresh_harness() as (store, cap_dir, _, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        store.submit(_req_norm("cfg-err", sg, cg, eg, kg))
        epoch = store.acquire_singleton("inst-err", timedelta(seconds=300))
        claim = store.claim_next("inst-err", epoch, timedelta(seconds=300))
        assert claim is not None
        cap_path, capability = _make_worker_capability(postgres, cap_dir, config, claim, sg, cg, eg, kg)
        cap_path.unlink()
        if failure == "configuration":
            broken = cap_dir / "broken_ops.toml"
            broken.write_text("invalid [ [ toml syntax\n", encoding="utf-8")
            capability = replace(capability, config_path=broken)
        else:
            capability = replace(capability, postgres_host="route-mismatched-host")
        cap_path = create_refresh_capability(cap_dir, capability)
        result = run_refresh_worker(
            cap_path, {"job_id": claim.job_id, "attempt": claim.attempt}, coordinator_test_limits(),
            job_context={"graph_id": claim.graph_id, "source_generation": sg, "config_generation": cg},
        )
        assert result.waited and result.process_group_cleaned
        assert not result.synthesized_terminal
        assert result.terminal["status"] == "failed"
        assert result.terminal["error_category"] == failure
        assert result.terminal["phase"] == "preflight"
        assert result.terminal["publication_state"] == "not_started"
        assert not cap_path.exists()
        assert store.stop_singleton("inst-err", epoch)


def test_worker_database_authorization_failure_disposition() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        store.submit(_req_norm("auth-err-1", sg, cg, eg, kg))
        epoch = store.acquire_singleton("inst-auth", timedelta(seconds=300))
        claim = store.claim_next("inst-auth", epoch, timedelta(seconds=300))
        assert claim is not None

        cap_path, _ = _make_worker_capability(
            postgres, cap_dir, config, claim, sg, cg, eg, kg,
            postgres_password="definitely-wrong-password-for-test",
        )
        res = run_refresh_worker(
            cap_path,
            {"job_id": claim.job_id, "attempt": claim.attempt},
            coordinator_test_limits(),
            job_context={"graph_id": claim.graph_id, "source_generation": sg, "config_generation": cg},
        )
        assert res.waited is True and res.process_group_cleaned is True
        assert res.terminal["status"] == "failed"
        assert "refresh-failure:" in res.stderr
        assert "authorization-failed" in res.stderr
        assert not cap_path.exists()


@pytest.mark.parametrize("interruption", ["sigkill", "timeout", "release"])
def test_worker_sigkill_and_timeout_supervision(monkeypatch: pytest.MonkeyPatch, interruption: str) -> None:
    with _refresh_harness() as (store, cap_dir, _, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        store.submit(_req_norm("supervision", sg, cg, eg, kg))
        epoch = store.acquire_singleton("inst-sup", timedelta(seconds=300))
        claim = store.claim_next("inst-sup", epoch, timedelta(seconds=300))
        assert claim is not None
        trigger = cap_dir / "trigger"
        trigger.touch()
        ready = Path(f"{trigger}.ready")
        killed = threading.Event()
        def killer() -> None:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if ready.exists():
                    try:
                        for line in ready.read_text().splitlines():
                            if line.startswith("pid="):
                                if interruption == "release":
                                    trigger.unlink()
                                else:
                                    os.kill(int(line.split("=", 1)[1]), signal.SIGKILL)
                                killed.set()
                                return
                    except (OSError, ValueError):
                        pass
                time.sleep(0.02)
        thread = threading.Thread(target=killer) if interruption != "timeout" else None
        key = "_REPOMAP_SYSTEM_TEST_PAUSE_PATH" if thread else "_REPOMAP_SYSTEM_TEST_TIMEOUT_TRIGGER"
        monkeypatch.setenv(key, str(trigger))
        cap_path, _ = _make_worker_capability(postgres, cap_dir, config, claim, sg, cg, eg, kg)
        if thread:
            thread.start()
        try:
            result = run_refresh_worker(
                cap_path, {"job_id": claim.job_id, "attempt": claim.attempt}, coordinator_test_limits(),
                job_context={"graph_id": claim.graph_id, "source_generation": sg, "config_generation": cg},
            )
        finally:
            trigger.unlink(missing_ok=True)
            ready.unlink(missing_ok=True)
            if thread:
                thread.join(timeout=16)
        assert result.waited and result.process_group_cleaned
        assert result.synthesized_terminal == (interruption != "release")
        assert result.terminal["status"] == ("succeeded" if interruption == "release" else "failed")
        assert result.terminal["error_category"] == (None if interruption == "release" else "worker_crash" if thread else "worker_timeout")
        assert result.terminal["publication_state"] == ("committed" if interruption == "release" else "commit_unknown")
        if thread:
            assert not thread.is_alive() and killed.is_set()
        else:
            assert result.process_timed_out
        assert not cap_path.exists()
        assert store.stop_singleton("inst-sup", epoch)


@pytest.mark.parametrize("invalid", ["job", "graph", "time", "diagnostic", "messages"])
def test_worker_protocol_identity_and_limits_validation(invalid: str) -> None:
    with _refresh_harness() as (store, cap_dir, _, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        store.submit(_req_norm("protocol", sg, cg, eg, kg))
        epoch = store.acquire_singleton("inst-proto", timedelta(seconds=300))
        claim = store.claim_next("inst-proto", epoch, timedelta(seconds=300))
        assert claim is not None
        path, _ = _make_worker_capability(postgres, cap_dir, config, claim, sg, cg, eg, kg)
        identity = {"job_id": "different-job" if invalid == "job" else claim.job_id, "attempt": claim.attempt}
        context = {"graph_id": "different-graph" if invalid == "graph" else claim.graph_id, "source_generation": sg, "config_generation": cg}
        limits = coordinator_test_limits()
        if invalid == "time":
            limits.process_deadline_seconds = -1
            limits.refresh_attempt_deadline_seconds = 0
        elif invalid == "diagnostic":
            limits.max_diagnostic_bytes = 70000
        elif invalid == "messages":
            limits.max_array_items = 0
        exception = ProtocolError if invalid in {"job", "graph"} else ValueError
        with pytest.raises(exception):
            run_refresh_worker(path, identity, limits, job_context=context)
        assert not path.exists()
        assert store.status(claim.job_id).state == "claimed"
        assert store.stop_singleton("inst-proto", epoch)
