"""Configuration filename formats, layer order and read-only CLOE rename plans."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Collection, Sequence
import unicodedata

from repomap_kg.ops.config_records import OpsConfigDiagnostic, OpsConfigError


def _portable_name(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _classification(name: str) -> tuple[str, int] | None:
    for suffix, format_name, layer in (
        (".local.cloe.toml", "cloe", 1),
        (".cloe.toml", "cloe", 0),
        (".rpl.toml", "legacy", 1),
        (".rp.toml", "legacy", 0),
    ):
        if name.endswith(suffix):
            return format_name, layer
    return None


def portable_config_name(name: str) -> str:
    """The conservative NFC/case-folded comparison key used for collisions."""
    return _portable_name(name)


def classify_config_filename(name: str) -> tuple[str, int] | None:
    """Return ``(family, layer)`` for a configuration filename, where layer 1 is local."""
    return _classification(name)


def discover_home_config_files(home: Path) -> tuple[list[Path], list[Path]]:
    """Keep top-level discovery and ordering; refuse competing format families."""
    matched: list[tuple[int, Path]] = []
    ignored: list[Path] = []
    formats: Counter[str] = Counter()
    for child in sorted(home.iterdir(), key=lambda item: item.name):
        if not child.is_file():
            continue
        classification = _classification(child.name)
        if classification is not None:
            format_name, layer = classification
            formats[format_name] += 1
            matched.append((layer, child))
        elif child.suffix == ".toml":
            ignored.append(child)
    if len(formats) > 1:
        raise OpsConfigError((OpsConfigDiagnostic(
            "error", "config-home-mixed-format", "config-home",
            f"configuration home mixes legacy ({formats['legacy']}) and CLOE "
            f"({formats['cloe']}) files; select one active format",
        ),))
    return [path for _, path in sorted(matched, key=lambda item: (item[0], item[1].name))], ignored


def plan_cloe_config_filenames(
    config_files: Sequence[str], *, occupied_names: Collection[str] = (),
) -> dict[str, Any]:
    """Plan names in existing load order, without reading values or applying changes."""
    if not config_files or len(set(config_files)) != len(config_files):
        raise ValueError("configuration filename plan requires distinct input files")
    classifications = []
    for name in config_files:
        classification = _classification(name)
        if classification is None or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("configuration filename plan requires recognized home filenames")
        classifications.append(classification)
    formats = {item[0] for item in classifications}
    if len(formats) != 1:
        raise ValueError("configuration filename plan requires one active format")
    format_name = classifications[0][0]
    changes: list[dict[str, str]] = []
    targets = list(config_files)
    refusals: list[dict[str, str]] = []
    if format_name == "legacy":
        targets = []
        for name, (_, layer) in zip(config_files, classifications):
            target = name[:-9] + ".local.cloe.toml" if layer else name[:-8] + ".cloe.toml"
            targets.append(target)
            changes.append({"source": name, "target": target, "layer": "local" if layer else "base"})
            if not layer and target.endswith(".local.cloe.toml"):
                refusals.append({"code": "base-became-local", "file": name})
        for key, count in sorted(Counter(_portable_name(name) for name in targets).items()):
            if count > 1:
                name = next(name for name in targets if _portable_name(name) == key)
                refusals.append({"code": "target-collision", "file": name})
        occupied = {_portable_name(name) for name in occupied_names}
        for name in sorted(set(targets)):
            if _portable_name(name) in occupied:
                refusals.append({"code": "target-already-exists", "file": name})
    proposed = sorted(targets, key=lambda name: (name.endswith(".local.cloe.toml"), name))
    if proposed != targets:
        refusals.append({"code": "layer-order-changed", "file": ""})
    return {
        "schema": "cloe-config-filename-plan-v1",
        "source_format": format_name,
        "source_order": list(config_files),
        "proposed_order": proposed,
        "changes": changes,
        "refusals": refusals,
        "conversion_required": format_name == "legacy",
        "filename_conversion_ready": not refusals,
        "read_only": True,
        "writes_performed": 0,
        "apply_supported": False,
    }
