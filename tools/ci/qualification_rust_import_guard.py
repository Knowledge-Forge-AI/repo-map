"""Fail closed on database or native-parser host imports during qualification."""

from __future__ import annotations

from contextlib import contextmanager
import importlib.abc
import importlib.machinery
import hashlib
from pathlib import Path
import sys
from collections.abc import Iterator, Mapping, Sequence
from types import ModuleType
from typing import Any

FORBIDDEN_TOPS = frozenset({"psycopg", "psycopg2", "psycopg_c", "psycopg_binary", "sqlalchemy", "sqlite3",
                             "tree_sitter", "tree_sitter_rust"})
FORBIDDEN_PREFIXES = ("common_lore_index.storage", "repomap_kg.storage",
                      "common_lore_index.coordinator.worker", "common_lore_index.ops.rust_pilot_publication")


class HostImportRefused(RuntimeError):
    def __init__(self) -> None:
        super().__init__("host_import_refused")
        self.code = "host_import_refused"


def forbidden(fullname: str) -> bool:
    return fullname.split(".", 1)[0] in FORBIDDEN_TOPS or any(
        fullname == prefix or fullname.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES)


class _Guard(importlib.abc.MetaPathFinder):
    def __init__(self, root: Path | None, digests: Mapping[str, str] | None) -> None:
        self.root, self.digests = root, digests

    def check_source(self, origin: str | None) -> None:
        if self.root is None or self.digests is None or origin is None:
            return
        source = Path(origin)
        if not source.is_absolute() or not source.is_relative_to(self.root):
            return
        relative = source.relative_to(self.root).as_posix()
        if not any(relative.startswith(prefix + "/") for prefix in (
                "tools", "src/main/python", "src/test/support/python")):
            raise HostImportRefused()
        try:
            if (source.resolve() != source or source.suffix != ".py"
                    or hashlib.sha256(source.read_bytes()).hexdigest() != self.digests.get(relative)):
                raise HostImportRefused()
        except OSError:
            raise HostImportRefused() from None

    def find_spec(self, fullname: str, path: Sequence[str] | None = None,
                  target: ModuleType | None = None) -> Any:
        if forbidden(fullname):
            raise HostImportRefused()
        if self.root is not None:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is not None:
                self.check_source(spec.origin)
        return None


@contextmanager
def host_import_guard(repo_root: Path | None = None,
                      digests: Mapping[str, str] | None = None) -> Iterator[None]:
    if (repo_root is None) != (digests is None):
        raise HostImportRefused()
    if any(forbidden(name) for name in tuple(sys.modules)):
        raise HostImportRefused()
    guard = _Guard(None if repo_root is None else repo_root.resolve(), digests)
    for module in tuple(sys.modules.values()):
        guard.check_source(getattr(module, "__file__", None))
    sys.meta_path.insert(0, guard)
    try:
        yield
    finally:
        sys.meta_path.remove(guard)
