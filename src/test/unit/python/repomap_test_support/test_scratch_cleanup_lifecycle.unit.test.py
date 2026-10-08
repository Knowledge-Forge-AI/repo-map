"""Exercise the maintained pytest hook's real report and retention boundary."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from repomap_test_support.test_scratch import TestScratchLayout
from repomap_test_support.test_scratch_cleanup import (
    ScratchOwnershipError,
    is_test_settled_and_passed,
    validate_scratch_path_ownership,
)

ROOT = Path(__file__).resolve().parents[5]


@pytest.mark.parametrize("mode", ["passed", "call_failed", "teardown_failed", "cleanup_failed"])
def test_real_pytest_cleanup_waits_for_teardown_report(tmp_path: Path, mode: str) -> None:
    owner = tmp_path / "owner"
    owner.mkdir()
    shutil.copyfile(ROOT / "src/test/conftest.py", owner / "conftest.py")
    fixture = """
import pytest
from pathlib import Path

@pytest.fixture(autouse=True)
def late_teardown():
    yield
    if MODE == 'teardown_failed':
        raise RuntimeError('late fixture error')

def test_evidence(tmp_path):
    Path(POINTER).write_text(str(tmp_path))
    (tmp_path / 'evidence.txt').write_text('retain on failure')
    if MODE == 'call_failed':
        raise RuntimeError('call error')
    if MODE == 'cleanup_failed':
        import repomap_test_support.test_scratch_cleanup as cleanup
        def refuse(path):
            raise OSError('owned cleanup refusal')
        cleanup.shutil.rmtree = refuse
"""
    pointer = tmp_path / "pointer.txt"
    (owner / "test_owner.py").write_text(
        f"MODE = {mode!r}\nPOINTER = {str(pointer)!r}\n" + fixture
    )
    env = dict(os.environ)
    env.pop("REPOMAP_TEST_RUN_ROOT", None)
    env["REPOMAP_TEST_SCRATCH_ROOT"] = str(tmp_path / "scratch")
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src/test/support/python"), str(ROOT / "src/main/python")))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_owner.py"],
        cwd=owner, env=env, capture_output=True, text=True, timeout=30,
    )
    evidence = Path(pointer.read_text()) / "evidence.txt"
    assert result.returncode == (0 if mode == "passed" else 1), result.stdout + result.stderr
    assert evidence.exists() is (mode != "passed")
    if mode == "cleanup_failed":
        assert "Test scratch cleanup failed for test_owner.py::test_evidence" in result.stdout
        assert "owned cleanup refusal" in result.stdout


def test_cleanup_requires_final_teardown_report() -> None:
    from types import SimpleNamespace
    passed = SimpleNamespace(outcome="passed")
    node = SimpleNamespace(rep_setup=passed, rep_call=passed)
    assert not is_test_settled_and_passed(node)


def test_cleanup_refuses_run_logs_and_keeps_content(tmp_path: Path) -> None:
    layout = TestScratchLayout(tmp_path / "run", tmp_path, True, "repo-map_dev", "cleanup").create()
    evidence = layout.logs / "retained"
    evidence.mkdir()
    (evidence / "report.json").write_text('{}')
    with pytest.raises(ScratchOwnershipError, match="outside test temporary directories"):
        validate_scratch_path_ownership(evidence, layout)
    assert (evidence / "report.json").exists()
