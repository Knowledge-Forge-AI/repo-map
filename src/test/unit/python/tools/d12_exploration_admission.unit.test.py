"""Pure owner for the ADR 0089 D9 E1 admission separation and the root pytest setup gate.

E1 keeps its own exploration slot; build admission stays empty, so the build accessor refuses throughout E1.
The real root conftest plugin's ``pytest_runtest_setup`` and the real runner routing run here; the named owner's
own E1 dataflow runs in ``d12_owner_exploration.unit.test.py``. No Docker, APT,
network or ledger: frozen identity is stubbed, ledger and build entry points are traps, and every filesystem
touch of the sentinel ledger is recorded.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import io
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import d12_dependency_preflight as preflight
from repomap_test_support import d12_core_image as d12
import runner_arguments
import test_sandbox

ROOT = Path(__file__).resolve().parents[5]
SOURCE = "a" * 64
IDENTITY: dict[str, Any] = {"source_sha256": SOURCE, "recipe_sha256": "b" * 64, "dockerfile_sha256": "c" * 64,
                            "context_file_count": 3}
FLAG, PROFILE = ["--d12-core-image-preflight"], ["--d12-core-image-profile", "linux/arm64"]
OTHER = "src/test/int/python/repomap_kg/runtime/other.int.test.py::test_other"
NO_ADMISSION = "no runner admission"
MIXED = "mixed build and exploration admission"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(d12, "_ADMISSION", None)
    monkeypatch.setattr(preflight, "_EXPLORATION", None)
    monkeypatch.setattr(d12, "frozen_identity", lambda root, platform: dict(IDENTITY))
    for name in (d12.ENV_PROFILE, d12.ENV_REPORT_DIR):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def trap(tmp_path, monkeypatch):
    """Ledger, host preflight and build entry points raise; the real ``admit_profile`` is only counted."""
    touched: list[str] = []
    admitted: list[str] = []

    def forbid(name: str):
        def refuse(*_args: Any, **_kwargs: Any):
            raise AssertionError(f"forbidden call: {name}")
        return refuse

    def guard(function):
        def checked(path, *args, **kwargs):
            if not isinstance(path, int) and "ledger-sentinel" in os.fsdecode(path):
                touched.append(os.fsdecode(path))
                raise AssertionError("ledger accessed")
            return function(path, *args, **kwargs)
        return checked

    def counted(*args: Any, **kwargs: Any):
        admitted.append("admit_profile")
        return real_admit(*args, **kwargs)

    real_admit = d12.admit_profile
    for module, name in ((os, "open"), (os, "stat"), (os, "lstat"), (io, "open"), (builtins, "open")):
        monkeypatch.setattr(module, name, guard(getattr(module, name)))
    monkeypatch.setattr(d12, "record_budget", forbid("record_budget"))
    monkeypatch.setattr(d12, "build_candidate", forbid("build_candidate"))
    monkeypatch.setattr(preflight, "preflight", forbid("host preflight"))
    monkeypatch.setattr(d12, "admit_profile", counted)
    return SimpleNamespace(ledger=tmp_path / "ledger-sentinel" / "BUILD-BUDGET.json", touched=touched,
                           admitted=admitted, real_admit=real_admit)


def _args(tmp_path: Path, *extra: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    runner_arguments.add_runner_arguments(parser, hygiene_profiles=(), parse_jobs=runner_arguments.parse_jobs,
                                          default_report_root=ROOT / ".test-reports")
    return parser.parse_args(["--suite", "int", "--no-coverage", "--report-dir", str(tmp_path / "report"),
                              "--d12-core-image-source-sha256", SOURCE, *extra])


def _route(monkeypatch, args, *, inside=True):
    monkeypatch.setattr(test_sandbox, "active_sandbox", lambda: inside)
    return runner_arguments.validate_pgvector_forwarded_selections(args, [d12.NODE_ID], repo_root=ROOT)


def _explore(monkeypatch, tmp_path):
    _route(monkeypatch, _args(tmp_path, *FLAG, *PROFILE))
    return preflight.current_exploration()


def _build(monkeypatch, tmp_path):
    _route(monkeypatch, _args(tmp_path, *PROFILE))
    return d12.current_admission()


def _setup(request, nodeid: str = d12.NODE_ID, marker: str | None = d12.MARKER) -> None:
    """The actual root conftest plugin registered in this session, never a copy of its source."""
    conftest = next(p for p in request.config.pluginmanager.get_plugins()
                    if str(getattr(p, "__file__", "")).endswith("src/test/conftest.py"))
    conftest.pytest_runtest_setup(SimpleNamespace(
        nodeid=nodeid, get_closest_marker=lambda name: object() if name == marker else None))


def test_sandbox_exploration_fills_only_its_own_slot_and_the_build_accessor_refuses(tmp_path, monkeypatch, trap):
    admitted = _explore(monkeypatch, tmp_path)
    assert admitted is not None and type(admitted) is d12.D12Admission, admitted
    assert (admitted.platform, admitted.node_id, admitted.source_sha256) == ("linux/arm64", d12.NODE_ID, SOURCE)
    assert d12._ADMISSION is None, "E1 must never fill the build admission slot"
    with pytest.raises(d12.D12ProfileError, match=NO_ADMISSION):
        d12.current_admission()
    assert trap.admitted == [] and trap.touched == []


def test_host_exploration_fills_no_slot(tmp_path, monkeypatch, trap):
    assert _route(monkeypatch, _args(tmp_path, *FLAG, *PROFILE), inside=False) is None
    assert preflight.current_exploration() is None and d12._ADMISSION is None
    assert trap.admitted == [] and trap.touched == []


def _state(state: str, monkeypatch, tmp_path, trap) -> None:
    if state == "build":
        _build(monkeypatch, tmp_path)
    elif state != "none":
        _explore(monkeypatch, tmp_path)
    if state == "both":  # the support's build admission called directly, bypassing the runner's guard
        trap.real_admit(_args(tmp_path, *PROFILE), [d12.NODE_ID], repo_root=ROOT, sandbox_active=lambda: True)
    elif state == "lost":  # the exploration singleton is lost while the build slot stays empty
        monkeypatch.setattr(preflight, "_EXPLORATION", None)
    elif state == "foreign":  # an exploration admitted for another node
        monkeypatch.setattr(preflight, "_EXPLORATION", d12.D12Admission(platform="linux/arm64", node_id=OTHER,
                                                                       **IDENTITY))


@pytest.mark.parametrize("state, nodeid, message", [
    ("none", d12.NODE_ID, NO_ADMISSION),
    ("build", d12.NODE_ID, None),
    ("exploration", d12.NODE_ID, None),
    ("exploration", OTHER, "E1 exploration admits only"),
    ("foreign", d12.NODE_ID, "E1 exploration admits only"),
    ("foreign", OTHER, "E1 exploration admits only"),
    ("both", d12.NODE_ID, MIXED),
    ("lost", d12.NODE_ID, NO_ADMISSION),
])
def test_root_setup_gate_admits_build_or_the_exact_node_exploration_only(tmp_path, monkeypatch, request, trap,
                                                                        state, nodeid, message):
    _state(state, monkeypatch, tmp_path, trap)
    if message is None:
        _setup(request, nodeid)
    else:
        with pytest.raises(d12.D12ProfileError, match=message):
            _setup(request, nodeid)
    assert trap.touched == [], "no case reads or writes a ledger"


def test_setup_gate_leaves_unmarked_items_alone(request, trap):
    _setup(request, OTHER, marker=None)  # no D12 gate at all, even with no admission
    assert trap.touched == [] and trap.admitted == []


def test_exploration_then_build_refuses_before_admit_profile_can_fill_its_slot(tmp_path, monkeypatch, trap):
    admitted = _explore(monkeypatch, tmp_path)
    with pytest.raises(d12.D12ProfileError, match=MIXED):
        _build(monkeypatch, tmp_path)
    assert trap.admitted == [], "the runner refused before calling admit_profile"
    assert d12._ADMISSION is None and preflight.current_exploration() is admitted and trap.touched == []
    with pytest.raises(d12.D12ProfileError, match=MIXED):  # a second exploration is refused too
        _explore(monkeypatch, tmp_path)
    assert preflight.current_exploration() is admitted


def test_build_then_exploration_refuses_and_keeps_the_build_admission(tmp_path, monkeypatch, trap):
    built = _build(monkeypatch, tmp_path)
    assert trap.admitted == ["admit_profile"] and preflight.current_exploration() is None
    with pytest.raises(d12.D12ProfileError, match=MIXED):
        _explore(monkeypatch, tmp_path)
    assert preflight.current_exploration() is None and d12.current_admission() is built and trap.touched == []


@pytest.mark.parametrize("state", ["exploration", "lost"])
def test_build_accessor_refuses_in_e1_and_the_owner_build_argument_is_its_guard(tmp_path, monkeypatch, trap, state):
    """Accessor refusal plus the guard's call site only. The owner's actual E1 and build dataflow, and the guard's
    behavior, run with faked interfaces in ``d12_owner_exploration.unit.test.py``."""
    _state(state, monkeypatch, tmp_path, trap)
    with pytest.raises(d12.D12ProfileError, match=NO_ADMISSION):
        d12.current_admission()
    owner = ast.parse((ROOT / d12.NODE_FILE).read_bytes())
    test = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == d12.NODE_ID.rsplit("::")[1])
    builds = [n for n in ast.walk(test) if isinstance(n, ast.Call) and ast.unparse(n.func) == "d12.build_candidate"]
    assert len(builds) == 1, "exactly one build call"
    argument = [ast.unparse(k.value) for k in builds[0].keywords if k.arg == "admission"]
    assert argument == ["_build_authority(admission)"], argument
    assert trap.admitted == [] and trap.touched == []
