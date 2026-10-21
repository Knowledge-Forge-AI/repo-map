"""Real SQL metadata and native command deadline boundaries for D9-A."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any

import psutil
import pytest

from repomap_kg.coordinator.local_lifecycle import initialize_coordinator_control
from repomap_kg.runtime._backup_observation import observe_database_provenance
from repomap_kg.runtime._backup_provenance import MAX_QUERY_OBSERVED_OUTPUT_BYTES, run_bounded_popen
from repomap_kg.runtime.backup import dump_database
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import build_local_runtime_plan
from repomap_kg.runtime.maintenance import MAINTENANCE_LOCK_KEY, maintenance_window
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.local_db_backup import connect_real_postgres, setup_real_backup_home
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.test_scratch import short_test_directory


@pytest.mark.parametrize("case,conditions", [(0, [None]), (1, []), (2, ["", "extra"]), (3, [" WHERE value > 0 "])])
def test_real_extcondition_arrays_are_not_padded_or_truncated(
    monkeypatch: pytest.MonkeyPatch, case: int, conditions: list[Any],
) -> None:
    require_postgres_binaries()
    with short_test_directory("d9-final-", "home/repomap.rpl.toml") as directory:
        home = Path(directory) / "home"
        with temporary_postgres() as postgres:
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", postgres.password)
            monkeypatch.setenv("POSTGRES_PASSWORD", postgres.password)
            database = f"d9_final_graph_{case}"
            _identity, runner = setup_real_backup_home(home, postgres, graph_db=database)
            handle = postgres.create_database(database)
            apply_migrations(default_rdbms_root(), handle.psql_args, psql_command=handle.psql_command)
            initialize_coordinator_control(home)
            with closing(connect_real_postgres(postgres, database, autocommit=True)) as connection:
                connection.execute("CREATE EXTENSION cube; CREATE TABLE d9_cfg_items(value int); INSERT INTO d9_cfg_items VALUES (7)")
                connection.execute(
                    "UPDATE pg_extension SET extconfig = ARRAY['d9_cfg_items'::regclass]::oid[], "
                    "extcondition = %s::text[] WHERE extname = 'cube'", (conditions,),
                )
            plan = build_local_runtime_plan(home)
            if conditions == [" WHERE value > 0 "]:
                observed = observe_database_provenance(plan, database, runner)
                extensions = observed.database_catalog["installed_extensions"]
                extension = next(item for item in extensions if item["name"] == "cube")
                assert extension["extcondition"] == conditions
                assert observed.database_catalog["extension_config_tables"][0]["condition"] == conditions[0]
                before = set((home / "backups").rglob("manifest.json"))
                for index, expression in enumerate(("(1/0)::text", "repeat('α', 1100000)")):
                    def guarded_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
                        if "repomap_d9_catalog_observation" not in " ".join(cmd):
                            return runner(cmd, **kwargs)
                        modified = [part.replace("version()", expression, 1) for part in cmd]
                        result = runner(modified, **kwargs)
                        if index == 0:
                            assert result.returncode != 0
                        else:
                            assert result.returncode == 0
                            assert isinstance(result.stdout, bytes)
                            assert result.stdout.startswith(b"OVERFLOW:")
                            assert len(result.stdout) < 128
                            assert int(result.stdout.partition(b":")[2]) > MAX_QUERY_OBSERVED_OUTPUT_BYTES
                        return result

                    with pytest.raises(LocalDbBackupError) as guard_error:
                        dump_database(
                            home, database=database, timestamp=f"20261020T0410{index:02d}Z",
                            command_runner=guarded_runner,
                        )
                    assert guard_error.value.diagnostics[0].code == "backup-observation-incomplete"
                    assert set((home / "backups").rglob("manifest.json")) == before
                    assert not list((home / "backups").rglob("*.partial*"))
            else:
                with pytest.raises(LocalDbBackupError) as observed_error:
                    observe_database_provenance(plan, database, runner)
                assert observed_error.value.diagnostics[0].code == "backup-observation-incomplete"
                before = set((home / "backups").rglob("manifest.json"))
                with pytest.raises(LocalDbBackupError) as backup_error:
                    dump_database(home, database=database, timestamp="20261020T040000Z", command_runner=runner)
                assert backup_error.value.diagnostics[0].code == "backup-observation-incomplete"
                assert set((home / "backups").rglob("manifest.json")) == before
                assert not list((home / "backups").rglob("*.partial*"))
            with closing(connect_real_postgres(postgres, database)) as connection:
                assert connection.execute("SELECT value FROM d9_cfg_items").fetchall() == [(7,)]


def test_linux_native_command_deadline_retires_inherited_output(tmp_path: Path) -> None:
    sh_cmd = shutil.which("sh") or "/bin/sh"
    sleep_cmd = shutil.which("sleep")
    assert Path(sh_cmd).is_file() and sleep_cmd is not None
    marker = tmp_path / "child-pid"
    program = '"$1" 2 & printf "%s" "$!" > "$2"'
    before = {thread.ident for thread in threading.enumerate()}
    with pytest.raises(LocalDbBackupError) as caught:
        run_bounded_popen(
            [sh_cmd, "-c", program, "sh", sleep_cmd, str(marker)], max_output_bytes=1024,
            timeout_seconds=1.0, error_code="backup-toc-inconsistent", field="repomap",
        )
    assert caught.value.diagnostics[0].code == "backup-toc-inconsistent"
    assert marker.is_file()
    assert not ({thread.ident for thread in threading.enumerate()} - before)
    child_pid = int(marker.read_text())
    deadline = time.monotonic() + 0.5
    while True:
        try:
            child = psutil.Process(child_pid)
            if not child.is_running() or child.status() == psutil.STATUS_ZOMBIE:
                break
        except psutil.NoSuchProcess:
            break
        assert time.monotonic() < deadline, "timed-out descendant remained active after process-group kill"
        time.sleep(0.01)


def test_real_maintenance_deadlines_and_lock_release() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        database = "d9_final_deadline"
        postgres.create_database(database)
        owner = connect_real_postgres(postgres, database, autocommit=True)
        with closing(connect_real_postgres(postgres, database, autocommit=True)) as observer:
            with maintenance_window(lambda: owner):
                assert owner.execute("SHOW lock_timeout").fetchone() == ("30s",)
                assert owner.execute("SHOW statement_timeout").fetchone() == ("30s",)
                assert observer.execute("SELECT pg_try_advisory_lock(%s)", (MAINTENANCE_LOCK_KEY,)).fetchone() == (False,)
            assert owner.closed
            deadline = time.monotonic() + 2.0
            while observer.execute("SELECT pg_try_advisory_lock(%s)", (MAINTENANCE_LOCK_KEY,)).fetchone() != (True,):
                assert time.monotonic() < deadline, "closed ownership connection did not release its lock"
                time.sleep(0.01)
            observer.execute("SELECT pg_advisory_unlock(%s)", (MAINTENANCE_LOCK_KEY,))
