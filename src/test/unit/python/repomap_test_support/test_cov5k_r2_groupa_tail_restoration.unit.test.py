from __future__ import annotations

from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest

from repomap_test_support.test_cov5k_r2_fix2_preparation import (
    _forced_tail_for_observations,
)
from scale28_preparation_worker import (
    _start_without_ambient_parent_main,
)


class _TrackedTail:
    def __init__(self, line: str = "ready\n") -> None:
        self._line = line
        self.closed = False

    def readline(self) -> str:
        return self._line

    def close(self) -> None:
        self.closed = True


class _TailProcess:
    def __init__(self, line: str = "ready\n") -> None:
        self.stdout = _TrackedTail(line)
        self.pid = 1234
        self.returncode: int | None = None

    def send_signal(self, _signal) -> None:
        self.returncode = -15

    def wait(self, timeout: float) -> None:
        del timeout

    def poll(self):
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


def test_forced_tail_stdout_closes_on_normal_path(monkeypatch) -> None:
    process = _TailProcess()
    monkeypatch.setattr(
        "repomap_test_support.test_cov5k_r2_fix2_preparation.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    _forced_tail_for_observations(("preparation_timeout",))
    assert process.stdout.closed is True


def test_forced_tail_stdout_closes_on_exception_path(monkeypatch) -> None:
    process = _TailProcess("bad\n")
    monkeypatch.setattr(
        "repomap_test_support.test_cov5k_r2_fix2_preparation.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    with pytest.raises(RuntimeError, match="did not become ready"):
        _forced_tail_for_observations(("preparation_timeout",))
    assert process.stdout.closed is True


def test_descriptor_authority_is_actual_forced_tail_stdout_lifecycle() -> None:
    source = Path(
        "src/test/support/python/repomap_test_support/"
        "test_cov5k_r2_fix2_preparation.py"
    ).read_text()
    assert "def _probe_descriptor_settlement" not in source
    assert "forced_tail_stdout_closed" in source


class _StartProcess:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.observed: tuple[bool, object] | None = None

    def start(self) -> None:
        import __main__ as ambient_main

        self.observed = (hasattr(ambient_main, "__file__"), getattr(ambient_main, "__spec__", object()))
        if self.error is not None:
            raise self.error


@pytest.mark.parametrize("raises", (False, True))
def test_ambient_main_attributes_restore_exactly(raises: bool) -> None:
    import __main__ as ambient_main

    original_file = getattr(ambient_main, "__file__", None)
    original_spec = getattr(ambient_main, "__spec__", None)
    sentinel_file = "public-safe-main.py"
    sentinel_spec = ModuleSpec(name="__main__", loader=None)
    ambient_main.__file__ = sentinel_file
    ambient_main.__spec__ = sentinel_spec
    process = _StartProcess(RuntimeError("start failed") if raises else None)
    try:
        if raises:
            with pytest.raises(RuntimeError, match="start failed"):
                _start_without_ambient_parent_main(process)
        else:
            _start_without_ambient_parent_main(process)
        assert process.observed == (False, None)
        assert ambient_main.__file__ is sentinel_file
        assert ambient_main.__spec__ is sentinel_spec
    finally:
        setattr(ambient_main, "__file__", original_file)
        ambient_main.__spec__ = original_spec
