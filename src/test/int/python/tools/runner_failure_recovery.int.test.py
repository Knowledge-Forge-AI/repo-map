"""Real isolated discovery failures preserve diagnostics without qualification."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import coverage
import pytest

from repomap_test_support.d12_image_probes import restore_replay_shim_source
from repomap_test_support.test_scratch import establish_run, read_run_manifest
from repomap_test_support.runner_recovery_probe import probe_command
from runner_failure_evidence import CHILD_SCHEMA, DISCOVERY_SCHEMA, FAILURE_SCHEMA, read_diagnostic
import runner_staging_discovery as discovery
from runner_coverage import ChildCoverageSession, get_active_bootstrap_capability
from runner_coverage_execution import (
    is_runner_bootstrap_path,
    launch_observed_process,
    prepare_child_coverage_environment,
    read_registered_children,
    scrub_coverage_environment,
)
from staging_report_contract import execution_succeeded, qualifies

REPO = Path(__file__).resolve().parents[5]
IDENTITY = {"commit": "a" * 40, "source_sha256": "b" * 64}


def _diagnostic_child(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
    """Diagnostic tooling has no measurement authority; preserve the caller's environment."""
    environment = scrub_coverage_environment(kwargs.pop("env", os.environ))
    return subprocess.run(argv, env=environment, **kwargs)


@pytest.mark.parametrize("flag", ["-I", "-B"])
def test_diagnostic_children_do_not_inherit_measurement_authority(tmp_path: Path, monkeypatch, flag: str):
    """Synthetic source only: no local RepoMap project coverage is collected."""
    outer_env, outer_cap = dict(os.environ), get_active_bootstrap_capability()
    source = tmp_path / "synthetic-source"
    source.mkdir()
    (source / "fixture.py").write_text("VALUE = 1\n")
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / "session", source_root=source)
    try:
        with session, monkeypatch.context() as patch:
            patch.setenv("COVERAGE_UNRECOGNIZED_SENTINEL", "fixture")
            before = dict(os.environ)
            done = _diagnostic_child(
                [sys.executable, flag, "-c", "import json, os, sys; sys.path.insert(0, sys.argv[1]); import fixture; print(json.dumps({'keys': sorted(k for k in os.environ if k.startswith('COVERAGE_')), 'paths': sys.path}))", str(source)],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
            )
            assert done.returncode == 0, done.stderr
            observed = json.loads(done.stdout)
            assert observed["keys"] == []
            if flag == "-B":  # -I independently ignores PYTHONPATH at interpreter startup.
                assert str(session.bootstrap_dir) not in observed["paths"]
            assert dict(os.environ) == before
            assert not list(session.data_dir.glob(".coverage*"))
    finally:
        session.cleanup()
    assert dict(os.environ) == outer_env
    assert get_active_bootstrap_capability() is outer_cap


def test_canonical_invalid_exact_selector_retains_unestablished_failure(tmp_path: Path):
    """The child runs the real canonical CLI within the authenticated container."""
    reports = tmp_path / "reports"
    environment = os.environ.copy()
    for key in ("REPOMAP_TEST_RUN_ROOT", "GOCOVERDIR"):
        environment.pop(key, None)
    environment.update(REPOMAP_TEST_SCRATCH_ROOT=str(tmp_path / "scratch"),
                       REPOMAP_TEST_PHASE="CLOE-RUNNER-RECOVERY1-invalid-selector")
    result = _diagnostic_child(
        probe_command(REPO, reports, capacity_available=True),
        cwd=REPO, env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=150,
    )
    assert result.returncode == 1, (result.returncode, result.stdout[-2500:], result.stderr[-2500:])
    assert b"discovery-only recovery probe must never execute tests" not in result.stderr
    directory = reports / "int/latest"
    report = json.loads((directory / "staging_contract_report.json").read_text())
    artifacts = list(directory.glob("staging_discovery_diagnostic.*.json"))
    assert len(artifacts) == 1
    value = read_diagnostic(artifacts[0], DISCOVERY_SCHEMA)
    assert value["invocation_id"] == report["invocation_id"]
    assert value["candidate_at_start"] == report["candidate"]
    # Collection hooks can map the invalid node to INTERRUPTED or USAGE_ERROR.
    # Bind the diagnostic to the observed nonzero child and its validated receipt.
    assert value["process_exit"] in (2, 4) and value["receipt_exit"] == value["process_exit"], value
    assert value["primary"]["type"] == "PopulationDiscoveryError" and value["child_error"] is None
    assert value["partition_state"] == "not_established" and value["collected_count"] is None
    assert report["partition"] == {} and report["go_coverage"] is None
    assert not execution_succeeded(report) and not qualifies(report) and not qualifies(value)
    assert not list((tmp_path / "scratch").rglob("discovery-*"))
    failure_path = directory / f"runner_failure_report.{report['invocation_id']}.json"
    failure = read_diagnostic(failure_path, FAILURE_SCHEMA)
    assert failure["invocation_id"] == report["invocation_id"]
    assert failure["primary"]["stage"] == "discovery_collection"
    assert failure["primary"]["type"] == "PopulationDiscoveryError"


def test_discovery_probe_preserves_real_low_capacity_refusal(tmp_path: Path):
    reports = tmp_path / "reports"
    environment = os.environ.copy()
    for key in ("REPOMAP_TEST_RUN_ROOT", "GOCOVERDIR"):
        environment.pop(key, None)
    scratch = tmp_path / "scratch"
    environment.update(REPOMAP_TEST_SCRATCH_ROOT=str(scratch),
                       REPOMAP_TEST_PHASE="CLOE-RUNNER-RECOVERY1-low-capacity")
    result = _diagnostic_child(
        probe_command(REPO, reports, capacity_available=False), cwd=REPO,
        env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=150,
    )
    assert result.returncode == 2
    assert b"discovery-only recovery probe must never execute tests" not in result.stderr
    assert b"host_admission_refused: free_disk_reserve" in result.stderr
    assert not list(reports.rglob("staging_contract_report.json"))
    manifests = list(scratch.glob("r/*/manifest.json"))
    assert len(manifests) == 1
    terminal = read_run_manifest(manifests[0].parent)
    assert (terminal["state"], terminal["exit_status"], terminal["live_runtime_residue"]) == ("failed", 2, False)
    assert not list(scratch.rglob("discovery-*"))


def test_real_child_failure_retains_safe_record_and_settles_process_group(tmp_path: Path):
    script = tmp_path / "controlled_child.py"
    pid_path = tmp_path / "child.pid"
    script.write_text(
        "from pathlib import Path\nimport os, sys\n"
        f"Path({str(pid_path)!r}).write_text(str(os.getpid()))\n"
        f"sys.path.insert(0, {str(REPO / 'tools')!r})\n"
        "from runner_failure_evidence import CHILD_SCHEMA, error_record, persist_diagnostic\n"
        "persist_diagnostic(Path(sys.argv[2]).with_name('child_error.json'),\n"
        "    {'schema': CHILD_SCHEMA, 'error': error_record(KeyError('opaque-fixture'), 'child_collection')})\n"
        "raise SystemExit(17)\n"
    )
    root = establish_run().tmp
    before = set(root.glob("discovery-*"))
    args = SimpleNamespace(suite="int", report_dir=tmp_path / "reports")
    with pytest.raises(discovery.PopulationDiscoveryError):
        discovery.discover_staging_population(
            args, [], repo_root=REPO, source_root=REPO / "src/main/python",
            test_support_root=REPO / "src/test/support/python", invocation_id="real-child",
            candidate_identity=IDENTITY, scoped=True, child_script_path=script,
        )
    assert set(root.glob("discovery-*")) == before
    path = args.report_dir / "int/latest/staging_discovery_diagnostic.real-child.json"
    value = read_diagnostic(path, DISCOVERY_SCHEMA)
    assert value["primary"]["type"] == "PopulationDiscoveryError"
    assert value["process_exit"] == 17 and value["receipt_exit"] is None
    assert value["child_error"]["type"] == "KeyError"
    assert "opaque-fixture" not in path.read_text()
    assert not qualifies(value)
    with pytest.raises(ProcessLookupError):
        os.killpg(int(pid_path.read_text()), 0)


def test_real_child_request_refusal_retains_typed_startup_failure(tmp_path: Path):
    request, receipt = tmp_path / "request.json", tmp_path / "receipt.json"
    request.write_text('{"unrecognized": "opaque-fixture"}')
    request.chmod(0o600)
    done = _diagnostic_child(
        [sys.executable, "-I", str(REPO / "tools/runner_staging_discovery_child.py"),
         str(request), str(receipt)], cwd=REPO, stdin=subprocess.DEVNULL,
        capture_output=True, timeout=15,
    )
    assert done.returncode == 2 and not receipt.exists()
    path = tmp_path / "child_error.json"
    value = read_diagnostic(path, CHILD_SCHEMA)
    assert value["error"]["stage"] == "child_startup"
    assert value["error"]["type"] == "PopulationDiscoveryError"
    assert b"opaque-fixture" not in done.stdout + done.stderr + path.read_bytes()


def test_measured_python_descendants_register_and_combine_through_restore_shim(
    tmp_path: Path,
) -> None:
    """Measured parent Python and nested shebang pg_restore shim children register and combine cleanly."""
    outer_env, outer_cap = dict(os.environ), get_active_bootstrap_capability()
    base = tmp_path.resolve()
    source = base / "synthetic-source"
    source.mkdir()
    fixture_file = source / "fixture.py"
    fixture_file.write_text(
        "def probe(v: int) -> int:\n    return v + 1 if v > 0 else 0\n",
        encoding="utf-8",
    )
    bin_dir = base / "bin"
    bin_dir.mkdir()
    real_restore = bin_dir / "pg_restore"
    real_restore.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-l\" ]; then\n"
        "  printf 'TOC:%s\\n' \"$2\"\n"
        "  exit 3\n"
        "fi\n"
        "printf 'CREATE TABLE t(id int);\\nSET transaction_timeout = 0;\\nINSERT INTO t VALUES (1);\\n'\n",
        encoding="utf-8",
    )
    real_restore.chmod(0o755)
    psql_argv_out = base / "psql-argv.txt"
    psql_sql_out = base / "psql-stdin.sql"
    real_psql = bin_dir / "psql"
    real_psql.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {str(psql_argv_out)!r}\n"
        f"cat > {str(psql_sql_out)!r}\n",
        encoding="utf-8",
    )
    real_psql.chmod(0o755)
    restore_shim = base / "pg_restore_shim.py"
    restore_shim.write_text(
        restore_replay_shim_source(sys.executable, real_restore, real_psql),
        encoding="utf-8",
    )
    restore_shim.chmod(0o755)
    parent_code = (
        "import json, os, subprocess, sys\n"
        "import fixture\n"
        "assert fixture.probe(2) == 3 and fixture.probe(0) == 0\n"
        "shim, archive = sys.argv[1], sys.argv[2]\n"
        "toc = subprocess.run([shim, '-l', archive], capture_output=True, text=True)\n"
        "subprocess.run(\n"
        "    [shim, '-h', '127.0.0.1', '-p', '5432', '-U', 'u', '-d', 'd12_restore',\n"
        "     '--exit-on-error', '--single-transaction', archive],\n"
        "    check=True,\n"
        "    capture_output=True,\n"
        "    text=True,\n"
        ")\n"
        "print(json.dumps({'pid': os.getpid(), 'toc_rc': toc.returncode, 'toc_out': toc.stdout.strip()}))\n"
    )
    session = ChildCoverageSession(
        coverage_module=coverage,
        scratch_dir=base / "session",
        source_root=source,
        suite="int",
    )
    try:
        with session:
            env = prepare_child_coverage_environment(
                os.environ,
                family="cli_module",
                source_root=source,
            )
            completed = launch_observed_process(
                [sys.executable, "-c", parent_code, str(restore_shim), str(base / "sample.dump")],
                family="cli_module",
                env=env,
                pid_namespace_relation="shared",
                check=True,
                text=True,
            )
            parent_result = json.loads(completed.stdout)
            assert parent_result["toc_rc"] == 3
            assert parent_result["toc_out"] == f"TOC:{base / 'sample.dump'}"
            assert psql_argv_out.read_text(encoding="utf-8").splitlines() == [
                "-h", "127.0.0.1", "-p", "5432", "-U", "u", "-d", "d12_restore",
                "--single-transaction", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
            ]
            assert psql_sql_out.read_text(encoding="utf-8") == (
                "CREATE TABLE t(id int);\nINSERT INTO t VALUES (1);\n"
            )
            obs_files = list(session.observation_dir.glob("parent_obs_*.json"))
            assert len(obs_files) == 1
            reg_failures = list(session.child_manifest_dir.glob("*.registration_failure"))
            assert reg_failures == []
            children = read_registered_children(
                session.child_manifest_dir,
                expected_invocation=session.invocation_id,
                expected_suite="int",
            )
            assert len(children) == 3
            parent_children = [
                (pid, info) for pid, info in children.items() if info.get("launch_shape") == "cpython:-c"
            ]
            shim_children = [
                info
                for info in children.values()
                if str(info.get("launch_shape", "")).startswith("script:pg_restore_shim.py")
            ]
            assert len(parent_children) == 1
            assert len(shim_children) == 2
            parent_pid, parent_info = parent_children[0]
            assert parent_pid == parent_result["pid"]
            assert parent_info["ppid"] == os.getpid()
            assert parent_info["exited"] is True and parent_info["strict"] is True
            assert parent_info["measurement"] == "selected_hits"
            assert all(c["ppid"] == parent_result["pid"] for c in shim_children)
            assert all(c["exited"] is True and c["strict"] is True for c in shim_children)
            assert all(c["measurement"] == "no_selected_hits" for c in shim_children)
            combined = session.combine()
            assert combined is not None
            assert session.source_rejections == []
            data = combined.get_data()
            assert set(data.measured_files()) == {str(fixture_file)}
            lines = data.lines(str(fixture_file)) or []
            assert 1 in lines and 2 in lines
    finally:
        session.cleanup()
    assert dict(os.environ) == outer_env
    assert get_active_bootstrap_capability() is outer_cap


def test_lost_bootstrap_orphan_child_remains_rejected(tmp_path: Path) -> None:
    """Overwriting PYTHONPATH while keeping COVERAGE_PROCESS_START produces a rejected orphan shard."""
    assert any((Path(p) / "a1_coverage.pth").is_file() for p in sys.path if p)
    outer_env, outer_cap = dict(os.environ), get_active_bootstrap_capability()
    base = tmp_path.resolve()
    source = base / "synthetic-source"
    source.mkdir()
    (source / "fixture.py").write_text(
        "def orphan_probe() -> int:\n    return 7\n",
        encoding="utf-8",
    )
    session = ChildCoverageSession(
        coverage_module=coverage,
        scratch_dir=base / "session",
        source_root=source,
        suite="int",
    )
    try:
        with session:
            non_bootstrap_paths = [
                p for p in sys.path
                if p and not is_runner_bootstrap_path(p, capability=session.bootstrap_capability)
            ]
            broken_env = dict(
                os.environ,
                PYTHONPATH=os.pathsep.join([str(source), *non_bootstrap_paths]),
            )
            assert "COVERAGE_PROCESS_START" in broken_env
            done = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import json, os, fixture; assert fixture.orphan_probe() == 7; "
                    "print(json.dumps({'pid': os.getpid()}))",
                ],
                env=broken_env,
                check=True,
                capture_output=True,
                text=True,
            )
            orphan_pid = int(json.loads(done.stdout)["pid"])
            shards = sorted(session.data_dir.glob(f".coverage.*.pid{orphan_pid}.*"))
            assert len(shards) == 1
            assert not (session.child_manifest_dir / f"{orphan_pid}.start").exists()
            assert not list(session.observation_dir.glob("parent_obs_*.json"))
            with pytest.raises(RuntimeError, match="unregistered coverage shard rejected") as exc_info:
                session.combine()
            message = str(exc_info.value)
            assert f"pid{orphan_pid}" in message
            unregistered = [
                snap.to_dict()
                for snap in session.diagnostic_snapshots
                if snap.shard_name == shards[0].name
            ]
            assert len(unregistered) == 1
            record = unregistered[0]
            assert record["file_type"] == "unregistered"
            assert record["termination_outcome"] == "unregistered_child"
            assert record["launch_role"] == "unregistered"
            assert record["launch_shape"] == "cpython:-c"
            assert record["failure_class"] == "valid_sqlite"
            assert record["child_probe_id"] == f"pid={orphan_pid}"
    finally:
        session.cleanup()
    assert dict(os.environ) == outer_env
    assert get_active_bootstrap_capability() is outer_cap
