#!/usr/bin/env python3
"""Emit a deterministic capability inventory for canonical RepoMap tests."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Mapping, TypedDict


SCHEMA = "repomap-test-capability-inventory-v1"
CLASSIFICATIONS = (
    "actual_live_resource",
    "integration_only_behavior",
    "ambiguous_dynamic_behavior",
    "simulated_unit_contract",
)


class CapabilityRecord(TypedDict, total=False):
    classification: str
    origin: str
    lines: list[int]
    inherited_from: dict[str, object]


class ModuleEntry(TypedDict):
    path: str
    suite: str
    capabilities: dict[str, CapabilityRecord]


@dataclass(frozen=True)
class CapabilityRule:
    name: str
    patterns: tuple[str, ...]
    live_patterns: tuple[str, ...] = ()


RULES = (
    CapabilityRule("docker_sdk", (r"docker\.from_env\s*\(",), (r"docker\.from_env\s*\(",)),
    CapabilityRule("docker_cli", (r"['\"](?:docker|podman)['\"]",)),
    CapabilityRule(
        "container_lifecycle",
        (r"['\"](?:docker|podman)['\"].{0,160}['\"](?:run|create|rm|remove|stop|kill)['\"]",),
    ),
    CapabilityRule(
        "image_lifecycle",
        (r"['\"](?:docker|podman)['\"].{0,160}['\"](?:build|pull|inspect|rmi|remove)['\"]",),
    ),
    CapabilityRule(
        "volume_lifecycle",
        (r"['\"](?:docker|podman)['\"].{0,160}['\"]volume['\"]", r"\.volumes\."),
    ),
    CapabilityRule(
        "network_lifecycle",
        (r"['\"](?:docker|podman)['\"].{0,160}['\"]network['\"]", r"\.networks\."),
    ),
    CapabilityRule(
        "temporary_postgres",
        (r"temporary_postgres\s*\(", r"postgres_container_session\s*\("),
        (r"temporary_postgres\s*\(", r"postgres_container_session\s*\("),
    ),
    CapabilityRule(
        "host_port",
        (r"DEFAULT_TEST_POSTGRES_PORT", r"pg_container_port", r"host_port", r"\b55433\b"),
    ),
    CapabilityRule(
        "bind_mounts",
        (
            r"['\"](?:--volume|--mount)['\"]",
            r"\bdocker\b[^\n]{0,120}['\"]-v['\"]",
            r"\bvolumes\s*=",
            r"\bbinds\s*=",
        ),
    ),
    CapabilityRule(
        "source_scratch_mounts",
        (r"/workspace", r"/scratch", r"REPOMAP_TEST_(?:SCRATCH|RUN)_ROOT"),
    ),
    CapabilityRule("proc_inspection", (r"/proc(?:/|['\"])", r"procfs")),
    CapabilityRule(
        "process_signal_control",
        (
            r"\bos\.kill\s*\(",
            r"\bsignal\.(?:SIG|pthread_kill)",
            r"\bsubprocess\.Popen\s*\(",
            r"\bterminate\s*\(",
            r"\bkill\s*\(",
            r"cancellation",
            r"process_containment",
        ),
    ),
    CapabilityRule(
        "unbounded_child_processes",
        (r"\bsubprocess\.Popen\s*\(", r"start_new_session\s*=", r"daemon\s*=\s*True"),
    ),
    CapabilityRule(
        "ipc",
        (r"\bipcs\b", r"\bipcrm\b", r"shared_memory", r"bounded_ipc", r"multiprocessing"),
    ),
    CapabilityRule(
        "filesystem_device_identity",
        (r"\bst_dev\b", r"samefile\s*\(", r"device_identity", r"mount_identity"),
    ),
    CapabilityRule(
        "resource_docker_mediation",
        (
            r"TestResourceRun",
            r"CanonicalDockerAuthority",
            r"resource_(?:run|deletion|quarantine|operator|index)",
            r"docker_mediation",
            r"container_pairs",
        ),
    ),
    CapabilityRule(
        "native_toolchain",
        (
            r"REPOMAP_GO_HELPER",
            r"golangci-lint",
            r"['\"]go['\"]",
            r"native executable",
            r"\b(?:psql|pg_dump|pg_restore|initdb|pg_ctl)\b",
        ),
    ),
    CapabilityRule(
        "network_assumptions",
        (r"\b127\.0\.0\.1\b", r"\blocalhost\b", r"socket\.(?:socket|create_connection)", r"https?://"),
    ),
    CapabilityRule(
        "platform_specific",
        (r"sys\.platform", r"platform\.system", r"os\.name", r"\bwin32\b", r"\bdarwin\b"),
    ),
    CapabilityRule(
        "external_writes",
        (r"Path\.home\s*\(", r"expanduser\s*\(", r"['\"]/(?:tmp|var|etc|Users|home)/"),
    ),
)

FORBIDDEN_UNIT_LIVE_CAPABILITIES = frozenset(
    {
        "docker_sdk",
        "docker_cli",
        "temporary_postgres",
        "ipc",
        "network_assumptions",
        "external_writes",
    }
)


def _line_matches(source: str, rule: CapabilityRule) -> list[int]:
    evidence: list[int] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        for pattern in rule.patterns:
            if re.search(pattern, line, flags=re.IGNORECASE):
                evidence.append(line_number)
                break
    return evidence


def _call_name(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _live_call_lines(source: str) -> set[int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    exact = {
        "docker.from_env",
        "temporary_postgres",
        "postgres_container_session",
        "subprocess.run",
        "subprocess.Popen",
        "os.kill",
    }
    suffixes = (".terminate", ".kill")
    return {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            _call_name(node.func) in exact
            or _call_name(node.func).endswith(suffixes)
        )
    }


def _is_direct_live(source: str, evidence: list[int], rule: CapabilityRule) -> bool:
    live_lines = _live_call_lines(source)
    return any(line in live_lines for line in evidence)


def _classification(suite: str, source: str, rule: CapabilityRule, evidence: list[int]) -> str:
    direct_live = _is_direct_live(source, evidence, rule)
    if suite == "int":
        if direct_live:
            return "actual_live_resource"
        if "getattr(" in source or "import_module(" in source:
            return "ambiguous_dynamic_behavior"
        return "integration_only_behavior"
    simulated_markers = ("fake", "mock", "patch", "stub", "runner(")
    if any(marker in source.lower() for marker in simulated_markers):
        return "simulated_unit_contract"
    if direct_live and rule.name in FORBIDDEN_UNIT_LIVE_CAPABILITIES:
        return "actual_live_resource"
    return "ambiguous_dynamic_behavior"


def _suite_fixture_evidence(root: Path) -> dict[str, dict[str, object]]:
    conftest = root / "src" / "test" / "int" / "python" / "conftest.py"
    if not conftest.is_file():
        return {}
    source = conftest.read_text(encoding="utf-8")
    relative = conftest.relative_to(root).as_posix()
    result: dict[str, dict[str, object]] = {}
    for name in ("temporary_postgres", "host_port"):
        rule = next(item for item in RULES if item.name == name)
        evidence = _line_matches(source, rule)
        if evidence:
            result[name] = {"owner": relative, "lines": evidence}
    return result


def _module_entry(
    root: Path, path: Path, suite_fixtures: Mapping[str, dict[str, object]]
) -> ModuleEntry:
    suite = "int" if "/int/" in path.as_posix() else "unit"
    source = path.read_text(encoding="utf-8")
    capabilities: dict[str, CapabilityRecord] = {}
    for rule in RULES:
        evidence = _line_matches(source, rule)
        if evidence:
            capabilities[rule.name] = {
                "classification": _classification(suite, source, rule, evidence),
                "origin": "module",
                "lines": evidence,
            }
        elif suite == "int" and rule.name in suite_fixtures:
            capabilities[rule.name] = {
                "classification": "actual_live_resource",
                "origin": "suite_fixture",
                "inherited_from": suite_fixtures[rule.name],
            }
    return {
        "path": path.relative_to(root).as_posix(),
        "suite": suite,
        "capabilities": capabilities,
    }


def _counts(modules: list[ModuleEntry]) -> dict[str, object]:
    suite_counts = Counter(entry["suite"] for entry in modules)
    capability_counts: dict[str, dict[str, dict[str, int]]] = {}
    for rule in RULES:
        classification_counts = Counter(
            entry["capabilities"][rule.name]["classification"]
            for entry in modules
            if rule.name in entry["capabilities"]
        )
        origin_counts = Counter(
            entry["capabilities"][rule.name]["origin"]
            for entry in modules
            if rule.name in entry["capabilities"]
        )
        capability_counts[rule.name] = {
            "classifications": {
                classification: classification_counts[classification]
                for classification in CLASSIFICATIONS
                if classification_counts[classification]
            },
            "origins": dict(sorted(origin_counts.items())),
        }
    return {
        "modules": dict(sorted(suite_counts.items())),
        "capabilities": capability_counts,
    }


def build_inventory(repo_root: Path) -> dict[str, object]:
    root = repo_root.resolve()
    suite_fixtures = _suite_fixture_evidence(root)
    paths = sorted(
        path
        for suite in ("int", "unit")
        for path in (root / "src" / "test" / suite / "python").rglob("*.test.py")
    )
    modules = [_module_entry(root, path, suite_fixtures) for path in paths]
    violations = sorted(
        {
            (entry["path"], capability)
            for entry in modules
            if entry["suite"] == "unit"
            for capability, record in entry["capabilities"].items()
            if capability in FORBIDDEN_UNIT_LIVE_CAPABILITIES
            and record["classification"] == "actual_live_resource"
        }
    )
    return {
        "schema": SCHEMA,
        "criteria": {
            "module_population": "tracked-layout *.test.py files under canonical int/unit roots",
            "direct_evidence": "line-level executable indicators, not import names alone",
            "suite_inheritance": "canonical integration conftest Postgres session and host-port owner",
            "classifications": list(CLASSIFICATIONS),
            "omitted_capability_classification": "none",
        },
        "counts": _counts(modules),
        "modules": modules,
        "unit_live_resource_violations": [
            {"capability": capability, "path": path}
            for path, capability in violations
        ],
    }


def inventory_json(inventory: dict[str, object]) -> str:
    return json.dumps(inventory, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--entry-revision")
    args = parser.parse_args(argv)
    inventory = build_inventory(args.repo_root)
    if args.entry_revision is not None:
        if re.fullmatch(r"[0-9a-f]{40}", args.entry_revision) is None:
            parser.error("--entry-revision must be an exact 40-character Git object ID")
        inventory["source_tree_revision"] = args.entry_revision
    text = inventory_json(inventory)
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
