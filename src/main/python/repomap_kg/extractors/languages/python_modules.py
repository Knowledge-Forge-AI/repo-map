"""Python module identity and package-root helpers."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class PythonModuleIndex:
    module_to_path: Mapping[str, str]
    path_to_module: Mapping[str, str]

    @classmethod
    def empty(cls) -> PythonModuleIndex:
        return cls(module_to_path={}, path_to_module={})

    @classmethod
    def from_modules(cls, modules: Mapping[str, str]) -> PythonModuleIndex:
        module_to_path = dict(modules)
        path_to_module = {path: module for module, path in module_to_path.items()}
        return cls(module_to_path=module_to_path, path_to_module=path_to_module)

    @classmethod
    def from_python_paths(
        cls,
        paths: Iterable[str],
        *,
        repository_root: Path | str | None = None,
    ) -> PythonModuleIndex:
        modules = {}
        for path in sorted(paths):
            module = importable_module_name(path, repository_root=repository_root)
            if module is not None:
                modules[module] = path
        return cls.from_modules(modules)

    def has_module(self, module: str) -> bool:
        return module in self.module_to_path


def importable_module_name(
    relative_path: str,
    *,
    repository_root: Path | str | None = None,
) -> str | None:
    if not relative_path.endswith(".py"):
        return None
    normalized_path = relative_path.replace("\\", "/")
    roots = package_roots(repository_root)
    for root in roots:
        prefix = f"{root}/" if root != "." else ""
        if root == "." or normalized_path.startswith(prefix):
            suffix = normalized_path.removeprefix(prefix)
            return module_name_from_suffix(suffix)
    return module_name_from_suffix(normalized_path)


def package_roots(repository_root: Path | str | None = None) -> tuple[str, ...]:
    roots = ["src/main/python"]
    roots.extend(pyproject_package_roots(repository_root))
    roots.extend(test_python_roots)
    return tuple(dict.fromkeys(roots))


def pyproject_package_roots(repository_root: Path | str | None) -> tuple[str, ...]:
    if repository_root is None:
        return ()
    pyproject_path = Path(repository_root) / "pyproject.toml"
    if not pyproject_path.exists():
        return ()
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return ()
    package_dir = (
        payload.get("tool", {})
        .get("setuptools", {})
        .get("package-dir", {})
    )
    if not isinstance(package_dir, Mapping):
        return ()
    roots = []
    for key in ("", "."):
        value = package_dir.get(key)
        if isinstance(value, str) and value.strip():
            roots.append(normalize_root(value))
    return tuple(roots)


test_python_roots = (
    "src/test/unit/python",
    "src/test/int/python",
)


def normalize_root(value: str) -> str:
    return value.strip().replace("\\", "/").strip("/")


def module_name_from_suffix(suffix: str) -> str | None:
    if not suffix.endswith(".py"):
        return None
    without_extension = suffix[:-3]
    if without_extension.endswith("/__init__"):
        without_extension = without_extension[: -len("/__init__")]
    elif without_extension == "__init__":
        return None
    parts = [part for part in without_extension.split("/") if part]
    if not parts:
        return None
    return ".".join(parts)
