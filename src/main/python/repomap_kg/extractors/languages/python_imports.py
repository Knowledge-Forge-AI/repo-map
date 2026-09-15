"""Python import observation and target-resolution helpers."""

from __future__ import annotations

import ast
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.languages.python_common import (
    EXTRACTOR_NAME,
    end_line,
    slug,
)
from repomap_kg.extractors.languages.python_modules import PythonModuleIndex
from repomap_kg.graph.keys import external_key, python_module_key, unknown_key
from repomap_kg.observations.raw import RawObservation


def python_import_observations(
    relative_path: str,
    source_module: str,
    node: ast.Import | ast.ImportFrom,
    *,
    module_index: PythonModuleIndex,
) -> tuple[RawObservation, ...]:
    observations = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            imported_module = alias.name
            target_key, resolution = import_target_for_absolute(
                imported_module,
                module_index=module_index,
            )
            observations.append(
                python_import_observation(
                    relative_path,
                    source_module,
                    node,
                    imported_module=imported_module,
                    imported_names=[alias.name],
                    alias=alias.asname,
                    level=0,
                    resolution=resolution,
                    target_key=target_key,
                )
            )
        return tuple(observations)

    base_module = node.module or ""
    for alias in node.names:
        imported_module, target_key, resolution = import_target_for_from(
            source_module,
            base_module,
            alias.name,
            node.level,
            module_index=module_index,
        )
        observations.append(
            python_import_observation(
                relative_path,
                source_module,
                node,
                imported_module=imported_module,
                imported_names=[alias.name],
                alias=alias.asname,
                level=node.level,
                resolution=resolution,
                target_key=target_key,
            )
        )
    return tuple(observations)


def python_import_observation(
    relative_path: str,
    source_module: str,
    node: ast.Import | ast.ImportFrom,
    *,
    imported_module: str,
    imported_names: list[str],
    alias: str | None,
    level: int,
    resolution: str,
    target_key: str,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "module": source_module,
        "imported_names": imported_names,
        "level": level,
        "resolution": resolution,
    }
    if imported_module:
        metadata["imported_module"] = imported_module
    if alias is not None:
        metadata["alias"] = alias
    return RawObservation(
        kind="python.import",
        source_id=(
            f"{relative_path}#import:{node.lineno}:"
            f"{slug(imported_module or '.'.join(imported_names))}"
        ),
        path=relative_path,
        start_line=node.lineno,
        end_line=end_line(node),
        name=imported_module or ".".join(imported_names),
        target=target_key,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def import_target_for_absolute(
    imported_module: str,
    *,
    module_index: PythonModuleIndex,
) -> tuple[str, str]:
    if module_index.has_module(imported_module):
        return python_module_key(imported_module), "local"
    return external_key("python.module", imported_module), "external"


def import_target_for_from(
    source_module: str,
    base_module: str,
    imported_name: str,
    level: int,
    *,
    module_index: PythonModuleIndex,
) -> tuple[str, str, str]:
    if level:
        resolved_base = resolve_relative_base(source_module, base_module, level)
        if resolved_base is None:
            return (
                "",
                unknown_key("python.module", "missing-package-context"),
                "unknown",
            )
        candidates = relative_module_candidates(
            resolved_base,
            base_module,
            imported_name,
        )
        for candidate in candidates:
            if module_index.has_module(candidate):
                return candidate, python_module_key(candidate), "local"
        return (
            candidates[0],
            unknown_key("python.module", "missing-module"),
            "unknown",
        )

    candidates = module_candidates(base_module, imported_name)
    for candidate in candidates:
        if module_index.has_module(candidate):
            return candidate, python_module_key(candidate), "local"
    if base_module and module_index.has_module(base_module):
        return base_module, python_module_key(base_module), "local"
    return base_module, external_key("python.module", base_module), "external"


def resolve_relative_base(
    source_module: str, base_module: str, level: int
) -> str | None:
    source_parts = source_module.split(".")
    if len(source_parts) < 2:
        return None
    package_parts = source_parts[:-1]
    if level > len(package_parts):
        return None
    prefix = package_parts[: len(package_parts) - level + 1]
    if base_module:
        prefix.extend(base_module.split("."))
    if not prefix:
        return None
    return ".".join(prefix)


def module_candidates(base_module: str, imported_name: str) -> tuple[str, ...]:
    if imported_name == "*":
        return (base_module,)
    if not base_module:
        return (imported_name,)
    return (f"{base_module}.{imported_name}", base_module)


def relative_module_candidates(
    resolved_base: str, base_module: str, imported_name: str
) -> tuple[str, ...]:
    if imported_name == "*":
        return (resolved_base,)
    if not base_module:
        return (f"{resolved_base}.{imported_name}",)
    return module_candidates(resolved_base, imported_name)
