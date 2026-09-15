"""Composed isolated discovery, exact population and real measured collection."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import coverage
import pytest

from repomap_test_support.test_scratch import establish_run
from runner_coverage import ChildCoverageSession
from runner_integration_population import LegPartitionPytestPlugin
import runner_staging_discovery as discovery
from runner_staging_discovery_contract import (
    DISCOVERY_RECEIPT_SCHEMA, MAX_RECEIPT_BYTES, PopulationDiscoveryError,
    digest, discovery_failure_detail, validate_discovery_receipt, write_document,
)

REPO = Path(__file__).resolve().parents[5]
SUPPORT = REPO / "src/test/support/python"


def fixture_tree(tmp_path: Path):
    root = tmp_path / "fixture"
    source = root / "source"
    source.mkdir(parents=True)
    product = source / "discovery_test_product.py"
    product.write_text("INITIAL = 7\ndef choose(flag):\n    if flag:\n        return INITIAL\n    return 0\n")
    marker = root / "executed"
    test = root / "test_probe.py"
    test.write_text(
        "from pathlib import Path\nimport discovery_test_product as product\n"
        "def test_chosen():\n"
        f"    Path({str(marker)!r}).write_text('yes')\n"
        "    assert product.choose(True) == 7\n"
    )
    (root / "pytest.ini").write_text("[pytest]\naddopts = --import-mode=importlib\n")
    return root, source, product, test, marker


def discover(root: Path, source: Path, test: Path, **kwargs):
    return discovery.discover_staging_population(
        SimpleNamespace(suite="int"), [str(test), "--rootdir=" + str(root)],
        repo_root=root, source_root=source, test_support_root=SUPPORT,
        invocation_id="fixture-invocation", candidate_identity={"commit": "a" * 40, "source_sha256": "b" * 64},
        scoped=True, **kwargs,
    )


@pytest.mark.parametrize("enclosing", [False, True])
def test_real_discovery_and_m_collection_preserve_import_lines_and_arcs(tmp_path, enclosing):
    root, source, product, test, marker = fixture_tree(tmp_path)
    before = coverage.Coverage.current()
    outer = coverage.Coverage(branch=True, data_file=str(tmp_path / "outer"), config_file=False) if enclosing else None
    if outer is not None:
        outer.start()
    active = coverage.Coverage.current()
    scratch = establish_run().tmp
    old_discoveries = set(scratch.glob("discovery-*"))
    try:
        assert "discovery_test_product" not in sys.modules
        partition = discover(root, source, test)
        assert not marker.exists()
        assert "discovery_test_product" not in sys.modules
        assert coverage.Coverage.current() is active
        assert set(scratch.glob("discovery-*")) == old_discoveries
        assert partition.collected_nodes == ("test_probe.py::test_chosen",)
        assert partition.m_nodes == partition.all_nodes
        with pytest.raises(FrozenInstanceError):
            setattr(partition, "m_nodes", ())
        sys.path.insert(0, str(source))
        try:
            with ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / "m-session", source_root=source) as session:
                runner = session.create_coverage(coverage)
                runner.start()
                try:
                    plugin = LegPartitionPytestPlugin(partition, "M", suite="int", full_population=False)
                    result = pytest.main([str(test), "--rootdir=" + str(root), "-q"], plugins=[plugin])
                finally:
                    runner.stop()
                    runner.save()
                    combined = session.combine(runner)
                assert result == 0
                assert marker.read_text() == "yes"
                assert tuple(plugin.completed_nodeids) == partition.m_nodes
                data = combined.get_data()
                assert set(data.lines(str(product)) or []) == {1, 2, 3, 4}
                assert (3, 4) in (data.arcs(str(product)) or [])
                assert (3, 5) not in (data.arcs(str(product)) or [])
                assert combined.analysis2(str(product))[3] == [5]
            session.cleanup()
        finally:
            sys.path.remove(str(source))
            for name, module in tuple(sys.modules.items()):
                filename = getattr(module, "__file__", None)
                if filename and Path(filename).is_relative_to(root):
                    sys.modules.pop(name, None)
        assert coverage.Coverage.current() is active
    finally:
        if outer is not None:
            outer.stop()
            outer.get_data().close(force=True)
    assert coverage.Coverage.current() is before


def receipt_for(request):
    result = {"schema": DISCOVERY_RECEIPT_SCHEMA, "request_sha256": digest(request),
              "exit_code": 0, "error": None, "collected": ["one", "two"],
              "eligible": ["one", "two"], "deferred": []}
    result["sha256"] = digest(result)
    return result


@pytest.mark.parametrize("fault", ["missing", "truncated", "corrupt", "stale", "reordered", "duplicate",
                                    "nonzero", "extra", "symlink", "oversized", "boolean-exit"])
def test_discovery_receipt_refuses_invalid_artifacts(tmp_path, fault):
    request = {"invocation_id": "first", "pytest_args": ["test_one"]}
    receipt = receipt_for(request)
    path = tmp_path / "receipt.json"
    if fault == "stale":
        receipt["request_sha256"] = digest({"invocation_id": "prior"})
    elif fault == "reordered":
        receipt["collected"].reverse()
    elif fault in ("duplicate", "nonzero", "extra", "boolean-exit"):
        receipt.pop("sha256")
        if fault == "duplicate":
            receipt["eligible"] = ["one", "one"]
        elif fault == "nonzero":
            receipt["exit_code"] = 2
        elif fault == "boolean-exit":
            receipt["exit_code"] = False
        else:
            receipt["unrecognized"] = True
        receipt["sha256"] = digest(receipt)
    if fault != "missing":
        write_document(path, receipt)
    if fault == "truncated":
        path.write_bytes(b"")
    elif fault == "corrupt":
        path.write_bytes(b"{broken")
    elif fault == "oversized":
        path.write_bytes(b" " * (MAX_RECEIPT_BYTES + 1))
    elif fault == "symlink":
        real = path.with_suffix(".real")
        path.rename(real)
        path.symlink_to(real)
    with pytest.raises(PopulationDiscoveryError):
        validate_discovery_receipt(path, request=request)


def test_valid_receipt_binds_all_request_inputs(tmp_path):
    request = {"invocation_id": "first", "pytest_args": ["test_one"], "declarations": ["fixed"],
               "candidate": "current", "python_paths": ["path"], "environment": {"key": "value"}}
    path = tmp_path / "receipt.json"
    write_document(path, receipt_for(request))
    assert validate_discovery_receipt(path, request=request)["eligible"] == ["one", "two"]
    for field in request:
        changed = {**request, field: "changed"}
        with pytest.raises(PopulationDiscoveryError, match="stale or cross-run"):
            validate_discovery_receipt(path, request=changed)


@pytest.mark.parametrize("fault", ["none", "stale", "mismatch", "corrupt", "invalid-error"])
def test_failure_detail_never_admits_invalid_receipt_or_population(tmp_path, fault):
    request = {"invocation_id": "current"}
    receipt = receipt_for(request)
    receipt.pop("sha256")
    receipt.update(exit_code=2, error="RuntimeError")
    if fault == "stale":
        receipt["request_sha256"] = digest({"invocation_id": "prior"})
    if fault == "invalid-error":
        receipt["error"] = "/private/error/payload"
    receipt["sha256"] = digest(receipt)
    if fault == "corrupt":
        receipt["eligible"].reverse()
    path = tmp_path / "receipt.json"
    write_document(path, receipt)
    detail = discovery_failure_detail(path, request=request, exit_code=3 if fault == "mismatch" else 2)
    if fault == "none":
        assert "error=RuntimeError collected=2 eligible=2 deferred=0" in detail
    else:
        assert detail.startswith("receipt_unavailable:")
    assert "/private/error/payload" not in detail
    with pytest.raises(PopulationDiscoveryError):
        validate_discovery_receipt(path, request=request)


@pytest.mark.parametrize("failure", ["collection", "timeout", "interrupt", "missing"])
def test_discovery_failure_refuses_and_cleans_owned_child(tmp_path, monkeypatch, failure):
    root, source, _product, test, marker = fixture_tree(tmp_path)
    scratch = establish_run().tmp
    before = set(scratch.glob("discovery-*"))
    processes = []
    popen = subprocess.Popen

    def track(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(discovery.subprocess, "Popen", track)
    kwargs = {}
    if failure == "collection":
        test.write_text("raise RuntimeError('collection fault')\n")
    else:
        script = tmp_path / "wait.py"
        script.write_text("pass\n" if failure == "missing" else "import time\ntime.sleep(60)\n")
        kwargs = {"child_script_path": script, "timeout_seconds": 0.1}
        if failure == "interrupt":
            original_wait = popen.wait
            triggered = False

            def interrupt_once(self, *args, **kwargs):
                nonlocal triggered
                if not triggered:
                    triggered = True
                    raise KeyboardInterrupt()
                return original_wait(self, *args, **kwargs)

            monkeypatch.setattr(popen, "wait", interrupt_once)
    expected = KeyboardInterrupt if failure == "interrupt" else PopulationDiscoveryError
    with pytest.raises(expected) as raised:
        discover(root, source, test, **kwargs)
    if failure == "collection":
        assert "receipt_sha256=" in str(raised.value)
        assert "collected=0 eligible=0 deferred=0" in str(raised.value)
    assert len(processes) == 1  # No discovery retry.
    assert processes[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(processes[0].pid, 0)
    assert set(scratch.glob("discovery-*")) == before
    assert not marker.exists()


def test_child_environment_retains_test_authority_and_excludes_measurement():
    source = {"PATH": "/bin", "REPOMAP_GO_HELPER": "/test/helper", "GOCOVERDIR": "/test/go-hits",
              "COVERAGE_PROCESS_START": "/test/bootstrap", "PYTHONPATH": "/test/bootstrap",
              "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
              "REPOMAP_TEST_PG_CONTAINER_PORT": "55433", "_REPOMAP_TEST_SANDBOX_TOKEN": "test-token",
              "UNRELATED_SECRET": "never-passed"}
    filtered = discovery.filter_child_environment(source)
    assert filtered == {key: source[key] for key in ("PATH", "REPOMAP_GO_HELPER",
                       "REPOMAP_TEST_PG_CONTAINER_PORT", "_REPOMAP_TEST_SANDBOX_TOKEN")}
    assert source["COVERAGE_PROCESS_START"] == "/test/bootstrap"
