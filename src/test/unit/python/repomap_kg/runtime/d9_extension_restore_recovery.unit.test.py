"""Unit tests for D9-B native input custody, private TOC custody and compensating cleanup outcomes."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
import subprocess
from typing import Any

import pytest

from common_lore_index.runtime import _extension_restore_native as native_mod
from common_lore_index.runtime import _extension_restore_toc_custody as toc_mod
from common_lore_index.runtime._backup_provenance import parse_toc_entries
from common_lore_index.runtime._extension_restore_custody import DatabaseCreationIntent
from common_lore_index.runtime._extension_restore_exec import bound_exec_custody
from common_lore_index.runtime._extension_restore_lifecycle import cleanup_extension_restore_intents
from common_lore_index.runtime._extension_restore_native import owned_private_input, run_bounded_ext_command
from common_lore_index.runtime._extension_restore_toc import (
    build_derived_toc_plan,
)
from common_lore_index.runtime._extension_restore_toc_custody import (
    private_derived_toc_custody,
)
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.local import LocalRuntimeDiagnostic, build_local_runtime_plan, setup_local_runtime


def _make_runtime_home(tmp_path: Path) -> Any:
    home = tmp_path / "home"
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    setup_local_runtime(home)
    home.chmod(0o700)
    (home / "runtime").chmod(0o700)
    plan = build_local_runtime_plan(home)
    plan.env_file.chmod(0o600)
    return plan


def _sample_toc_plan() -> Any:
    raw_toc = b";\n6; 2615 16385 SCHEMA - repomap_vector repomap\n2; 3079 16387 EXTENSION - vector \n215; 1259 16500 TABLE public items repomap\n"
    cat = {
        "extension_config_tables": [], "extension_dependency_summary": {"by_class": {}, "edge_count": 0, "edges": []},
        "installed_extensions": [{"is_baseline": True, "name": "plpgsql", "schema": "pg_catalog"}, {"is_baseline": False, "name": "vector", "schema": "repomap_vector"}],
        "non_system_schemas": [{"name": "public", "owner": "repomap"}, {"name": "repomap_vector", "owner": "repomap"}],
    }
    return build_derived_toc_plan(raw_toc, database="repomap", database_catalog=cat, expected_toc_sha256=parse_toc_entries(raw_toc, database="repomap").toc_sha256)


def _stdin_residue(plan: Any) -> list[str]:
    return sorted(p.name for p in plan.runtime_dir.iterdir() if p.name.startswith(".ext-stdin-"))


def test_native_owned_input_handles_partial_writes_fsync_failure_and_interruption(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _make_runtime_home(tmp_path)
    real_write = os.write
    monkeypatch.setattr(native_mod.os, "write", lambda fd, data: real_write(fd, bytes(data[:3])))
    with owned_private_input(plan.runtime_dir, b"0123456789abcdef", field="probe") as path:
        assert path.read_bytes() == b"0123456789abcdef", "partial os.write results must be completed"
        assert (path.stat().st_mode & 0o777) == 0o600
    assert _stdin_residue(plan) == [], "owned input file must be removed after use"
    monkeypatch.setattr(native_mod.os, "write", real_write)

    def failing_fsync(fd: int) -> None:
        raise OSError("injected fsync failure")

    monkeypatch.setattr(native_mod.os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="injected fsync failure"):
        with owned_private_input(plan.runtime_dir, b"payload", field="probe"):
            pass
    assert _stdin_residue(plan) == [], "a failed acquisition must remove only the file it created"
    monkeypatch.undo()

    with pytest.raises(KeyboardInterrupt):
        with owned_private_input(plan.runtime_dir, b"payload", field="probe") as path:
            replaced = path.with_name(path.name + ".moved")
            path.rename(replaced)
            path.write_bytes(b"foreign")
            raise KeyboardInterrupt("operator interrupt")
    leftovers = _stdin_residue(plan)
    assert len(leftovers) == 2, "a replaced path is retained, never removed by name"
    for name in leftovers:
        (plan.runtime_dir / name).unlink()


def test_native_bounded_command_uses_real_process_custody_with_input_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _make_runtime_home(tmp_path)
    out = run_bounded_ext_command(plan, ["/bin/cat"], subprocess.run, field="cat", input_bytes=b"streamed-input\n")
    assert out == b"streamed-input\n" and _stdin_residue(plan) == []
    with pytest.raises(LocalDbBackupError) as timeout_exc:
        run_bounded_ext_command(plan, ["/bin/sleep", "5"], subprocess.run, field="sleep", input_bytes=b"x", timeout_seconds=0.5)
    assert "timed out" in timeout_exc.value.diagnostics[0].message and _stdin_residue(plan) == []
    with pytest.raises(LocalDbBackupError) as ceiling_exc:
        run_bounded_ext_command(plan, ["/bin/cat"], subprocess.run, field="cat", input_bytes=b"y" * 4096, max_output_bytes=16)
    assert "ceiling" in ceiling_exc.value.diagnostics[0].message and _stdin_residue(plan) == []

    def interrupted(*args: Any, **kwargs: Any) -> bytes:
        raise KeyboardInterrupt("injected interrupt during bounded process")

    monkeypatch.setattr(native_mod, "run_bounded_popen", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_bounded_ext_command(plan, ["/bin/cat"], subprocess.run, field="cat", input_bytes=b"z")
    assert _stdin_residue(plan) == [], "interruption still settles the owned input file"


# The fake runtime answers the container settlement exec as a settled, removed process
# without descendants, and the inherited-session settlement as zero remaining sessions.
_SETTLED = (
    "*UNAVAILABLE*) printf 'REMOTE killed\\nCONTROL removed\\nDESCENDANTS none\\n' ;; "
    "*pg_terminate_backend*) printf '0\\n0\\n' ;;"
)


def _fake_runtime(tmp_path: Path, body: str) -> str:
    script = tmp_path / "fake-runtime"
    script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    script.chmod(0o700)
    return str(script)


def test_toc_custody_native_timeout_settles_unknown_acquisition_by_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _make_runtime_home(tmp_path)
    marker = tmp_path / "probe-calls"
    runtime = _fake_runtime(tmp_path, f'case "$*" in {_SETTLED} *"echo present"*) echo probe >> "{marker}"; echo absent ;; *"rm -f"*) echo rm >> "{marker}" ;; *) exec /bin/sleep 5 ;; esac\n')
    plan = replace(base, container_runtime=runtime)
    monkeypatch.setattr(toc_mod, "TOC_CUSTODY_TIMEOUT_SECONDS", 0.5)
    with pytest.raises(LocalDbBackupError) as exc, bound_exec_custody("f" * 64):
        with private_derived_toc_custody(plan, "repomap", _sample_toc_plan(), subprocess.run, invocation_token="native-timeout"):
            raise AssertionError("custody must not be yielded after a timeout")
    assert [d.code for d in exc.value.diagnostics] == ["restore-toc-custody-failed"], "an absent probe means nothing was acquired"
    assert "timed out" in exc.value.diagnostics[0].message, "the native bounded timeout is the initiating error"
    assert marker.read_text(encoding="utf-8").split() == ["probe"], "unknown acquisition is settled by an existence probe, never rm"

    marker.unlink()
    plan2 = replace(base, container_runtime=_fake_runtime(tmp_path, f'case "$*" in {_SETTLED} *"echo present"*) echo probe >> "{marker}"; echo present ;; *"rm -f"*) echo rm >> "{marker}" ;; *) exec /bin/sleep 5 ;; esac\n'))
    with pytest.raises(LocalDbBackupError) as present_exc, bound_exec_custody("f" * 64):
        with private_derived_toc_custody(plan2, "repomap", _sample_toc_plan(), subprocess.run, invocation_token="native-present"):
            raise AssertionError("custody must not be yielded after a timeout")
    assert [d.code for d in present_exc.value.diagnostics] == ["restore-toc-custody-failed", "restore-toc-cleanup-failed"]
    assert "retained" in present_exc.value.diagnostics[1].message and marker.read_text(encoding="utf-8").split() == ["probe"]


def _prep_output(toc_plan: Any, *, status: str = "ok", meta: str | None = None) -> bytes:
    lines = ["DIR 1:100", "FILE 1:101"]
    if status == "ok":
        lines.append(meta or f"META 700 600 {len(toc_plan.derived_toc_bytes)} {toc_plan.derived_toc_sha256}")
    lines.append(f"STATUS {status}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_toc_custody_orchestration_preserves_preexisting_and_cleans_only_proven_identities(tmp_path: Path) -> None:
    plan = _make_runtime_home(tmp_path)
    toc_plan = _sample_toc_plan()
    calls: list[list[str]] = []

    def runner_for(prep: bytes, clean: bytes = b"CLEANED\n", clean_rc: int = 0) -> Any:
        def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            calls.append(cmd)
            joined = " ".join(cmd)
            if "mkdir -m 0700" in joined:
                return subprocess.CompletedProcess(cmd, 0, stdout=prep, stderr=b"")
            if "rmdir" in joined:
                return subprocess.CompletedProcess(cmd, clean_rc, stdout=clean, stderr=b"")
            return subprocess.CompletedProcess(cmd, 0, stdout=b"absent\n", stderr=b"")
        return run

    with private_derived_toc_custody(plan, "repomap", toc_plan, runner_for(_prep_output(toc_plan)), invocation_token="tok1") as toc_path:
        assert toc_path.endswith("/derived.toc") and toc_path.startswith("/tmp/repomap-ext-toc-")
    assert calls[-1][-2:] == ["1:100", "1:101"], "cleanup must carry the proven directory and file identities"

    calls.clear()
    with pytest.raises(LocalDbBackupError) as pre_exc:
        with private_derived_toc_custody(plan, "repomap", toc_plan, runner_for(b"STATUS preexisting\n"), invocation_token="tok2"):
            pass
    assert "preserved" in pre_exc.value.diagnostics[0].message and len(calls) == 1, "a preexisting path must never be cleaned"

    calls.clear()
    with pytest.raises(LocalDbBackupError) as mode_exc:
        with private_derived_toc_custody(plan, "repomap", toc_plan, runner_for(_prep_output(toc_plan, meta="META 755 600 1 x")), invocation_token="tok3"):
            pass
    assert mode_exc.value.diagnostics[0].code == "restore-toc-custody-failed" and calls[-1][-2:] == ["1:100", "1:101"]

    primary = LocalDbBackupError((LocalRuntimeDiagnostic("error", "local-db-command-failed", "pg_restore", "replay failed"),))
    with pytest.raises(LocalDbBackupError) as chained:
        with private_derived_toc_custody(plan, "repomap", toc_plan, runner_for(_prep_output(toc_plan), clean=b"", clean_rc=5), invocation_token="tok4"):
            raise primary
    assert [d.code for d in chained.value.diagnostics] == ["local-db-command-failed", "restore-toc-cleanup-failed"]

    with pytest.raises(KeyboardInterrupt) as kb_exc:
        with private_derived_toc_custody(plan, "repomap", toc_plan, runner_for(_prep_output(toc_plan), clean=b"", clean_rc=5), invocation_token="tok5"):
            raise KeyboardInterrupt("operator interrupt")
    assert any("restore-toc-cleanup-failed" in n for n in getattr(kb_exc.value, "__notes__", ())), "the initiating interrupt is preserved"


class _FakeAuthority:
    def __init__(self, held: set[str], verified: set[str], absent_after_drop: bool = True) -> None:
        self._held, self._verified, self._absent = held, verified, absent_after_drop

    def held(self, database: str) -> bool:
        return database in self._held

    def verify(self, intent: DatabaseCreationIntent, *, finalized: bool = False) -> bool:
        return intent.database in self._verified

    def oid_absent(self, oid: int) -> bool:
        return self._absent


def _fake_authority(held: set[str], verified: set[str]) -> Any:
    return _FakeAuthority(held, verified)


def test_compensation_drops_only_held_verified_targets_and_retains_unknown(tmp_path: Path) -> None:
    plan = _make_runtime_home(tmp_path)
    ledger = plan.runtime_dir / ".restore-intents-test" / "intents.json"
    primary = LocalDbBackupError((LocalRuntimeDiagnostic("error", "local-db-command-failed", "pg_restore", "boom"),))
    intents = [
        DatabaseCreationIntent("g_owned", "inv-0", "created", 16384, "sys"),
        DatabaseCreationIntent("g_replaced", "inv-1", "created", 16385, "sys"),
        DatabaseCreationIntent("g_lost_ack", "inv-2", "outcome_unknown"),
        DatabaseCreationIntent("g_unheld", "inv-3", "created_unheld"),
        DatabaseCreationIntent("g_never", "inv-4", "not_created"),
    ]
    drops: list[str] = []

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        drops.extend(tok for tok in cmd if "DROP DATABASE" in tok)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    authority: Any = _FakeAuthority(held={"g_owned", "g_replaced"}, verified={"g_owned"})
    with pytest.raises(LocalDbBackupError) as exc:
        cleanup_extension_restore_intents(plan, authority, intents, runner, primary_error=primary, coordinated=True, ledger_path=ledger)
    assert drops == ['DROP DATABASE "g_owned" WITH (FORCE);'], f"only the held, verified target may be dropped: {drops!r}"
    assert [d.code for d in exc.value.diagnostics] == [
        "local-db-command-failed", "restore-target-ownership-unknown", "restore-target-ownership-unknown",
        "restore-target-ownership-mismatch", "coordinated-restore-cleanup-failed",
    ]
    assert ledger.exists() and (ledger.stat().st_mode & 0o777) == 0o600 and intents[0].state == "cleaned"

    def failing_drop(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"drop failed")

    with pytest.raises(KeyboardInterrupt) as kb_exc:
        cleanup_extension_restore_intents(
            plan, _fake_authority(held={"g"}, verified={"g"}), [DatabaseCreationIntent("g", "inv", "created", 1, "sys")], failing_drop,
            primary_error=KeyboardInterrupt("ctrl-c"), coordinated=False, ledger_path=ledger,
        )
    assert any("failed-target-cleanup-failed" in n for n in getattr(kb_exc.value, "__notes__", ()))

    clean_ledger = plan.runtime_dir / ".restore-intents-clean" / "intents.json"
    clean_ledger.parent.mkdir(mode=0o700)
    clean_ledger.write_text("[]", encoding="utf-8")
    with pytest.raises(LocalDbBackupError) as ok_exc:
        cleanup_extension_restore_intents(
            plan, _fake_authority(held={"g"}, verified={"g"}), [DatabaseCreationIntent("g", "inv", "created", 1, "sys")], runner,
            primary_error=primary, coordinated=False, ledger_path=clean_ledger,
        )
    assert ok_exc.value is primary and not clean_ledger.parent.exists(), "full compensation re-raises the primary error and removes the ledger"
