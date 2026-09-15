#!/usr/bin/env python3
"""Load and resolve RepoMap's architecture-aligned Python type ownership."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src/main/python"
DEFAULT_MANIFEST = Path(__file__).with_name("python_type_ownership.json")
SCHEMA = "repomap-python-type-ownership-v1"
RESOLUTION = "longest-component-prefix-wins"
CLASS_TIERS = {
    "cross_language_contract": frozenset({"T0"}),
    "python_retained": frozenset({"T1-seed", "T1-future"}),
    "transitional_python": frozenset({"T2"}),
    "planned_go": frozenset({"T3"}),
    "planned_go_or_rust": frozenset({"T3"}),
}


class OwnershipManifestError(ValueError):
    """The typing ownership manifest is incomplete or invalid."""


@dataclass(frozen=True)
class OwnershipRule:
    module_prefix: str
    match: str
    ownership_class: str
    architecture_box: str
    enforcement_tier: str
    justification: str
    disposition: str


@dataclass(frozen=True)
class OwnershipManifest:
    entries: tuple[OwnershipRule, ...]


def module_name_for_path(path: Path, source_root: Path = SOURCE_ROOT) -> str:
    relative = path.resolve().relative_to(source_root.resolve())
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def maintained_modules(repo_root: Path = ROOT) -> dict[str, Path]:
    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "src/main/python/repomap_kg",
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    source_root = repo_root / "src/main/python"
    module_paths = {}
    for raw_path in completed.stdout.splitlines():
        if not raw_path.endswith(".py"):
            continue
        path = repo_root / raw_path
        module = module_name_for_path(path, source_root)
        if module in module_paths:
            raise OwnershipManifestError(f"duplicate maintained module: {module}")
        module_paths[module] = path
    return dict(sorted(module_paths.items()))


def load_manifest(
    path: Path = DEFAULT_MANIFEST,
    *,
    modules: Mapping[str, Path] | None = None,
) -> OwnershipManifest:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OwnershipManifestError("ownership manifest is unreadable") from error
    if not isinstance(document, dict) or set(document) != {
        "schema",
        "resolution",
        "entries",
    }:
        raise OwnershipManifestError("ownership manifest fields are invalid")
    if document["schema"] != SCHEMA or document["resolution"] != RESOLUTION:
        raise OwnershipManifestError("ownership manifest schema is invalid")
    raw_entries = document["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise OwnershipManifestError("ownership manifest entries are invalid")
    entries = tuple(_rule(raw) for raw in raw_entries)
    prefixes = tuple(rule.module_prefix for rule in entries)
    if len(prefixes) != len(set(prefixes)):
        raise OwnershipManifestError("duplicate module prefix")
    if prefixes != tuple(sorted(prefixes)):
        raise OwnershipManifestError("ownership entries are not deterministically ordered")
    manifest = OwnershipManifest(entries)
    if modules is not None:
        classify_modules(modules, manifest)
    return manifest


def _rule(raw: object) -> OwnershipRule:
    fields = tuple(OwnershipRule.__dataclass_fields__)
    if not isinstance(raw, dict) or set(raw) != set(fields):
        raise OwnershipManifestError("ownership entry fields are invalid")
    if any(not isinstance(raw[field], str) or not raw[field] for field in fields):
        raise OwnershipManifestError("ownership entry values are invalid")
    ownership_class = raw["ownership_class"]
    if ownership_class not in CLASS_TIERS:
        raise OwnershipManifestError("ownership class is invalid")
    if raw["enforcement_tier"] not in CLASS_TIERS[ownership_class]:
        raise OwnershipManifestError("ownership class and tier are inconsistent")
    if raw["match"] not in {"exact", "subtree"}:
        raise OwnershipManifestError("ownership match is invalid")
    prefix = raw["module_prefix"]
    if not prefix.startswith("repomap_kg") or any(not part for part in prefix.split(".")):
        raise OwnershipManifestError("module prefix is invalid")
    return OwnershipRule(**{field: raw[field] for field in fields})


def resolve_rule(module: str, manifest: OwnershipManifest) -> OwnershipRule | None:
    candidates = []
    for rule in manifest.entries:
        if rule.match == "exact":
            matched = module == rule.module_prefix
        else:
            matched = module == rule.module_prefix or module.startswith(
                rule.module_prefix + "."
            )
        if matched:
            candidates.append(rule)
    if not candidates:
        return None
    return max(candidates, key=lambda rule: len(rule.module_prefix.split(".")))


def classify_modules(
    modules: Mapping[str, Path], manifest: OwnershipManifest
) -> dict[str, OwnershipRule]:
    """Classify module paths under ownership rules.

    The public `modules` parameter accepts a mapping of module name to filesystem path.
    The dependency scanner flags subscripts named `modules` as dynamic imports.
    The `module_paths` alias identifies this ordinary path mapping without changing
    the public keyword parameter or relaxing that conservative scanner rule.
    """
    module_paths: Mapping[str, Path] = modules
    classified = {}
    unclassified = []
    for module in sorted(module_paths):
        rule = resolve_rule(module, manifest)
        if rule is None:
            unclassified.append(module)
        else:
            classified[module] = rule
    if unclassified:
        joined = ", ".join(unclassified[:5])
        raise OwnershipManifestError(f"unclassified maintained modules: {joined}")
    return classified


def tier_targets(
    modules: Mapping[str, Path],
    manifest: OwnershipManifest,
    tiers: frozenset[str],
) -> tuple[Path, ...]:
    """Return paths for modules matching target tiers.

    The public `modules` parameter accepts a mapping of module name to filesystem path.
    The dependency scanner flags subscripts named `modules` as dynamic imports.
    The `module_paths` alias identifies this ordinary path mapping without changing
    the public keyword parameter or relaxing that conservative scanner rule.
    """
    module_paths: Mapping[str, Path] = modules
    classified = classify_modules(module_paths, manifest)
    return tuple(
        module_paths[module]
        for module in sorted(module_paths)
        if classified[module].enforcement_tier in tiers
    )
