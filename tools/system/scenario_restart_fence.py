"""Durable prior-attempt readback and storage-bound rejection for restart tests."""

from __future__ import annotations

import json
from typing import Any, Callable

from tools.system.config import SystemTestError


def _build_stale_refresh_probe_script(
    *,
    job_id: str,
    initial_attempt: int,
    initial_instance: str,
    initial_epoch: int,
    initial_lease_epoch: int,
    generations: dict[str, str],
    graph_id: str,
    handoff: dict[str, Any],
) -> str:
    # Service config resolver creds INTERNAL nosecretoutput:
    # All database credentials and routing are resolved internally inside
    # the container by ConfiguredRefreshResolver without leaking secrets.
    return f"""
import os
import shutil
import sys
from pathlib import Path

import psycopg
from repomap_kg.storage.staged_publication import execute_final_transaction, existing_stage_state
from repomap_kg.storage.staged_ingestion import IngestionAuthority
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.publication import publication_receipt_from_mapping
from repomap_kg.storage.publication_fencing import PublicationHandoff
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.runtime.database_role_contract import REFRESH_PUBLICATION_ROLE, read_role_secrets
from repomap_kg.runtime.release import PACKAGED_PSQL

home = Path(os.environ.get("REPOMAP_HOME", "/repo-map-home"))
psql = Path(shutil.which("psql") or os.environ.get("REPOMAP_PACKAGED_PSQL", PACKAGED_PSQL))
role_secrets = read_role_secrets(home / "runtime" / ".env")
resolver = ConfiguredRefreshResolver(home, psql, postgres_user=REFRESH_PUBLICATION_ROLE,
                                     postgres_password=role_secrets.refresh_publication)
resolved = resolver._snapshot({graph_id!r}, discover_source=False)
checkpoint = {handoff!r}
authority = IngestionAuthority(
    operation_id=OperationId({job_id!r}), job_id=JobId({job_id!r}),
    attempt=AttemptNumber({int(initial_attempt)}), execution_mode="coordinator",
    source_generation={generations['source_generation']!r},
    config_generation={generations['config_generation']!r},
    extractor_generation={generations['extractor_generation']!r},
    canonicalizer_generation={generations['canonicalizer_generation']!r},
    coordinator_instance_id={initial_instance!r},
    singleton_fencing_epoch={int(initial_epoch)},
    graph_lease_fencing_epoch={int(initial_lease_epoch)},
)

# Resume the exact handoff produced before the crash. Replaying ingestion
# would test its earlier graph-claim refusal and never reach this boundary.
receipt = publication_receipt_from_mapping(checkpoint["receipt"])
owner = authority.owner(checkpoint["repository_id"])
handoff = PublicationHandoff(MergeContext(checkpoint["stage_id"], owner, checkpoint["run_id"]), receipt).validate()
params = _psycopg_connection_params_from_psql_args(resolved.psql_args)
params["password"] = resolved.password
try:
    with psycopg.connect(**params) as connection:
        connection.execute("SET LOCAL lock_timeout = '1s'")
        connection.execute("SET LOCAL statement_timeout = '5s'")
        if existing_stage_state(connection, handoff.merge.stage_id, owner) != "validated":
            raise ValueError("crashed worker validated stage is unavailable")
        try:
            execute_final_transaction(connection, handoff)
        except psycopg.errors.RaiseException as error:
            connection.rollback()
            if "SCALE5 stale publication fence" in str(error):
                sys.stderr.write("SCALE5 stale publication fence\\n")
                sys.exit(1)
            raise
        connection.rollback()
        sys.stderr.write("probe did not observe durable storage refusal\\n")
        sys.exit(0)
except Exception as exc:
    sys.stderr.write(f"probe rejection: {{type(exc).__name__}}\\n")
    sys.exit(2)

"""


def verify_restart_fence(compose_dir, plan, timer, *, job_id: str,
                         coordinator_evidence: dict[str, Any], durable: dict[str, Any],
                         authority: dict[str, Any], env: dict[str, str],
                         run_compose: Callable[..., Any]) -> dict[str, Any]:
    initial_attempt = coordinator_evidence['initial_attempt']
    initial_instance = coordinator_evidence['initial_instance_id']
    initial_epoch = coordinator_evidence['initial_singleton_fencing_epoch']
    old_attempts = [
        row for row in durable.get("attempt_history", [])
        if row.get("attempt") == initial_attempt
    ]
    if len(old_attempts) != 1 or old_attempts[0] != {
        "attempt": initial_attempt, "publication_state": "not_started",
        "instance_id": initial_instance, "singleton_epoch": initial_epoch,
    }:
        raise SystemTestError("crashed prior attempt did not durably reconcile to not_started")

    initial_lease_epoch = coordinator_evidence["initial_graph_lease_fencing_epoch"]
    graph_id = durable["graph_id"]
    probe_script = _build_stale_refresh_probe_script(
        job_id=job_id,
        initial_attempt=initial_attempt,
        initial_instance=initial_instance,
        initial_epoch=initial_epoch,
        initial_lease_epoch=initial_lease_epoch,
        generations=coordinator_evidence["initial_generations"],
        graph_id=graph_id,
        handoff=coordinator_evidence["initial_publication_handoff"],
    )

    # Prove durable publication and counts remain unchanged after rejection of stale attempt
    repo_id = authority["repository_id"]
    readback_sql = (
        f"SELECT json_build_object("
        f"'attempt', gpa.attempt, "
        f"'singleton_fencing_epoch', gpa.singleton_fencing_epoch, "
        f"'coordinator_instance_id', gpa.coordinator_instance_id, "
        f"'latest_run_id', gpa.last_run_id, "
        f"'files_count', ("
        f"SELECT count(*) FROM files WHERE repository_id = {repo_id}), "
        f"'canonical_nodes_count', (SELECT count(*) FROM canonical_nodes WHERE repository_id = {repo_id}), "
        f"'canonical_edges_count', (SELECT count(*) FROM canonical_edges WHERE repository_id = {repo_id}), "
        f"'runs_count', ("
        f"SELECT count(*) FROM runs WHERE repository_id = {repo_id} AND status = 'complete')"
        f") "
        f"FROM graph_publication_authority AS gpa "
        f"WHERE gpa.repository_id = {repo_id};"
    )
    def readback():
        readback_res = run_compose(
            compose_dir,
            [
                "exec", "-T", "postgres", "psql", "-XAt",
                "-U", plan.user, "--dbname", plan.database, "--file", "-",
            ],
            env=env,
            timer=timer,
            timeout=30.0,
            check=False,
            stdin_input=readback_sql,
        )
        if readback_res.returncode != 0 or not readback_res.stdout.strip():
            raise SystemTestError("failed to read back publication state after restart fence probe")
        try:
            current_pub = json.loads(readback_res.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as err:
            raise SystemTestError("malformed publication readback after restart fence probe") from err
        return current_pub

    before = readback()
    fence_probe = run_compose(
        compose_dir,
        ["exec", "-T", "coordinator", "python", "-"],
        env=env,
        timer=timer,
        timeout=30.0,
        check=False,
        stdin_input=probe_script,
    )
    if fence_probe.returncode == 0:
        raise SystemTestError(
            "crashed worker authority was not rejected by the storage publication fence"
        )
    if fence_probe.returncode != 1 or "SCALE5 stale publication fence" not in fence_probe.stderr:
        raise SystemTestError(
            "storage publication fence probe failed before proving stale-authority refusal: "
            f"exit={fence_probe.returncode}; setup, precondition, or process failure"
        )

    current_pub = readback()
    if before != current_pub:
        raise SystemTestError("durable publication was mutated by rejected stale attempt")

    for key in ("attempt", "singleton_fencing_epoch", "coordinator_instance_id", "latest_run_id"):
        expected_val = authority.get(key)
        if expected_val is not None and current_pub.get(key) != expected_val:
            raise SystemTestError(
                f"durable publication was mutated by rejected stale attempt: {key} mismatch"
            )

    return {
        'prior_attempt_reconciliation': old_attempts[0],
        'orphan_publication_fence_rejected': True,
        'durable_publication_unchanged': True,
        'publication_counts': {
            'files_count': current_pub.get('files_count', 0),
            'runs_count': current_pub.get('runs_count', 0),
        },
    }


def control_evidence_sql() -> str:
    return (
        "SELECT json_build_object('job_id', j.job_id, 'graph_id', j.graph_id, "
        "'idempotency_digest', j.idempotency_digest, 'state', j.state, "
        "'source_generation', a.source_generation, 'config_generation', a.config_generation, "
        "'extractor_generation', a.extractor_generation, 'canonicalizer_generation', a.canonicalizer_generation, "
        "'attempt_history', (SELECT json_agg(json_build_object('attempt', h.attempt, "
        "'publication_state', h.publication_state, 'instance_id', h.coordinator_instance_id, "
        "'singleton_epoch', h.fencing_epoch) ORDER BY h.attempt) FROM job_attempts h WHERE h.job_id = j.job_id), "
        "'current_attempt', j.current_attempt, 'coordinator_instance_id', a.coordinator_instance_id, "
        "'singleton_fencing_epoch', a.fencing_epoch, 'graph_lease_fencing_epoch', a.graph_lease_fencing_epoch) "
        "FROM jobs AS j JOIN job_attempts AS a ON a.job_id = j.job_id AND a.attempt = j.current_attempt "
        "LEFT JOIN graph_leases AS gl ON gl.job_id = a.job_id AND gl.attempt = a.attempt "
        "WHERE j.job_id = :'job_id'"
    )
