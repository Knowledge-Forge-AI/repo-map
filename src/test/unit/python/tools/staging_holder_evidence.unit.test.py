"""Coverage settlement and invalidation for lock holders that spawn descendants."""

import os
from pathlib import Path

import coverage

from runner_coverage import ChildCoverageSession

def test_hold_and_spawn_abrupt_kill_settlement_produces_complete_receipt_and_clean_combine(tmp_path: Path) -> None:
    """Prove HOLD_AND_SPAWN with abrupt=True produces complete .exit, valid shard, and clean combine on kill_holder."""
    import sqlite3
    from runner_coverage_execution import read_registered_children
    from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
    from repomap_test_support.sqlite_local_harness import LocalHarness
    from repomap_test_support.sqlite_local_lock_children import HOLD_AND_SPAWN, kill_holder, start_holder

    source = write_shell_source(tmp_path / "sources" / "vault")
    home = write_sqlite_home(tmp_path / "home", graph_toml("vault", source, privacy="private-ops"))
    harness = LocalHarness(tmp_path / "harness_scratch", block_psycopg=True)
    db = home / "graphs" / "vault" / "g.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "vault")

    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / "cov", suite="int")
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            keep_read, keep_write = os.pipe()
            try:
                child, ready = start_holder(db, harness.environment(), HOLD_AND_SPAWN, keep_open=keep_read, abrupt=True)
                assert ready.startswith("ready ")
                kill_holder(child)
            finally:
                os.close(keep_write)
                os.close(keep_read)
                child.communicate()
            runner.stop()
            runner.save()

            # 1. Terminal receipt is complete and bound to correct child identity
            records = read_registered_children(session.child_manifest_dir, session.session_dir.name, "int")
            assert int(str(child.pid)) in records
            rec = records[int(str(child.pid))]
            assert rec["exited"] is True

            exit_content = (session.child_manifest_dir / f"{child.pid}.exit").read_text(encoding="utf-8")
            assert f"pid={child.pid}" in exit_content
            assert "complete=1" in exit_content

            # 2. Referenced coverage shard is valid and non-corrupt SQLite
            shard_path = Path((session.child_manifest_dir / f"{child.pid}.shard").read_text(encoding="utf-8").strip())
            assert shard_path.exists()
            with sqlite3.connect(shard_path) as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA integrity_check;")
                res = cur.fetchone()[0]
                assert res == "ok"

            # 3. Coverage combine accepts the shard cleanly without measurement errors
            combined = session.combine(runner)
            assert not session.measurement_errors
            assert not getattr(runner, "_instrumentation_error", None)
            assert combined.get_data().measured_files()
    finally:
        session.cleanup()


def test_hold_and_spawn_abrupt_child_unexpectedly_released_invalidates_receipt_and_raises(tmp_path: Path) -> None:
    """Prove an abrupt HOLD_AND_SPAWN child released instead of killed invalidates receipt and raises."""
    from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
    from repomap_test_support.sqlite_local_harness import LocalHarness
    from repomap_test_support.sqlite_local_lock_children import HOLD_AND_SPAWN, release_holder, start_holder

    source = write_shell_source(tmp_path / "sources" / "vault")
    home = write_sqlite_home(tmp_path / "home", graph_toml("vault", source, privacy="private-ops"))
    harness = LocalHarness(tmp_path / "harness_scratch", block_psycopg=True)
    db = home / "graphs" / "vault" / "g.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "vault")

    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / "cov", suite="int")
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            keep_read, keep_write = os.pipe()
            try:
                child, ready = start_holder(db, harness.environment(), HOLD_AND_SPAWN, keep_open=keep_read, abrupt=True)
                assert ready.startswith("ready ")
                release_holder(child)
            finally:
                os.close(keep_write)
                os.close(keep_read)
                _, stderr = child.communicate()
            runner.stop()
            runner.save()
            assert child.returncode != 0
            assert "abrupt termination lock child was released instead of killed" in stderr

            exit_file = session.child_manifest_dir / f"{child.pid}.exit"
            assert exit_file.exists()
            exit_content = exit_file.read_text(encoding="utf-8")
            assert "complete=0" in exit_content
    finally:
        session.cleanup()


