"""Containerized D9-B fault, custody and cooperating-actor exclusion proofs on real owned clusters.

Native boundaries: real pg_restore failure under --exit-on-error, real TOC path collision,
real advisory-lock exclusion of a second cooperating actor, real compensation drops.
Injected boundaries (orchestration only, labelled per case): lost CREATE acknowledgment
after a real CREATE, external FORCE replacement, operator interruption and TOC cleanup failure.
Injected triggers with native observation: client wrappers that rewrite a control record
to name the postmaster, for the preflight archive listing and for a compensation DROP.
"""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from repomap_kg.runtime._extension_restore_exec import bound_exec_custody
from repomap_kg.runtime._extension_restore_toc import (
    DerivedTocPlan,
)
from repomap_kg.runtime._extension_restore_toc_custody import (
    private_derived_toc_custody,
)
from repomap_kg.runtime.backup import dump_database, init_database_from_dump
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import build_local_runtime_plan
from repomap_kg.runtime.maintenance import MAINTENANCE_LOCK_KEY, MaintenanceUnavailableError, maintenance_activity
from repomap_kg.runtime.release import PACKAGED_PSQL
from repomap_test_support.d9_extension_policies import (
    installed_synthetic_extensions, probe_live_container_qualification, synthetic_multilevel_extension_policy,
)
from repomap_test_support.d9_extension_restore import (
    clean_template_reference, database_names, engine_container_id, owned_d9_postgres_cluster, seed_synthetic_graph,
)
from repomap_test_support.local_db_backup import connect_real_postgres as _connect
from repomap_test_support.postgres_harness import require_postgres_binaries
from repomap_test_support.test_scratch import short_test_directory

GRAPH = "d9b_fault_graph"
# Rewrites this invocation's control record to name the postmaster, in a subshell that keeps "$@".
POSTMASTER_RECORD = (
    '( for d in /tmp/repomap-ext-exec-*-"$REPOMAP_EXT_INVOCATION"; do read -r s < /proc/1/stat; s="${s##*) }"; '
    'set -- $s; printf \'1 %s %s\\n\' "${20}" "$REPOMAP_EXT_INVOCATION" > "$d/proc"; done )'
)


def _record_wrapper(binary: str, pattern: str) -> str:
    return (
        f"mv {binary} {binary}.real && cat <<'EOF' > {binary}\n#!/bin/sh\n"
        f'for a in "$@"; do case "$a" in {pattern}) {POSTMASTER_RECORD} ;; esac; done\n'
        f'exec {binary}.real "$@"\nEOF\nchmod 0755 {binary}'
    )


def _toc_dirs(runner: Any, container: str, prefix: str = "repomap-ext-toc-") -> list[str]:
    res = runner(["docker", "exec", "-i", container, "find", "/tmp", "-maxdepth", "1", "-name", f"{prefix}*"], capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stderr
    return sorted(res.stdout.split())


def _pid1_start(runner: Any, container: str) -> str:
    stat = runner(["docker", "exec", container, "cat", "/proc/1/stat"], capture_output=True, text=True, check=True).stdout
    return str(stat.split(") ", 1)[1].split()[19])


def _ledgers(home: Path) -> list[dict[str, Any]]:
    return [entry for p in sorted((home / "runtime").glob(".restore-intents-*/intents.json")) for entry in json.loads(p.read_text(encoding="utf-8"))]


def _clear_ledgers(home: Path) -> None:
    for p in (home / "runtime").glob(".restore-intents-*"):
        shutil.rmtree(p)


def _force_drop(postgres: Any, db: str) -> None:
    with closing(_connect(postgres, autocommit=True)) as adm:
        adm.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')


def _is_replay(cmd: list[str]) -> bool:
    return "/usr/bin/pg_restore" in cmd and any(tok.startswith("--use-list=") for tok in cmd)


def test_d9b_fault_matrix_custody_and_cooperating_actor_exclusion(monkeypatch: pytest.MonkeyPatch) -> None:
    require_postgres_binaries()
    with short_test_directory("d9b-flt-", "home/repomap.rpl.toml") as directory:
        root = Path(directory)
        home = root / "home"
        reference = clean_template_reference(root)
        with owned_d9_postgres_cluster(home, graph_db=GRAPH) as (identity, postgres, runner):
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", str(postgres.password))
            monkeypatch.setenv("POSTGRES_PASSWORD", str(postgres.password))
            container = identity.postgres_container
            with installed_synthetic_extensions("docker", container, runner=runner):
                qual = probe_live_container_qualification(container, user=postgres.user, template_baseline_sha256=reference)
                policy = synthetic_multilevel_extension_policy(owner=postgres.user, artifact_qualification=qual)
                seed_synthetic_graph(postgres, GRAPH)
                dump = dump_database(home, database=GRAPH, timestamp="20261021T050000Z", command_runner=runner, extension_restore_policy=policy)
                assert dump.restore_supported is True, f"blockers: {dump.restore_blockers}"
                archive = dump.plan.backup_path / "dump.pgcustom"
                archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
                _force_drop(postgres, GRAPH)
                before = database_names(postgres)

                def restore(command_runner: Any) -> Any:
                    return init_database_from_dump(home, database=GRAPH, backup=dump.plan.backup_path, command_runner=command_runner, extension_restore_policy=policy)

                # Native: a preexisting TOC path is preserved byte-for-byte; nothing is removed.
                toc_plan = DerivedTocPlan(GRAPH, "a" * 64, b";\n", hashlib.sha256(b";\n").hexdigest(), 0, (), ())
                pre_dir = f"/tmp/repomap-ext-toc-{identity.home_hash}-{GRAPH}-collide"
                runner(["docker", "exec", "-i", container, "sh", "-euc", f"mkdir {pre_dir} && printf keep > {pre_dir}/sentinel"], check=True)
                with pytest.raises(LocalDbBackupError) as pre_exc, bound_exec_custody(engine_container_id(container)):
                    with private_derived_toc_custody(build_local_runtime_plan(home), GRAPH, toc_plan, runner, invocation_token="collide"):
                        raise AssertionError("custody must not be yielded on collision")
                assert [d.code for d in pre_exc.value.diagnostics] == ["restore-toc-custody-failed"]
                assert runner(["docker", "exec", "-i", container, "cat", f"{pre_dir}/sentinel"], capture_output=True, text=True, check=True).stdout == "keep"
                runner(["docker", "exec", "-i", container, "rm", "-r", pre_dir], check=True)

                # Native: real pg_restore failure under --exit-on-error (a conflicting schema created mid-protocol).
                wrap = (
                    "mv /usr/bin/pg_restore /usr/bin/pg_restore.real && cat <<'EOF' > /usr/bin/pg_restore\n#!/bin/sh\n"
                    f'for a in "$@"; do case "$a" in --use-list=*) psql -U {postgres.user} -d {GRAPH} -c "CREATE SCHEMA app_ext;" >/dev/null ;; esac; done\n'
                    'exec /usr/bin/pg_restore.real "$@"\nEOF\nchmod 0755 /usr/bin/pg_restore'
                )
                runner(["docker", "exec", "-i", "-u", "root", container, "sh", "-euc", wrap], check=True)
                try:
                    with pytest.raises(LocalDbBackupError) as mid_exc:
                        restore(runner)
                finally:
                    runner(["docker", "exec", "-i", "-u", "root", container, "sh", "-euc", "mv -f /usr/bin/pg_restore.real /usr/bin/pg_restore"], check=True)
                assert [d.code for d in mid_exc.value.diagnostics] == ["local-db-command-failed"], f"compensated failure keeps only the primary: {mid_exc.value.diagnostics}"
                assert database_names(postgres) == before and _toc_dirs(runner, container) == [] and not _ledgers(home)

                # Injected acknowledgment loss after a real CREATE: outcome unknown, target and ledger retained.
                def lost_ack(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
                    result = runner(cmd, **{**kwargs, "check": False})
                    if any("CREATE DATABASE" in str(tok) for tok in cmd):
                        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"connection lost before acknowledgment")
                    return result

                with pytest.raises(LocalDbBackupError) as lost_exc:
                    restore(lost_ack)
                assert "restore-target-ownership-unknown" in [d.code for d in lost_exc.value.diagnostics]
                assert GRAPH in database_names(postgres) and [e["state"] for e in _ledgers(home)] == ["outcome_unknown"], "unknown outcome is retained"
                _force_drop(postgres, GRAPH)
                _clear_ledgers(home)

                # Injected external FORCE replacement: the held custody connection is terminated, so nothing is dropped.
                def replaced(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
                    if _is_replay(cmd):
                        _force_drop(postgres, GRAPH)
                        with closing(_connect(postgres, autocommit=True)) as adm:
                            adm.execute(f'CREATE DATABASE "{GRAPH}"')
                        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"replay aborted")
                    return runner(cmd, **{**kwargs, "check": False})

                with pytest.raises(LocalDbBackupError) as rep_exc:
                    restore(replaced)
                assert "restore-target-ownership-mismatch" in [d.code for d in rep_exc.value.diagnostics]
                with closing(_connect(postgres, GRAPH)) as foreign:
                    assert foreign.execute("SELECT count(*) FROM pg_namespace WHERE nspname = 'ext_alpha_s'").fetchone() == (0,), "replacement retained untouched"
                _force_drop(postgres, GRAPH)
                _clear_ledgers(home)
                for leftover in _toc_dirs(runner, container):
                    runner(["docker", "exec", "-i", container, "rm", "-r", leftover], check=True)

                # Injected interruption plus TOC cleanup failure: the interrupt survives with notes; the held target is compensated.
                def interrupted(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
                    if _is_replay(cmd):
                        raise KeyboardInterrupt("operator interrupt")
                    if any("rmdir" in str(tok) for tok in cmd):
                        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"rm failed")
                    return runner(cmd, **{**kwargs, "check": False})

                with pytest.raises(KeyboardInterrupt) as kb_exc:
                    restore(interrupted)
                notes = getattr(kb_exc.value, "__notes__", ())
                assert any("restore-toc-cleanup-failed" in n for n in notes), f"notes: {notes}"
                assert database_names(postgres) == before and not _ledgers(home), "a held, verified target is compensated after interruption"
                retained = _toc_dirs(runner, container)
                assert len(retained) == 1, "an owned TOC directory whose cleanup failed is retained and reported, not silently removed"
                runner(["docker", "exec", "-i", container, "rm", "-r", retained[0]], check=True)

                # Native preflight retention: the listing outcome is unknown, so a durable typed record
                # names the exact retained control path and refuses the next attempt before any command.
                pid1 = _pid1_start(runner, container)
                runner(["docker", "exec", "-u", "root", container, "sh", "-euc", _record_wrapper("/usr/bin/pg_restore", "-l")], check=True)
                try:
                    with pytest.raises(LocalDbBackupError) as pre_unknown:
                        restore(runner)
                finally:
                    runner(["docker", "exec", "-u", "root", container, "mv", "-f", "/usr/bin/pg_restore.real", "/usr/bin/pg_restore"], check=True)
                assert [d.code for d in pre_unknown.value.diagnostics] == ["restore-exec-outcome-unknown"], pre_unknown.value.diagnostics
                retained = _toc_dirs(runner, container, "repomap-ext-exec-")
                records = sorted((home / "runtime").glob(".restore-exec-record-*/record.json"))
                assert len(records) == 1 and len(retained) == 1 and not _ledgers(home), "a command record, not a target ledger"
                record = json.loads(records[0].read_text(encoding="utf-8"))
                assert (record["record_type"], record["phase"], record["owned_targets"], record["container_id"]) == (
                    "repomap-extension-exec-record-v1", "preflight", [], engine_container_id(container))
                assert [(c["label"], c["remote"], c["control"], c["control_path"]) for c in record["exec_unknown"]] == [
                    ("dump.pgcustom", "mismatch", "retained", retained[0])]
                with pytest.raises(LocalDbBackupError) as refused:
                    restore(runner)
                assert [d.code for d in refused.value.diagnostics] == ["restore-exec-outcome-unknown"]
                assert _toc_dirs(runner, container, "repomap-ext-exec-") == retained and _pid1_start(runner, container) == pid1
                assert database_names(postgres) == before
                runner(["docker", "exec", "-u", "root", container, "rm", "-r", *retained], check=True)  # operator intervention
                shutil.rmtree(records[0].parent)

                # Native compensation-time unknown: a real replay failure, then the forced DROP's own
                # outcome becomes unknown. The DROP really ran; the ledger still retains the record.
                runner(["docker", "exec", "-i", "-u", "root", container, "sh", "-euc", wrap], check=True)
                runner(["docker", "exec", "-u", "root", container, "sh", "-euc", _record_wrapper(PACKAGED_PSQL, '"DROP DATABASE"*')], check=True)
                try:
                    with pytest.raises(LocalDbBackupError) as drop_exc:
                        restore(runner)
                finally:
                    for binary in ("/usr/bin/pg_restore", PACKAGED_PSQL):
                        runner(["docker", "exec", "-u", "root", container, "mv", "-f", f"{binary}.real", binary], check=True)
                assert [d.code for d in drop_exc.value.diagnostics] == [
                    "local-db-command-failed", "failed-target-cleanup-failed", "restore-exec-outcome-unknown", "failed-target-cleanup-failed",
                ], drop_exc.value.diagnostics
                ledger = _ledgers(home)
                assert [e["state"] for e in ledger] == ["created"] and GRAPH not in database_names(postgres)
                assert [(r["label"], r["remote"], r["control"]) for r in ledger[0]["exec_unknown"]] == [("database drop", "mismatch", "retained")]
                retained = _toc_dirs(runner, container, "repomap-ext-exec-")
                assert [r["control_path"] for r in ledger[0]["exec_unknown"]] == retained and _pid1_start(runner, container) == pid1
                runner(["docker", "exec", "-u", "root", container, "rm", "-r", *retained], check=True)  # operator intervention
                _clear_ledgers(home)
                assert _toc_dirs(runner, container) == [] and database_names(postgres) == before

                # Native cooperating-actor exclusion at the replay seam, then a successful restore.
                observations: dict[str, Any] = {}

                def probing(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
                    if _is_replay(cmd) and not observations:
                        with closing(_connect(postgres, GRAPH, autocommit=True)) as actor:
                            observations["target_exclusive"] = actor.execute("SELECT pg_try_advisory_lock(%s)", (MAINTENANCE_LOCK_KEY,)).fetchone()
                            observations["target_shared"] = actor.execute("SELECT pg_try_advisory_lock_shared(%s)", (MAINTENANCE_LOCK_KEY,)).fetchone()
                        try:
                            with maintenance_activity(lambda: _connect(postgres, GRAPH, autocommit=True)):
                                observations["activity"] = "admitted"
                        except MaintenanceUnavailableError:
                            observations["activity"] = "refused"
                        with closing(_connect(postgres, "postgres", autocommit=True)) as actor:
                            observations["maintenance_exclusive"] = actor.execute("SELECT pg_try_advisory_lock(%s)", (MAINTENANCE_LOCK_KEY,)).fetchone()
                    return runner(cmd, **{**kwargs, "check": False})

                result = restore(probing)
                assert result.result == "success" and hashlib.sha256(archive.read_bytes()).hexdigest() == archive_sha
                assert observations == {"target_exclusive": (False,), "target_shared": (False,), "activity": "refused", "maintenance_exclusive": (False,)}, f"cooperating actors must be excluded: {observations}"
                assert _toc_dirs(runner, container) == [] and not _ledgers(home)
                with closing(_connect(postgres, GRAPH)) as g:
                    assert g.execute("SELECT ext_gamma_s.gamma_probe()").fetchone() == ("1.0:beta-1.0:gamma-1.0",)
