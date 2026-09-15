from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import psutil
import pytest

import scale12_resource_sampling as resource_sampling
from repomap_test_support.process_boundary import RecordingProcessBoundary
from scale12_resource_sampling import (
    ResourceSamplingError,
    read_process_rss_bytes,
    read_process_tree_rss_bytes,
)


class _Process:
    def __init__(
        self,
        rss: object,
        *,
        children: tuple[_Process, ...] = (),
        running: bool = True,
        memory_error: BaseException | None = None,
        children_error: BaseException | None = None,
    ) -> None:
        self._rss = rss
        self._children = children
        self._running = running
        self._memory_error = memory_error
        self._children_error = children_error

    def children(self, *, recursive: bool) -> list[_Process]:
        assert recursive is True
        if self._children_error is not None:
            raise self._children_error
        return list(self._children)

    def is_running(self) -> bool:
        return self._running

    def memory_info(self) -> SimpleNamespace:
        if self._memory_error is not None:
            raise self._memory_error
        return SimpleNamespace(rss=self._rss)


def _install_process(monkeypatch: pytest.MonkeyPatch, process: _Process) -> None:
    monkeypatch.setattr(resource_sampling.psutil, "Process", lambda _pid: process)


def test_process_rss_returns_current_bytes_without_a_host_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_process(monkeypatch, _Process(123_456))
    boundary = RecordingProcessBoundary().install(monkeypatch)

    assert read_process_rss_bytes(17) == 123_456
    assert boundary.host_process_count == 0


@pytest.mark.parametrize("value", [True, 1.0, "1", 0, -1])
def test_process_rss_rejects_invalid_process_identifiers(value: object) -> None:
    with pytest.raises(ResourceSamplingError, match="process identifier"):
        read_process_rss_bytes(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "error",
    [
        psutil.NoSuchProcess(17),
        psutil.AccessDenied(17),
        psutil.ZombieProcess(17),
    ],
)
def test_process_rss_maps_owned_psutil_failures_to_none(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    _install_process(monkeypatch, _Process(1, memory_error=error))

    assert read_process_rss_bytes(17) is None


@pytest.mark.parametrize("rss", [-1, True, 1.5, "123"])
def test_process_rss_refuses_invalid_values(
    monkeypatch: pytest.MonkeyPatch, rss: object
) -> None:
    _install_process(monkeypatch, _Process(rss))

    assert read_process_rss_bytes(17) is None


def test_process_tree_sums_root_and_available_children_without_ps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vanished = _Process(20, memory_error=psutil.NoSuchProcess(19))
    denied = _Process(30, memory_error=psutil.AccessDenied(20))
    zombie = _Process(40, memory_error=psutil.ZombieProcess(21))
    reused = _Process(50, running=False)
    root = _Process(
        100,
        children=(_Process(10), vanished, denied, zombie, reused),
    )
    _install_process(monkeypatch, root)
    boundary = RecordingProcessBoundary().install(monkeypatch)

    assert read_process_tree_rss_bytes(17) == 110
    assert boundary.host_process_count == 0


@pytest.mark.parametrize(
    "error",
    [
        psutil.NoSuchProcess(17),
        psutil.AccessDenied(17),
        psutil.ZombieProcess(17),
    ],
)
def test_process_tree_root_disappearance_or_denial_returns_none(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    _install_process(monkeypatch, _Process(100, children_error=error))

    assert read_process_tree_rss_bytes(17) is None


def test_process_tree_refuses_reused_root_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_process(monkeypatch, _Process(100, running=False))

    assert read_process_tree_rss_bytes(17) is None


@pytest.mark.parametrize("missing_name", ["psutil", "docker"])
def test_sampling_module_fails_fast_when_scale_dependency_is_missing(
    monkeypatch: pytest.MonkeyPatch, missing_name: str
) -> None:
    from unittest.mock import patch

    module_path = Path(resource_sampling.__file__)
    module_name = f"_scale28_missing_{missing_name}"
    real_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == missing_name:
            raise ModuleNotFoundError(f"No module named {missing_name!r}", name=missing_name)
        return real_import(name, globals, locals, fromlist, level)

    with monkeypatch.context() as import_patch, patch.dict(sys.modules):
        import_patch.setattr(builtins, "__import__", blocked_import)
        specification = importlib.util.spec_from_file_location(module_name, module_path)
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        sys.modules[module_name] = module
        with pytest.raises(RuntimeError, match="scale-tools"):
            specification.loader.exec_module(module)
