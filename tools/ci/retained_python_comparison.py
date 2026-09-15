"""Typed comparison records for retained-Python ratchet snapshots."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence, TypedDict

from ci.file_length_policy import (
    FAILURE_LIMIT,
    WARNING_LIMIT,
    FileLengthOperationalError,
    count_physical_lines,
    resolve_tracked_path,
)
from ci.python_type_check import parse_mypy_errors, _project_imports
from ci.python_type_ownership import (
    OwnershipManifest,
    classify_modules,
    resolve_rule,
)
from ci.retained_python_records import (
    BaselineDocument,
    ScopeChange,
    ScopeSelection,
    SelectionModuleRecord,
    FileLengthRecord,
    ImportEdgeRecord,
    MypyFindingRecord,
    RecordValidationError,
    RuffFindingRecord,
)


def _relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as error:
        raise RecordValidationError("path escapes repository root") from error


def select_retained_modules(
    modules: Mapping[str, Path],
    manifest: OwnershipManifest,
    retained_classes: Sequence[str],
    repo_root: Path,
) -> tuple[SelectionModuleRecord, ...]:
    """Select retained modules matching requested ownership classes.

    The public `modules` parameter accepts a mapping of module name to filesystem path.
    The dependency scanner flags subscripts named `modules` as dynamic imports.
    The `module_paths` alias identifies this ordinary path mapping without changing
    the public keyword parameter or relaxing that conservative scanner rule.
    """
    module_paths: Mapping[str, Path] = modules
    classified = classify_modules(module_paths, manifest)
    return tuple(
        SelectionModuleRecord(
            module=module,
            path=_relative(module_paths[module], repo_root),
            ownership_class=classified[module].ownership_class,
            tier=classified[module].enforcement_tier,
        )
        for module in sorted(module_paths)
        if classified[module].ownership_class in retained_classes
    )


def normalize_ruff_inventory(
    findings: object, selected_paths: frozenset[str], repo_root: Path
) -> tuple[RuffFindingRecord, ...]:
    if not isinstance(findings, list):
        raise RecordValidationError("Ruff JSON has no finding collection")
    grouped: Counter[tuple[str, str, str, str]] = Counter()
    for finding in findings:
        if not isinstance(finding, dict):
            raise RecordValidationError("Ruff finding is invalid")
        raw_path, code, message = (
            finding.get("filename"),
            finding.get("code"),
            finding.get("message"),
        )
        if not isinstance(raw_path, str) or not isinstance(code, str) or not isinstance(message, str):
            raise RecordValidationError("Ruff finding fields are invalid")
        relative = _relative(Path(raw_path) if Path(raw_path).is_absolute() else repo_root / raw_path, repo_root)
        if relative not in selected_paths or not code.startswith("F"):
            raise RecordValidationError("Ruff reported outside the retained full-F set")
        normalized = " ".join(message.split())
        fingerprint = hashlib.sha256(f"{relative}\0{code}\0{normalized}".encode()).hexdigest()
        grouped[(relative, code, normalized, fingerprint)] += 1
    return tuple(
        RuffFindingRecord(
            path=key[0], code=key[1], message=key[2], fingerprint=key[3], count=count
        )
        for key, count in sorted(grouped.items())
    )


def mypy_inventory(
    output: str,
    manifest: OwnershipManifest,
    selected_modules: frozenset[str],
    repo_root: Path,
) -> tuple[MypyFindingRecord, ...]:
    grouped: Counter[tuple[str, str, str, str]] = Counter()
    for error in parse_mypy_errors(output, repo_root):
        rule = resolve_rule(error.module, manifest)
        if error.module not in selected_modules or rule is None or rule.enforcement_tier != "T1-future":
            raise RecordValidationError("mypy reported outside the T1-future set")
        grouped[(error.module, error.path, error.error_code, error.fingerprint)] += 1
    return tuple(
        MypyFindingRecord(
            module=key[0], path=key[1], error_code=key[2],
            normalized_fingerprint=key[3], count=count,
        )
        for key, count in sorted(grouped.items())
    )


def migration_edges(
    manifest: OwnershipManifest,
    modules: Mapping[str, Path],
    repo_root: Path,
) -> tuple[ImportEdgeRecord, ...]:
    """Identify migration direction import edges from T1-future to T2/T3.

    The public `modules` parameter accepts a mapping of module name to filesystem path.
    The dependency scanner flags subscripts named `modules` as dynamic imports.
    The `module_paths` alias identifies this ordinary path mapping without changing
    the public keyword parameter or relaxing that conservative scanner rule.
    """
    module_paths: Mapping[str, Path] = modules
    classified = classify_modules(module_paths, manifest)
    edges: set[tuple[str, str, str, str]] = set()
    for module in sorted(module_paths):
        if classified[module].enforcement_tier != "T1-future":
            continue
        path = module_paths[module]
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as error:
            raise RecordValidationError("cannot parse T1-future module") from error
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        for imported in _project_imports(tree, package, module_paths):
            rule = resolve_rule(imported, manifest)
            if rule is not None and rule.enforcement_tier in {"T2", "T3"}:
                edges.add((module, _relative(path, repo_root), imported, rule.enforcement_tier))
    return tuple(
        ImportEdgeRecord(
            source_module=item[0], source_path=item[1],
            target_module=item[2], target_tier=item[3],
        )
        for item in sorted(edges)
    )


def file_length_inventory(
    selection: Sequence[Mapping[str, object]], repo_root: Path
) -> tuple[tuple[FileLengthRecord, ...], tuple[FileLengthRecord, ...]]:
    ceilings: list[FileLengthRecord] = []
    hard: list[FileLengthRecord] = []
    for item in selection:
        path = item.get("path")
        if not isinstance(path, str):
            raise RecordValidationError("baseline path is invalid")
        safe = PurePosixPath(path)
        if safe.is_absolute() or ".." in safe.parts or "\\" in path:
            raise RecordValidationError("baseline path is invalid")
        try:
            resolved = resolve_tracked_path(repo_root.resolve(), safe)
        except FileLengthOperationalError as error:
            raise RecordValidationError("retained file path is invalid") from error
        record = FileLengthRecord(path=path, line_count=count_physical_lines(resolved))
        if record["line_count"] > FAILURE_LIMIT:
            hard.append(record)
        elif record["line_count"] > WARNING_LIMIT:
            ceilings.append(record)
    return tuple(ceilings), tuple(hard)


class Comparison(TypedDict):
    new: list[dict[str, object]]
    increased: list[dict[str, object]]
    removed: list[dict[str, object]]
    decreased: list[dict[str, object]]
    unchanged: list[dict[str, object]]


class SelectionComparison(TypedDict):
    new: list[SelectionModuleRecord]
    removed: list[SelectionModuleRecord]
    changed: list[dict[str, object]]
    unchanged: list[SelectionModuleRecord]


def _identity(item: Mapping[str, object], fields: Sequence[str]) -> tuple[str, ...]:
    values: list[str] = []
    for field in fields:
        value = item.get(field)
        if not isinstance(value, str):
            raise ValueError("comparison identity field is not a string")
        values.append(value)
    return tuple(values)


def _count(item: Mapping[str, object], field: str = "count") -> int:
    value = item.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"comparison {field} is not an integer")
    return value


def _comparison() -> Comparison:
    return {
        "new": [],
        "increased": [],
        "removed": [],
        "decreased": [],
        "unchanged": [],
    }


def compare_counted(
    actual: Sequence[Mapping[str, object]],
    baseline: Sequence[Mapping[str, object]],
    identity_fields: Sequence[str],
) -> Comparison:
    old = {_identity(item, identity_fields): item for item in baseline}
    new = {_identity(item, identity_fields): item for item in actual}
    result = _comparison()
    for key in sorted(set(old) | set(new)):
        if key not in old:
            result["new"].append(dict(new[key]))
        elif key not in new:
            result["removed"].append(dict(old[key]))
        else:
            before, after = _count(old[key]), _count(new[key])
            if after == before:
                result["unchanged"].append(dict(new[key]))
            else:
                record = {field: new[key][field] for field in identity_fields}
                record.update({"baseline_count": before, "actual_count": after})
                result["increased" if after > before else "decreased"].append(record)
    return result


def compare_file_lengths(
    actual: Sequence[Mapping[str, object]],
    baseline: Sequence[Mapping[str, object]],
) -> Comparison:
    old = {_identity(item, ("path",))[0]: item for item in baseline}
    new = {_identity(item, ("path",))[0]: item for item in actual}
    result = _comparison()
    for path in sorted(set(old) | set(new)):
        if path not in old:
            result["new"].append(dict(new[path]))
        elif path not in new:
            result["removed"].append(dict(old[path]))
        else:
            before, after = _count(old[path], "line_count"), _count(new[path], "line_count")
            if after == before:
                result["unchanged"].append(dict(new[path]))
            else:
                record = {
                    "path": path,
                    "baseline_line_count": before,
                    "actual_line_count": after,
                }
                result["increased" if after > before else "decreased"].append(record)
    return result


def compare_selection(
    actual: Sequence[SelectionModuleRecord],
    baseline: Sequence[SelectionModuleRecord],
) -> SelectionComparison:
    old = {item["module"]: item for item in baseline}
    new = {item["module"]: item for item in actual}
    result: SelectionComparison = {
        "new": [],
        "removed": [],
        "changed": [],
        "unchanged": [],
    }
    for module in sorted(set(old) | set(new)):
        if module not in old:
            result["new"].append(new[module])
        elif module not in new:
            result["removed"].append(old[module])
        elif new[module] != old[module]:
            result["changed"].append({"baseline": old[module], "actual": new[module]})
        else:
            result["unchanged"].append(new[module])
    return result


def result_comparison(comparison: Mapping[str, object]) -> dict[str, object]:
    rendered: dict[str, object] = {}
    for name, raw_values in comparison.items():
        if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
            raise ValueError("comparison values are not a sequence")
        rendered[name] = len(raw_values) if name == "unchanged" else list(raw_values)
    return rendered


def has_policy_deltas(comparisons: Sequence[Mapping[str, object]]) -> bool:
    for comparison in comparisons:
        for name, raw_values in comparison.items():
            if name == "unchanged":
                continue
            if isinstance(raw_values, Sequence) and raw_values:
                return True
    return False


def summary_counts(comparisons: Sequence[Mapping[str, object]]) -> dict[str, int]:
    names = ("new", "increased", "removed", "decreased", "changed", "unchanged")
    summary = {name: 0 for name in names}
    for comparison in comparisons:
        for name in names:
            raw_values = comparison.get(name, ())
            if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes)):
                summary[name] += len(raw_values)
    return summary


def additions_have_debt(
    additions: Sequence[ScopeSelection], after: BaselineDocument
) -> bool:
    ruff_paths = {item["path"] for item in after["ruff"]["findings"]}
    mypy_modules = {item["module"] for item in after["mypy"]["findings"]}
    edge_sources = {
        item["source_module"]
        for item in after["migration_direction_imports"]["edges"]
    }
    ceiling_paths = {item["path"] for item in after["file_length"]["ceilings"]}
    return any(
        item["path"] in ruff_paths
        or item["module"] in mypy_modules
        or item["module"] in edge_sources
        or item["path"] in ceiling_paths
        for item in additions
    )


def has_upward_debt(before: BaselineDocument, after: BaselineDocument) -> bool:
    counted = (
        compare_counted(
            after["ruff"]["findings"],
            before["ruff"]["findings"],
            ("path", "code", "message", "fingerprint"),
        ),
        compare_counted(
            after["mypy"]["findings"],
            before["mypy"]["findings"],
            ("module", "path", "error_code", "normalized_fingerprint"),
        ),
        compare_counted(
            [dict(item, count=1) for item in after["migration_direction_imports"]["edges"]],
            [dict(item, count=1) for item in before["migration_direction_imports"]["edges"]],
            ("source_module", "source_path", "target_module", "target_tier"),
        ),
    )
    lengths = compare_file_lengths(
        after["file_length"]["ceilings"], before["file_length"]["ceilings"]
    )
    return any(result["new"] or result["increased"] for result in counted) or bool(
        lengths["new"] or lengths["increased"]
    )


def selection_delta(
    before: BaselineDocument,
    after: BaselineDocument,
) -> tuple[list[ScopeChange], tuple[ScopeSelection, ...], bool]:
    old = {item["module"]: item for item in before["selection"]["modules"]}
    new = {item["module"]: item for item in after["selection"]["modules"]}
    changes: list[ScopeChange] = []
    additions: list[ScopeSelection] = []
    restricted = False
    for module in sorted(set(old) | set(new)):
        prior, current = old.get(module), new.get(module)
        if prior == current:
            continue
        changes.append({"old": prior, "new": current})
        if prior is None:
            if current is not None:
                additions.append(current)
        else:
            restricted = True
    return changes, tuple(additions), restricted
