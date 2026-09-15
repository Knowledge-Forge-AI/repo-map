#!/usr/bin/env python3
"""Report drift in the canonicalization package-root compatibility ledger."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "main" / "python"
CANONICALIZATION_ROOT = SRC_ROOT / "repomap_kg" / "canonicalization"
PACKAGE_INIT = CANONICALIZATION_ROOT / "__init__.py"
FAMILY_SCAFFOLD_MARKERS = (
    'sys.modules["repomap_kg.canonicalization.main"]',
    "globals().update",
)


if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


@dataclass(frozen=True)
class FacadeInventory:
    ledger_names: tuple[str, ...]
    generated_main_surface: tuple[str, ...]
    missing_from_package_root: tuple[str, ...]
    missing_from_main: tuple[str, ...]
    extra_main_names: tuple[str, ...]
    missing_all_names: tuple[str, ...]
    extra_all_names: tuple[str, ...]
    family_scaffold_files: tuple[str, ...]
    package_root_uses_static_ledger: bool
    public_names: tuple[str, ...]
    all_names: tuple[str, ...]

    @property
    def static_ledger_count(self) -> int:
        return len(self.ledger_names)

    @property
    def generated_main_count(self) -> int:
        return len(self.generated_main_surface)

    @property
    def public_all_count(self) -> int:
        return len(self.all_names)

    @property
    def public_package_root_count(self) -> int:
        return len(self.public_names)

    @property
    def ledger_matches_generated_main(self) -> bool:
        return self.ledger_names == self.generated_main_surface

    @property
    def all_matches_public_surface(self) -> bool:
        return set(self.all_names) == set(self.public_names)

    @property
    def check_passed(self) -> bool:
        return (
            self.package_root_uses_static_ledger
            and self.ledger_matches_generated_main
            and self.all_matches_public_surface
            and not self.missing_from_package_root
            and not self.missing_from_main
            and not self.extra_main_names
            and not self.missing_all_names
            and not self.extra_all_names
            and not self.family_scaffold_files
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "static_ledger_count": self.static_ledger_count,
            "generated_main_count": self.generated_main_count,
            "public_all_count": self.public_all_count,
            "public_package_root_count": self.public_package_root_count,
            "ledger_matches_generated_main": self.ledger_matches_generated_main,
            "all_matches_public_surface": self.all_matches_public_surface,
            "package_root_uses_static_ledger": self.package_root_uses_static_ledger,
            "check_passed": self.check_passed,
            "missing_from_package_root": list(self.missing_from_package_root),
            "missing_from_main": list(self.missing_from_main),
            "extra_main_names": list(self.extra_main_names),
            "missing_all_names": list(self.missing_all_names),
            "extra_all_names": list(self.extra_all_names),
            "family_scaffold_files": list(self.family_scaffold_files),
        }


def _sorted_difference(left: Sequence[str], right: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(set(left) - set(right)))


def _relative_path(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _scan_family_scaffold_files(root: Path = CANONICALIZATION_ROOT) -> tuple[str, ...]:
    scaffold_files: list[str] = []
    for family_path in sorted(root.glob("*_family.py")):
        source = family_path.read_text()
        if any(marker in source for marker in FAMILY_SCAFFOLD_MARKERS):
            scaffold_files.append(_relative_path(family_path))
    return tuple(scaffold_files)


def _package_root_uses_static_ledger(path: Path = PACKAGE_INIT) -> bool:
    source = path.read_text()
    return "_COMPATIBILITY_EXPORT_NAMES = (" in source and "dir(_impl)" not in source


def build_inventory(
    *,
    ledger_names: Sequence[str],
    generated_main_surface: Sequence[str],
    package_root_names: Sequence[str],
    public_names: Sequence[str],
    all_names: Sequence[str],
    family_scaffold_files: Sequence[str],
    package_root_uses_static_ledger: bool,
) -> FacadeInventory:
    ledger_tuple = tuple(ledger_names)
    generated_tuple = tuple(generated_main_surface)
    package_root_tuple = tuple(package_root_names)
    public_tuple = tuple(public_names)
    all_tuple = tuple(all_names)
    return FacadeInventory(
        ledger_names=ledger_tuple,
        generated_main_surface=generated_tuple,
        missing_from_package_root=_sorted_difference(
            ledger_tuple,
            package_root_tuple,
        ),
        missing_from_main=_sorted_difference(ledger_tuple, generated_tuple),
        extra_main_names=_sorted_difference(generated_tuple, ledger_tuple),
        missing_all_names=_sorted_difference(public_tuple, all_tuple),
        extra_all_names=_sorted_difference(all_tuple, public_tuple),
        family_scaffold_files=tuple(family_scaffold_files),
        package_root_uses_static_ledger=package_root_uses_static_ledger,
        public_names=public_tuple,
        all_names=all_tuple,
    )


def collect_inventory() -> FacadeInventory:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main

    ledger_names = tuple(canonicalization._COMPATIBILITY_EXPORT_NAMES)
    generated_main_surface = tuple(
        name
        for name in dir(main)
        if name not in canonicalization._MODULE_DUNDER_NAMES
    )
    package_root_names = tuple(dir(canonicalization))
    public_names = tuple(
        name for name in package_root_names if not name.startswith("_")
    )
    all_names = tuple(canonicalization.__all__)
    return build_inventory(
        ledger_names=ledger_names,
        generated_main_surface=generated_main_surface,
        package_root_names=package_root_names,
        public_names=public_names,
        all_names=all_names,
        family_scaffold_files=_scan_family_scaffold_files(),
        package_root_uses_static_ledger=_package_root_uses_static_ledger(),
    )


def format_inventory(inventory: FacadeInventory) -> list[str]:
    lines = [
        "canonicalization facade inventory",
        f"static ledger count: {inventory.static_ledger_count}",
        f"generated main surface count: {inventory.generated_main_count}",
        f"package-root missing ledger names: {len(inventory.missing_from_package_root)}",
        f"ledger names missing from main: {len(inventory.missing_from_main)}",
        f"generated main names missing from ledger: {len(inventory.extra_main_names)}",
        f"public __all__ count: {inventory.public_all_count}",
        f"public package-root names count: {inventory.public_package_root_count}",
        f"missing __all__ public names: {len(inventory.missing_all_names)}",
        f"extra __all__ names: {len(inventory.extra_all_names)}",
        f"family modules with old scaffold: {len(inventory.family_scaffold_files)}",
        "static tuple source check: "
        f"{'pass' if inventory.package_root_uses_static_ledger else 'fail'}",
        f"status: {'pass' if inventory.check_passed else 'fail'}",
    ]
    issue_groups = (
        ("missing from package root", inventory.missing_from_package_root),
        ("missing from main", inventory.missing_from_main),
        ("extra generated main names", inventory.extra_main_names),
        ("missing __all__ names", inventory.missing_all_names),
        ("extra __all__ names", inventory.extra_all_names),
        ("family scaffold files", inventory.family_scaffold_files),
    )
    for label, names in issue_groups:
        if names:
            lines.append(f"{label}:")
            lines.extend(f"  - {name}" for name in names)
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report the canonicalization package-root facade inventory.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the static ledger has drifted",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a JSON inventory report",
    )
    args = parser.parse_args(argv)

    inventory = collect_inventory()
    if args.json:
        print(json.dumps(inventory.to_dict(), indent=2, sort_keys=True))
    else:
        print("\n".join(format_inventory(inventory)))

    if args.check and not inventory.check_passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
