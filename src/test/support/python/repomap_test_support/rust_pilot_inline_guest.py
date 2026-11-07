"""Coverage-only inline guest adapter for the T1 fake boundary.

The canonical fake boundary still runs guest text in isolated subprocesses.
This adapter is an optional test seam: it imports the maintained guest modules
normally so the parent coverage session can observe their lines, then calls
the same main functions against only the fake bridge's owned temp tree.
It is not a containment, UID, kernel, Docker or native qualification path.
"""

from __future__ import annotations

import hashlib
import io
import sys as _host_sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult
from common_lore_index.extractors.rust_pilot.guest import (
    install_readback,
    parse_helper,
    runtime_probe,
    setup_writer,
)
from repomap_test_support.rust_pilot_fake_tree_sitter import (
    tree_sitter as _fake_binding,
    tree_sitter_rust as _fake_grammar,
)

_MISSING = object()
_GUESTS = {
    "setup_writer": setup_writer,
    "install_readback": install_readback,
    "runtime_probe": runtime_probe,
    "parse_helper": parse_helper,
}
_FAKE_MODULES = {
    "tree_sitter": _fake_binding,
    "tree_sitter_rust": _fake_grammar,
}
_INVOCATION_LOCK = threading.RLock()


class _BinaryInput:
    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)
        self.buffer = self

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def readline(self, size: int = -1) -> bytes:
        return self._stream.readline(size)


class _Capture:
    def __init__(self) -> None:
        self.buffer = self
        self._data = bytearray()

    def write(self, value: str | bytes) -> int:
        data = value.encode("utf-8") if isinstance(value, str) else value
        if not isinstance(data, bytes):
            raise TypeError("guest stream expects text or bytes")
        self._data.extend(data)
        return len(value)

    def flush(self) -> None:
        return None

    def value(self) -> bytes:
        return bytes(self._data)


class _SystemProxy:
    def __init__(self, stdin: _BinaryInput, stdout: _Capture, stderr: _Capture,
                 argv: Sequence[str]) -> None:
        self.stdin, self.stdout, self.stderr = stdin, stdout, stderr
        self.argv = list(argv)
        self.path = list(_host_sys.path)

    def __getattr__(self, name: str) -> object:
        return getattr(_host_sys, name)


class _ImportProxy:
    """Return only the two exact pure-Python stand-ins for guest imports."""

    def import_module(self, name: str, package: str | None = None) -> object:
        if package is None and name in _FAKE_MODULES:
            return _FAKE_MODULES[name]
        raise ImportError("inline guest import refused")


def _result(code: int, stdout: bytes, stderr: bytes) -> ExecResult:
    return ExecResult(code, stdout, False, len(stderr), hashlib.sha256(stderr).hexdigest(),
                      False, False, True, 0.0)


def _owned_temp_paths(root: Path, scratch: Path) -> None:
    paths = (Path(root), Path(scratch))
    if root == scratch or any(not path.is_absolute() or path.is_symlink() or not path.is_dir()
                              for path in paths):
        raise AssertionError("inline guest requires owned real directories")


class InlineGuestExecutor:
    """Invoke one fixed guest entry point against a fake bridge container."""

    def __call__(self, kind: str, *, root: Path, scratch: Path, stdin: bytes = b"",
                 argv: Sequence[str] = ()) -> ExecResult:
        if kind not in _GUESTS or type(stdin) is not bytes:
            raise AssertionError("unknown inline guest invocation")
        _owned_temp_paths(root, scratch)
        module = _GUESTS[kind]
        input_stream, stdout, stderr = _BinaryInput(stdin), _Capture(), _Capture()
        values: dict[str, Any] = {
            "sys": _SystemProxy(input_stream, stdout, stderr, [f"<inline:{kind}>", *argv]),
            "RUNTIME_ROOT": str(root),
            "SCRATCH": str(scratch),
        }
        if kind in {"runtime_probe", "parse_helper"}:
            values["importlib"] = _ImportProxy()
        with _INVOCATION_LOCK:
            previous = {name: module.__dict__.get(name, _MISSING) for name in values}
            try:
                module.__dict__.update(values)
                code = module.main()
            except SystemExit as exit_error:
                code = exit_error.code if type(exit_error.code) is int else 1
            except Exception as error:
                stderr.write(type(error).__name__)
                code = 1
            finally:
                for name, old in previous.items():
                    if old is _MISSING:
                        module.__dict__.pop(name, None)
                    else:
                        module.__dict__[name] = old
        return _result(code, stdout.value(), stderr.value())


__all__ = ("InlineGuestExecutor",)
