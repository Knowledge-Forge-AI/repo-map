#!/usr/bin/env python3
"""Run the blocking Python type boundary and inventory deferred type debt."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Mapping

if __package__ in (None, ""):
    tools_root = Path(__file__).resolve().parents[1]
    if str(tools_root) not in sys.path:
        sys.path.insert(0, str(tools_root))

from ci.python_type_ownership import (
    DEFAULT_MANIFEST,
    ROOT,
    SOURCE_ROOT,
    OwnershipManifest,
    OwnershipManifestError,
    classify_modules,
    load_manifest,
    maintained_modules,
    module_name_for_path,
    resolve_rule,
    tier_targets,
)
from ci.retained_python_records import EnvironmentAttestation, TypeCheckInventoryRecord


SCHEMA = "repomap-python-type-check-v1"
BLOCKING_TIERS = frozenset({"T0", "T1-seed"})
DEFERRED_TIERS = frozenset({"T2", "T3"})
MYPY_ERROR = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+)(?::\d+)?: error: "
    r"(?P<message>.*?)  \[(?P<code>[^]]+)]$"
)
HISTORICAL_SERVICE_PACKAGE_BASELINE = {
    "checked_source_files": 10,
    "error_count": 282,
    "file_count": 73,
    "missing_psycopg_import_count": 19,
    "top_level": {
        "coordinator": {"errors": 135, "files": 27},
        "extractors": {"errors": 49, "files": 16},
        "graph": {"errors": 6, "files": 2},
        "observations": {"errors": 2, "files": 1},
        "ops": {"errors": 36, "files": 7},
        "runtime": {"errors": 13, "files": 5},
        "storage": {"errors": 41, "files": 15},
    },
}


class TypeCheckToolError(RuntimeError):
    """The sealed interpreter, mypy, manifest, or output is invalid."""


@dataclass(frozen=True)
class MypyError:
    module: str
    path: str
    error_code: str
    fingerprint: str


def architecture_violations(
    manifest: OwnershipManifest,
    modules: Mapping[str, Path],
    source_root: Path = SOURCE_ROOT,
) -> tuple[str, ...]:
    classified = classify_modules(modules, manifest)
    violations = set()
    for module, path in modules.items():
        if classified[module].enforcement_tier not in BLOCKING_TIERS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as error:
            raise TypeCheckToolError(f"cannot parse blocking module {module}") from error
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        for imported in _project_imports(tree, package, modules):
            rule = resolve_rule(imported, manifest)
            if rule is not None and rule.enforcement_tier in DEFERRED_TIERS:
                violations.add(
                    f"{module} imports {rule.enforcement_tier} {imported}"
                )
    return tuple(sorted(violations))


def _project_imports(
    tree: ast.AST,
    package: str,
    maintained_modules: Mapping[str, Path],
) -> tuple[str, ...]:
    """Return direct static imports without claiming dynamic or transitive closure."""
    imports: set[str] = set()
    maintained = frozenset(maintained_modules)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative = "." * node.level + (node.module or "")
                try:
                    imported = importlib.util.resolve_name(relative, package)
                except (ImportError, ValueError):
                    continue
            else:
                imported = node.module or ""
            for alias in node.names:
                candidate = f"{imported}.{alias.name}" if imported else alias.name
                imports.add(candidate if candidate in maintained else imported)
    return tuple(sorted(name for name in imports if name.startswith("repomap_kg")))


def parse_mypy_errors(output: str, repo_root: Path = ROOT) -> tuple[MypyError, ...]:
    errors = []
    source_root = repo_root / "src/main/python"
    for line in output.splitlines():
        match = MYPY_ERROR.match(line)
        if match is None:
            continue
        raw_path = Path(match.group("path"))
        path = raw_path if raw_path.is_absolute() else repo_root / raw_path
        try:
            module = module_name_for_path(path, source_root)
            relative = path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError as error:
            raise TypeCheckToolError("mypy reported a path outside maintained source") from error
        normalized = re.sub(r"\b\d+\b", "<n>", match.group("message"))
        normalized = " ".join(normalized.split())
        fingerprint = hashlib.sha256(
            f"{match.group('code')}\0{normalized}".encode()
        ).hexdigest()
        errors.append(
            MypyError(module, relative, match.group("code"), fingerprint)
        )
    return tuple(errors)


def grouped_inventory(
    errors: tuple[MypyError, ...], manifest: OwnershipManifest
) -> tuple[TypeCheckInventoryRecord, ...]:
    grouped: Counter[tuple[str, str, str, str, str, str]] = Counter()
    for error in errors:
        rule = resolve_rule(error.module, manifest)
        if rule is None:
            raise TypeCheckToolError(f"mypy error module is unclassified: {error.module}")
        grouped[
            (
                error.module,
                error.path,
                rule.ownership_class,
                rule.architecture_box,
                error.error_code,
                error.fingerprint,
            )
        ] += 1
    return tuple(
        TypeCheckInventoryRecord(
            module=key[0],
            path=key[1],
            ownership_class=key[2],
            architecture_box=key[3],
            error_code=key[4],
            normalized_fingerprint=key[5],
            count=count,
        )
        for key, count in sorted(grouped.items())
    )


def result_exit_code(*, blocking_returncode: int, deferred_returncode: int) -> int:
    if blocking_returncode not in {0, 1} or deferred_returncode not in {0, 1}:
        return 2
    return 1 if blocking_returncode == 1 else 0


def _attest_environment() -> EnvironmentAttestation:
    configured = os.environ.get("MYPYPATH")
    if configured is None or Path(configured).resolve() != SOURCE_ROOT.resolve():
        raise TypeCheckToolError("MYPYPATH does not select current-checkout source")
    versions = {
        "mypy": "2.1.0",
        "psycopg": "3.2.12",
        "typing-extensions": "4.16.0",
    }
    for distribution, expected in versions.items():
        if importlib.metadata.version(distribution) != expected:
            raise TypeCheckToolError(f"unexpected {distribution} version")
    owners = {
        "psycopg": Path(sys.prefix),
        "typing_extensions": Path(sys.prefix),
    }
    for module, owner in owners.items():
        spec = importlib.util.find_spec(module)
        if spec is None or spec.origin is None:
            raise TypeCheckToolError(f"required module unavailable: {module}")
        if not Path(spec.origin).resolve().is_relative_to(owner.resolve()):
            raise TypeCheckToolError(f"module owner mismatch: {module}")
    return {
        "versions": versions,
        "owners_attested": sorted(owners),
        "source_authority": "MYPYPATH-current-checkout",
    }


def _mypy(
    targets: tuple[Path, ...],
    *,
    cwd: Path = ROOT,
    config: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "mypy",
        "--follow-imports=silent",
        "--no-error-summary",
    ]
    if config is not None:
        command.extend(("--config-file", str(config)))
    command.extend(str(path) for path in targets)
    return subprocess.run(
        command,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _boundary_probe() -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="repomap-mypy-boundary-") as raw:
        root = Path(raw)
        package = root / "probe"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        deferred = package / "deferred.py"
        contract = package / "contract.py"
        deferred.write_text('value: int = "deferred error"\n', encoding="utf-8")
        contract.write_text(
            'from probe import deferred\nvalue: int = "blocking error"\n',
            encoding="utf-8",
        )
        config = root / "mypy.ini"
        config.write_text("[mypy]\npython_version = 3.12\n", encoding="utf-8")
        env = dict(os.environ)
        env["MYPYPATH"] = str(root)
        red = _mypy((contract,), cwd=root, config=config, env=env)
        contract.write_text(
            "from probe import deferred\nvalue: int = 1\n",
            encoding="utf-8",
        )
        green = _mypy((contract,), cwd=root, config=config, env=env)
    if red.returncode != 1 or green.returncode != 0:
        raise TypeCheckToolError("mypy boundary probe failed")
    return {"blocking_error_failed": True, "deferred_import_did_not_broaden": True}


def _run_checked_mypy(
    targets: tuple[Path, ...],
    *,
    repo_root: Path = ROOT,
) -> tuple[int, tuple[MypyError, ...]]:
    if not targets:
        return 0, ()
    relative = tuple(path.relative_to(repo_root) for path in targets)
    completed = _mypy(relative, cwd=repo_root)
    output = completed.stdout + completed.stderr
    errors = parse_mypy_errors(output, repo_root=repo_root)
    if completed.returncode == 1 and not errors:
        raise TypeCheckToolError("mypy failed without parseable findings")
    if completed.returncode not in {0, 1}:
        raise TypeCheckToolError(f"mypy tool failure: exit={completed.returncode}")
    return completed.returncode, errors


def _distribution(
    inventory: tuple[TypeCheckInventoryRecord, ...],
) -> dict[str, object]:
    errors: Counter[str] = Counter()
    files: dict[str, set[str]] = {}
    for finding in inventory:
        module_parts = str(finding["module"]).split(".")
        top_level = module_parts[1] if len(module_parts) > 1 else "__root__"
        errors[top_level] += int(finding["count"])
        files.setdefault(top_level, set()).add(str(finding["path"]))
    return {
        "error_count": sum(errors.values()),
        "file_count": len({str(item["path"]) for item in inventory}),
        "top_level": {
            name: {"errors": errors[name], "files": len(files[name])}
            for name in sorted(errors)
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    try:
        modules = maintained_modules()
        manifest = load_manifest(args.manifest, modules=modules)
        attestation = _attest_environment()
        probe = _boundary_probe()
        violations = architecture_violations(manifest, modules)
        blocking_targets = tier_targets(modules, manifest, BLOCKING_TIERS)
        deferred_targets = tier_targets(modules, manifest, DEFERRED_TIERS)
        blocking_rc, blocking_errors = _run_checked_mypy(blocking_targets)
        deferred_rc, deferred_errors = _run_checked_mypy(deferred_targets)
        blocking_inventory = grouped_inventory(blocking_errors, manifest)
        deferred_inventory = grouped_inventory(deferred_errors, manifest)
        if violations:
            blocking_rc = 1
        result = result_exit_code(
            blocking_returncode=blocking_rc,
            deferred_returncode=deferred_rc,
        )
        document = {
            "schema": SCHEMA,
            "blocking_targets": [
                path.relative_to(ROOT).as_posix() for path in blocking_targets
            ],
            "deferred_targets": [
                path.relative_to(ROOT).as_posix() for path in deferred_targets
            ],
            "boundary_probe": probe,
            "architecture_violations": list(violations),
            "blocking_inventory": list(blocking_inventory),
            "deferred_inventory": list(deferred_inventory),
            "historical_service_package_baseline": HISTORICAL_SERVICE_PACKAGE_BASELINE,
            "post_runtime_deferred_distribution": _distribution(deferred_inventory),
            "runtime_attestation": attestation,
        }
    except (
        OSError,
        OwnershipManifestError,
        TypeCheckToolError,
        importlib.metadata.PackageNotFoundError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {"schema": SCHEMA, "tool_failure": type(error).__name__},
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(document, sort_keys=True))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
