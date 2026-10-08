"""Adversarial regression matrix for child coverage registration atomicity."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

import coverage
import pytest

from runner_coverage import ChildCoverageSession
from runner_coverage_execution import read_registered_children


def _setup_session(tmp_path: Path, suite: str = "int") -> ChildCoverageSession:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    (source / "mod.py").write_text("VALUE = 42\n", encoding="utf-8")
    return ChildCoverageSession(
        coverage_module=coverage,
        scratch_dir=tmp_path / "measure",
        source_root=source,
        suite=suite,
    )


def test_normal_registered_child_accepted(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            res = subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
            assert res.returncode == 0
            runner.stop()
            runner.save()
            registered = read_registered_children(
                session.child_manifest_dir, session.session_dir.name, "int"
            )
            assert len(registered) == 1
            pid, record = next(iter(registered.items()))
            assert record["cov_start"] == 1 and record["exited"]
            assert record["strict"] is True
            combined = session.combine(runner)
            assert combined is not None
    finally:
        session.cleanup()


def test_missing_manifest_authority_fails_closed(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            env = dict(os.environ)
            env.pop("COVERAGE_CHILD_MANIFEST_DIR", None)
            res = subprocess.run([sys.executable, "-c", "pass"], env=env, capture_output=True)
            assert res.returncode == 0
            shards_before_parent_save = [
                p for p in session.data_dir.iterdir() if p.name.startswith(".coverage.")
            ]
            assert not shards_before_parent_save
            runner.stop()
            runner.save()
            diag_files = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert len(diag_files) == 1
            diag_text = diag_files[0].read_text(encoding="utf-8")
            assert "failure_class=missing_manifest_authority" in diag_text
            assert "has_manifest=0" in diag_text
            registered = read_registered_children(
                session.child_manifest_dir, session.session_dir.name, "int"
            )
            assert len(registered) == 1
            rec = next(iter(registered.values()))
            assert rec["registration_failure"] is True
            assert rec["failure_class"] == "missing_manifest_authority"
            with pytest.raises(RuntimeError, match="missing_manifest_authority"):
                session.combine(runner)
            snap = session.diagnostic_snapshots[-1]
            assert snap.failure_class == "missing_manifest_authority"
            assert snap.termination_outcome == "registration_failed"
    finally:
        session.cleanup()


def test_marker_creation_collision_fails_closed(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            token = "f" * 32
            (session.child_manifest_dir / f"{token}.start").write_text("collision", encoding="utf-8")
            env = dict(os.environ, COVERAGE_CHILD_REGISTRATION_TOKEN=token)
            res = subprocess.run([sys.executable, "-c", "pass"], env=env, capture_output=True)
            assert res.returncode == 0
            runner.stop()
            runner.save()
            diag_files = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert len(diag_files) == 1
            diag_text = diag_files[0].read_text(encoding="utf-8")
            assert "failure_class=token_reuse" in diag_text
            registered = read_registered_children(
                session.child_manifest_dir, session.session_dir.name, "int"
            )
            rec = next(iter(registered.values()))
            assert rec["registration_failure"] is True
            with pytest.raises(RuntimeError, match="token_reuse"):
                session.combine(runner)
    finally:
        session.cleanup()


def test_stale_cross_invocation_registration_rejected(tmp_path):
    manifest = tmp_path / "child_procs"
    manifest.mkdir()
    (manifest / "101.start").write_text(
        "pid=101\ninvocation=stale_inv\nsuite=int\nrevision=rev1\nrole=inherited-python\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="child invocation identity mismatch"):
        read_registered_children(manifest, expected_invocation="fresh_inv", expected_suite="int")
    (manifest / "101.start").write_text(
        "pid=101\ninvocation=fresh_inv\nsuite=staging\nrevision=rev1\nrole=inherited-python\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="child suite identity mismatch"):
        read_registered_children(manifest, expected_invocation="fresh_inv", expected_suite="int")
    (manifest / "101.start").write_text(
        "pid=101\ninvocation=fresh_inv\nsuite=int\nrevision=stale_rev\nrole=inherited-python\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="child source identity mismatch"):
        read_registered_children(
            manifest, expected_invocation="fresh_inv", expected_suite="int", expected_revision="fresh_rev",
        )


def test_stale_cross_invocation_registration_failure_rejected(tmp_path):
    manifest = tmp_path / "child_procs"
    manifest.mkdir()
    (manifest / "101.registration_failure").write_text(
        "pid=101\ninvocation=stale_inv\nsuite=int\nrevision=rev1\nfailure_class=marker_collision\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="child invocation identity mismatch"):
        read_registered_children(manifest, expected_invocation="fresh_inv", expected_suite="int")


def test_token_reuse_rejected(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            tok = "a" * 32
            (session.child_manifest_dir / f"{tok}.start").write_text("prior_worker", encoding="utf-8")
            env = dict(os.environ, COVERAGE_CHILD_REGISTRATION_TOKEN=tok)
            subprocess.run([sys.executable, "-c", "pass"], env=env, capture_output=True)
            diag_files = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert len(diag_files) == 1
            content = diag_files[0].read_text(encoding="utf-8")
            assert "failure_class=token_reuse" in content
            assert f"token_hash={hashlib.sha256(tok.encode()).hexdigest()}" in content
            assert tok not in content.split("token_hash=")[0]
    finally:
        session.cleanup()


def test_grandchild_token_inheritance_neutralized(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            token = "t" * 32
            child_shard = session.data_dir / f".coverage.{token}"
            env = dict(
                os.environ,
                COVERAGE_CHILD_REGISTRATION_TOKEN=token,
                COVERAGE_FILE=str(child_shard),
                COVERAGE_CHILD_LAUNCH_ROLE="portable",
            )
            child_code = (
                "import subprocess, sys, os\n"
                "assert 'COVERAGE_CHILD_REGISTRATION_TOKEN' not in os.environ\n"
                "res = subprocess.run([sys.executable, '-c', "
                "'import os; assert \"COVERAGE_CHILD_REGISTRATION_TOKEN\" not in os.environ'], "
                "capture_output=True)\n"
                "sys.exit(res.returncode)\n"
            )
            res = subprocess.run([sys.executable, "-c", child_code], env=env, capture_output=True)
            assert res.returncode == 0, f"Child execution failed: {res.stderr.decode()}"
            runner.stop()
            runner.save()
            fail_markers = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert not fail_markers
    finally:
        session.cleanup()


def test_narrow_resource_tracker_boundary_preserved(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            lookalike = "from multiprocessing.resource_tracker import main; print('not tracker')"
            res = subprocess.run([sys.executable, "-c", lookalike], env=dict(os.environ), capture_output=True)
            assert res.returncode == 0
            runner.stop()
            runner.save()
            registered = read_registered_children(session.child_manifest_dir, session.session_dir.name, "int")
            rec = next(iter(registered.values()))
            assert rec["auxiliary"] is False
            assert rec["strict"] is True
            assert rec["role"] != "auxiliary-runtime"
    finally:
        session.cleanup()


def test_auxiliary_runtime_exempt_from_failure(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            tracker_cmd = "from multiprocessing.resource_tracker import main;main(42)"
            env = dict(os.environ)
            env.pop("COVERAGE_CHILD_MANIFEST_DIR", None)
            subprocess.run([sys.executable, "-c", tracker_cmd], env=env, capture_output=True)
            runner.stop()
            runner.save()
            fail_markers = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert not fail_markers
    finally:
        session.cleanup()


def test_registration_failure_precedence_over_stale_start(tmp_path):
    manifest = tmp_path / "child_procs"
    manifest.mkdir()
    pid = 4321
    (manifest / f"{pid}.start").write_text(
        f"pid={pid}\ninvocation=fresh_inv\nsuite=int\nrevision=rev1\nrole=inherited-python\ncov_start=1\n",
        encoding="utf-8",
    )
    (manifest / f"{pid}.registration_failure").write_text(
        f"pid={pid}\nppid=1\ninvocation=fresh_inv\nsuite=int\nrevision=rev1\n"
        f"role=inherited-python\nowner=\nlaunch_shape=script:test\n"
        f"has_config=1\nhas_manifest=1\nhas_token=0\ntoken_hash=\n"
        f"bootstrap_stage=marker_creation\nfailure_class=marker_collision\n"
        f"failure_reason=FileExistsError\n",
        encoding="utf-8",
    )
    registered = read_registered_children(manifest, expected_invocation="fresh_inv", expected_suite="int")
    assert pid in registered
    assert registered[pid].get("registration_failure") is True
    assert registered[pid].get("failure_class") == "marker_collision"


def test_child_lost_bootstrap_pythonpath_fails_closed(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            clean_env = dict(os.environ)
            clean_env["PYTHONPATH"] = str(tmp_path)
            child_script = (
                "import sys\n"
                "assert 'coverage' in sys.modules, 'coverage was not loaded by startup hook'\n"
                "sys.exit(0)\n"
            )
            res = subprocess.run([sys.executable, "-c", child_script], env=clean_env, capture_output=True)
            assert res.returncode == 0
            runner.stop()
            runner.save()
            from runner_portable_coverage import validate_shard_directory_integrity
            with pytest.raises(RuntimeError, match="unregistered coverage shard rejected"):
                validate_shard_directory_integrity(
                    session.data_dir, set(), None,
                    session._create_snapshot, session._record_diagnostic, coverage,
                )
    finally:
        session.cleanup()


def test_duplicate_process_startup_hook_coexistence(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            early_cov = coverage.Coverage(config_file=str(session.config_file))
            try:
                setattr(coverage.process_startup, "coverage", early_cov)
                early_cov._auto_save = True
                early_cov.start()
                assert coverage.process_startup() is None
                assert coverage.Coverage.current() is early_cov
            finally:
                early_cov._auto_save = False
                try:
                    early_cov.stop()
                except Exception:
                    pass
                if hasattr(coverage.process_startup, "coverage"):
                    delattr(coverage.process_startup, "coverage")
    finally:
        session.cleanup()


def test_scrub_coverage_environment_disarms_capability_atomically(tmp_path):
    from runner_coverage_execution import scrub_coverage_environment
    session_dir = tmp_path / "runner_session"
    session_dir.mkdir()
    (session_dir / "sitecustomize.py").write_text("# Runner-owned bootstrap: no product authority hooks are replaced.\n")
    fake_env = {
        "COVERAGE_PROCESS_START": "/path/to/rc", "COVERAGE_PROCESS_CONFIG": "data",
        "COVERAGE_FILE": "/path/to/cov", "COVERAGE_CHILD_MANIFEST_DIR": str(session_dir / "manifests"),
        "COVERAGE_CHILD_REGISTRATION_TOKEN": "token123", "COVERAGE_SESSION_INVOCATION_ID": "inv1",
        "PYTHONPATH": f"/user/lib:{session_dir}:/other/lib", "USER_VAR": "keep_me",
    }
    cleaned = scrub_coverage_environment(fake_env, session_dir=session_dir)
    assert not any(k.startswith("COVERAGE_") for k in cleaned)
    assert cleaned["USER_VAR"] == "keep_me"
    assert str(session_dir) not in cleaned.get("PYTHONPATH", "")
    assert cleaned["PYTHONPATH"] == "/user/lib:/other/lib"


def test_module_process_environment_avoids_duplicate_entries(tmp_path):
    from repomap_test_support.cli_in_process import module_process_environment
    from runner_coverage_bootstrap import install_bootstrap_directory
    m_dir = tmp_path / "child_procs"
    m_dir.mkdir()
    b_dir = install_bootstrap_directory(tmp_path / "bootstrap").parent
    ambient = {
        "COVERAGE_PROCESS_START": "/path/to/rc", "COVERAGE_CHILD_MANIFEST_DIR": str(m_dir),
        "PYTHONPATH": f"/existing/path:{b_dir}:/existing/path",
    }
    with pytest.MonkeyPatch.context() as mp:
        for k, v in ambient.items():
            mp.setenv(k, v)
        env = module_process_environment()
        parts = env["PYTHONPATH"].split(os.pathsep)
        assert len(parts) == len(set(parts))
        assert str(b_dir) in parts


def test_disarm_coverage_prevents_shard_on_failure(tmp_path):
    from runner_coverage_bootstrap import BOOTSTRAP_TEMPLATE

    shard_file = tmp_path / "test.shard"
    disarm_body = "def _disarm_coverage():" + BOOTSTRAP_TEMPLATE.split("def _disarm_coverage():")[1].split("def _write_reg_fail")[0]
    script = (
        "import coverage, os\n"
        f"cov = coverage.Coverage(data_file={str(shard_file)!r})\n"
        "cov.start()\ncov._auto_save = True\n"
        "setattr(coverage.process_startup, 'coverage', cov)\n"
        "os.environ['COVERAGE_PROCESS_START'] = _config = '/dummy'\n"
        f"{disarm_body}\n_disarm_coverage()\n"
        "assert cov._auto_save is False\n"
        "assert not hasattr(coverage.process_startup, 'coverage')\n"
        "assert 'COVERAGE_PROCESS_START' not in os.environ\n"
    )
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    env.update({"PYTHONNOUSERSITE": "1", "PYTHONPATH": ""})
    res = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    assert not shard_file.exists()


def test_registration_diagnostics_sanitized_and_bounded(tmp_path):
    session = _setup_session(tmp_path)
    try:
        with session:
            raw_token = "secrettoken123456789012345678901"
            (session.child_manifest_dir / f"{raw_token}.start").write_text("collision", encoding="utf-8")
            env = dict(os.environ, COVERAGE_CHILD_REGISTRATION_TOKEN=raw_token, SUPER_SECRET="my_password_123")
            subprocess.run([sys.executable, "-c", "pass"], env=env, capture_output=True)
            diag_files = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert len(diag_files) == 1
            content = diag_files[0].read_text(encoding="utf-8")
            assert "pid=" in content and "ppid=" in content
            assert "invocation=" in content and "suite=" in content
            assert "role=" in content and "has_token=1" in content
            assert "failure_class=token_reuse" in content
            assert raw_token not in content
            assert "my_password_123" not in content
            assert "SUPER_SECRET" not in content
            assert hashlib.sha256(raw_token.encode()).hexdigest() in content
    finally:
        session.cleanup()
