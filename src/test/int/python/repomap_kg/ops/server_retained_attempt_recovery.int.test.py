"""Real worker/publication evidence followed by explicit retained settlement."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import stat

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from common_lore_index.cli.main import main
from common_lore_index.ops import portable_refresh
from common_lore_index.ops._retained_attempt_record import BACKUP_NAME
from common_lore_index.ops.retained_attempt_recovery import recover_server_retained_attempt
from common_lore_index.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
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
