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

from repomap_test_support.test_scratch import establish_run
from runner_failure_evidence import CHILD_SCHEMA, DISCOVERY_SCHEMA, FAILURE_SCHEMA, read_diagnostic
import runner_staging_discovery as discovery
from runner_coverage import ChildCoverageSession, get_active_bootstrap_capability
from runner_coverage_execution import scrub_coverage_environment
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
    selector = "src/test/int/python/tools/runner_failure_recovery.int.test.py::test_missing_recovery_probe"
    result = _diagnostic_child(
        [sys.executable, "-B", str(REPO / "tools/run_tests.py"), "--suite", "int", "--no-coverage",
         "--jobs", "1", "--report-dir", str(reports), "--", selector],
        cwd=REPO, env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=150,
    )
    assert result.returncode == 1, (result.returncode, result.stdout[-2500:], result.stderr[-2500:])
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
