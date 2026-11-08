"""Real worker/publication evidence followed by explicit retained settlement."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import stat
from collections.abc import Callable
from dataclasses import replace
from common_lore_index.artifacts import ExtractionReceipt
from common_lore_index.artifacts._canonical import canonical_json
import select
import subprocess
import sys
import time

from repomap_test_support.cli_in_process import module_process_environment
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_sqlite_home
from repomap_test_support.sqlite_managed_child import ManagedChild, cleanup_after_failure
from runner_coverage_observer import popen_observed_process


import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from common_lore_index.cli.main import main
from common_lore_index.ops import portable_refresh
from common_lore_index.ops._retained_attempt_record import BACKUP_NAME
from common_lore_index.ops._retained_attempt_record import read_retained_record
from common_lore_index.ops._retained_attempt_artifacts import RetainedArtifactError, read_retained_artifacts
from common_lore_index.ops.retained_attempt_recovery import RetainedAttemptRecovery, recover_server_retained_attempt
from common_lore_index.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_test_support.postgres_harness import PostgresCluster, require_postgres_binaries, temporary_postgres
from repomap_test_support.server_retained_recovery_fixture import (
    direct_authority, home_files, prepare_retained_server, publish_unsettled,
)


def test_real_historical_publication_inspect_settle_and_cli_without_reexecution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        capture = publish_unsettled(fixture, monkeypatch, "retained-first")
        original = capture.result_path.read_bytes()
        assert json.loads(original)["retention_class"] == "publication-reconciliation"
        newer = portable_refresh.execute_portable_refresh(
            fixture.config, fixture.graph, postgres.database,
            authority=direct_authority(fixture, "retained-newer"),
        )
        conninfo = make_conninfo(**_psycopg_connection_params_from_psql_args(postgres.psql_args))
        with psycopg.connect(conninfo) as connection:
            before_runs = connection.execute("SELECT count(*), max(id) FROM public.runs").fetchone()
        assert before_runs is not None and before_runs[0] == 2
        assert before_runs[1] == newer.summary.run_id

        def no_work(*args: object, **kwargs: object) -> None:
            raise AssertionError("recovery attempted source capture or worker execution")

        monkeypatch.setattr(portable_refresh, "capture_portable_candidate", no_work)
        monkeypatch.setattr(portable_refresh, "run_portable_worker", no_work)
        monkeypatch.setattr(portable_refresh, "seal_configured_sources", no_work)
        before_files = home_files(fixture.home)
        inspected = recover_server_retained_attempt(
            fixture.config, fixture.graph.id, "retained-first", 1,
            psql_command=postgres.psql_command,
        )
        assert inspected.exit_code == 0 and inspected.result == "ready"
        assert inspected.publication_proof == inspected.artifact_proof == "matched"
        assert home_files(fixture.home) == before_files
        assert capture.result_path.read_bytes() == original

        output = io.StringIO()
        with redirect_stdout(output):
            code = main([
                "ops", "retained-attempt", "inspect", "--repo-map-home", str(fixture.home),
                "--graph", fixture.graph.id, "--operation-id", "retained-first", "--attempt", "1",
                "--psql-command", postgres.psql_command, "--json",
            ])
        assert code == 0 and json.loads(output.getvalue()) == inspected.to_jsonable()
        assert home_files(fixture.home) == before_files
        assert all(value not in output.getvalue() for value in (
            str(fixture.home), fixture.graph.id, "retained-first", "sha256:",
        ))

        settled = recover_server_retained_attempt(
            fixture.config, fixture.graph.id, "retained-first", 1,
            settle=True, psql_command=postgres.psql_command,
        )
        assert settled.exit_code == 0 and settled.result == "settled"
        backup = capture.result_path.parent / BACKUP_NAME
        assert backup.read_bytes() == original
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600
        accepted = json.loads(capture.result_path.read_bytes())
        assert accepted["retention_class"] == "terminal-accepted"
        assert type(accepted["expires_at_epoch"]) is int
        accepted_bytes = capture.result_path.read_bytes()
        again = recover_server_retained_attempt(
            fixture.config, fixture.graph.id, "retained-first", 1,
            settle=True, psql_command=postgres.psql_command,
        )
        assert again.exit_code == 0 and again.result == "already-settled"
        assert capture.result_path.read_bytes() == accepted_bytes
        assert backup.read_bytes() == original
        with psycopg.connect(conninfo) as connection:
            assert connection.execute("SELECT count(*), max(id) FROM public.runs").fetchone() == before_runs


_RECOVERY_FIELDS = {
    "operation", "result", "reason", "retention_state", "artifact_proof",
    "publication_proof", "metadata_write_state",
}


def _assert_recovery_payload(outcome: RetainedAttemptRecovery, expected: dict[str, str]) -> None:
    payload = outcome.to_jsonable()
    assert set(payload) == _RECOVERY_FIELDS
    assert payload == expected


def _run_marker(postgres: PostgresCluster) -> tuple[int, int | None]:
    conninfo = make_conninfo(
        **_psycopg_connection_params_from_psql_args(postgres.psql_args)
    )
    with psycopg.connect(conninfo) as connection:
        row = connection.execute(
            "SELECT count(*), max(id) FROM public.runs"
        ).fetchone()
    assert row is not None
    return int(row[0]), None if row[1] is None else int(row[1])


def test_real_corrupt_referenced_bundle_is_held_without_metadata_or_new_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        capture = publish_unsettled(fixture, monkeypatch, "retained-corrupt")
        record_before = capture.result_path.read_bytes()
        bundle_path = capture.store.object_path(capture.bundle_reference)
        bundle_before = bundle_path.read_bytes()
        assert bundle_before
        bundle_path.write_bytes(bundle_before[:-1] + bytes([bundle_before[-1] ^ 1]))
        before_runs = _run_marker(postgres)
        try:
            outcome = recover_server_retained_attempt(
                fixture.config, fixture.graph.id, "retained-corrupt", 1,
                settle=True, psql_command=postgres.psql_command,
            )
            _assert_recovery_payload(outcome, {
                "operation": "settle", "result": "held", "reason": "artifact-invalid",
                "retention_state": "publication-reconciliation", "artifact_proof": "invalid",
                "publication_proof": "not-checked", "metadata_write_state": "not-attempted",
            })
            assert capture.result_path.read_bytes() == record_before
            assert not (capture.result_path.parent / BACKUP_NAME).exists()
            assert _run_marker(postgres) == before_runs
        finally:
            bundle_path.write_bytes(bundle_before)


_RETENTION_LOCK_SCRIPT = r"""
import sys
from pathlib import Path
from common_lore_index.ops._server_retention_lock import ServerRetentionLock

with ServerRetentionLock(Path(sys.argv[1])):
    sys.stderr.buffer.write(b"retention-lock-ready-v1\n")
    sys.stderr.buffer.flush()
    if sys.stdin.buffer.read(1) != b"x":
        raise RuntimeError("retention lock release token missing")
"""


def _wait_retention_lock(child: ManagedChild) -> None:
    stream = child.stderr
    assert stream is not None
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        readable, _, _ = select.select([stream], [], [], 0.25)
        if not readable:
            if child.poll() is not None:
                _, stderr = child.communicate(timeout=2)
                raise AssertionError("lock holder exited before readiness")
            continue
        if stream.readline() == b"retention-lock-ready-v1\n":
            return
    raise AssertionError("lock holder did not complete the readiness handshake")


def test_real_retention_lock_busy_holds_metadata_and_run_count_steady(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        capture = publish_unsettled(fixture, monkeypatch, "retained-lock")
        raw = popen_observed_process(
            [sys.executable, "-c", _RETENTION_LOCK_SCRIPT,
             str(capture.result_path.parent.parent)],
            family="cli_module", cwd=tmp_path, env=module_process_environment(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=False, pid_namespace_relation="shared", start_new_session=True,
        )
        child = ManagedChild(raw, group_owned=True)
        try:
            _wait_retention_lock(child)
            before_files = home_files(fixture.home)
            before_runs = _run_marker(postgres)
            outcome = recover_server_retained_attempt(
                fixture.config, fixture.graph.id, "retained-lock", 1,
                settle=True, psql_command=postgres.psql_command,
            )
            _assert_recovery_payload(outcome, {
                "operation": "settle", "result": "held", "reason": "lock-busy",
                "retention_state": "publication-reconciliation", "artifact_proof": "matched",
                "publication_proof": "matched", "metadata_write_state": "not-attempted",
            })
            assert home_files(fixture.home) == before_files
            assert _run_marker(postgres) == before_runs
            assert not (capture.result_path.parent / BACKUP_NAME).exists()
        finally:
            try:
                stdin = child.stdin
                assert stdin is not None
                stdin.write(b"x")
                stdin.flush()
                _, stderr = child.communicate(timeout=60)
                child.verify_dead_and_group()
            except BaseException as error:
                cleanup_after_failure(child, error)
                raise
        assert child.returncode == 0, stderr


def test_cli_refuses_sqlite_home_before_server_recovery(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    home = write_sqlite_home(tmp_path / "sqlite-home", graph_toml("local", source))
    output = io.StringIO()
    with redirect_stdout(output):
        code = main([
            "ops", "retained-attempt", "inspect", "--repo-map-home", str(home),
            "--graph", "local", "--operation-id", "unsupported", "--attempt", "1",
            "--json",
        ])
    assert code == 1
    assert json.loads(output.getvalue()) == {
        "operation": "inspect", "result": "refused", "reason": "sqlite-backend",
        "retention_state": "unavailable", "artifact_proof": "not-checked",
        "publication_proof": "not-checked", "metadata_write_state": "not-attempted",
    }


def _repoint_retained_objects(
    capture: portable_refresh.PortableCapture, bundle_bytes: bytes, *,
    receipt_change: Callable[[ExtractionReceipt], ExtractionReceipt] | None = None,
) -> None:
    old_receipt = ExtractionReceipt.from_bytes(capture.store.read(capture.receipt_reference))
    bundle_ref = capture.store.put(
        bundle_bytes,
        media_type=capture.bundle_reference.media_type,
        record_format=capture.bundle_reference.record_format,
        privacy=capture.bundle_reference.privacy,
    )
    receipt = replace(old_receipt, bundle_reference=bundle_ref)
    if receipt_change is not None:
        receipt = receipt_change(receipt)
    receipt = receipt.reidentify()
    receipt_ref = capture.store.put(
        receipt.canonical_bytes(),
        media_type=capture.receipt_reference.media_type,
        record_format=capture.receipt_reference.record_format,
        privacy=capture.receipt_reference.privacy,
    )
    payload = json.loads(capture.result_path.read_bytes())
    payload["receipt"] = receipt_ref.to_mapping()
    payload["bundle"] = bundle_ref.to_mapping()
    capture.result_path.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


@pytest.mark.parametrize("mutation", [
    "receipt-header", "receipt-cancellation", "bundle-identity", "header-vector",
    "unknown-family", "trailer-summary", "receipt-count", "header-framing",
    "header-keys", "header-types", "candidate-type", "header-values", "stage-contract",
    "record-shape", "record-order", "missing-trailer",
])
def test_real_rehashed_retained_objects_reach_deeper_artifact_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        capture = publish_unsettled(fixture, monkeypatch, "retained-deep-gate")
        original_record = capture.result_path.read_bytes()
        raw_bundle = capture.store.read(capture.bundle_reference)
        header_line, remainder = raw_bundle.split(b"\n", 1)
        before_runs = _run_marker(postgres)
        try:
            if mutation == "receipt-header":
                _repoint_retained_objects(
                    capture, raw_bundle,
                    receipt_change=lambda value: replace(value, graph_id="foreign-graph"),
                )
            elif mutation == "receipt-cancellation":
                _repoint_retained_objects(
                    capture, raw_bundle,
                    receipt_change=lambda value: replace(value, cancellation="requested"),
                )
            elif mutation == "bundle-identity":
                header = json.loads(header_line)
                header["candidate_id"] = "foreign-candidate"
                _repoint_retained_objects(capture, canonical_json(header) + remainder)
            elif mutation == "header-vector":
                header = json.loads(header_line)
                header["snapshot_vector"] = ["malformed-vector-item"]
                _repoint_retained_objects(capture, canonical_json(header) + remainder)
            elif mutation == "unknown-family":
                frames = [json.loads(line) for line in raw_bundle.splitlines()]
                frames[1]["family"] = "foreign-family"
                _repoint_retained_objects(capture, b"".join(canonical_json(frame) for frame in frames))
            elif mutation == "trailer-summary":
                frames = [json.loads(line) for line in raw_bundle.splitlines()]
                frames[-1]["families"][0]["record_count"] += 1
                _repoint_retained_objects(capture, b"".join(canonical_json(frame) for frame in frames))
            elif mutation == "receipt-count":
                _repoint_retained_objects(
                    capture, raw_bundle,
                    receipt_change=lambda value: replace(
                        value, family_counts={**value.family_counts, "files": value.family_counts["files"] + 1},
                    ),
                )
            elif mutation in {"header-keys", "header-types", "candidate-type", "header-values", "stage-contract"}:
                header = json.loads(header_line)
                if mutation == "header-keys":
                    del header["graph_id"]
                else:
                    field, value = {"header-types": ("schema_version", True), "candidate-type": ("candidate_id", 7),
                                    "header-values": ("graph_id", "foreign-graph"),
                                    "stage-contract": ("row_stage_contract", "foreign-stage")}[mutation]
                    header[field] = value
                _repoint_retained_objects(capture, canonical_json(header) + remainder)
            elif mutation in {"record-shape", "record-order", "missing-trailer"}:
                frames = [json.loads(line) for line in raw_bundle.splitlines()]
                if mutation == "record-shape":
                    frames[1]["record"] = []
                elif mutation == "missing-trailer":
                    frames.pop()
                else:
                    index = next(i for i in range(1, len(frames) - 2) if frames[i].get("family") == frames[i + 1].get("family") and frames[i]["record"] != frames[i + 1]["record"])
                    frames[index], frames[index + 1] = frames[index + 1], frames[index]
                _repoint_retained_objects(capture, b"".join(canonical_json(frame) for frame in frames))
            else:
                header = json.loads(header_line)
                header["framing_version"] = "foreign-framing"
                _repoint_retained_objects(capture, canonical_json(header) + remainder)
            expected = {"receipt-header": "manifest-mismatch", "receipt-cancellation": "receipt-invalid",
                        "bundle-identity": "bundle-mismatch", "header-values": "bundle-mismatch",
                        "trailer-summary": "bundle-mismatch", "receipt-count": "receipt-mismatch"}.get(mutation, "bundle-invalid")
            with pytest.raises(RetainedArtifactError) as gate:
                read_retained_artifacts(read_retained_record(capture.result_path.parent), capture.store)
            assert str(gate.value) == expected
            outcome = recover_server_retained_attempt(
                fixture.config, fixture.graph.id, "retained-deep-gate", 1,
                settle=True, psql_command=postgres.psql_command,
            )
            _assert_recovery_payload(outcome, {
                "operation": "settle", "result": "held", "reason": "artifact-invalid",
                "retention_state": "publication-reconciliation", "artifact_proof": "invalid",
                "publication_proof": "not-checked", "metadata_write_state": "not-attempted",
            })
            assert not (capture.result_path.parent / BACKUP_NAME).exists()
            assert _run_marker(postgres) == before_runs
        finally:
            capture.result_path.write_bytes(original_record)
