"""Validate declared dynamic operations and add governed dependency obligations."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ci.python_retention_dynamic_history import active_boundaries
from ci.python_retention_dynamic_coverage import coverage_fixture
from ci.python_retention_dynamic_false_identity import generated_false_code_identity
from ci.python_retention_dynamic_loaders import file_loader_spec
from ci.python_retention_dynamic_recipes import (
    fingerprint, guarded_symbol_import, literal_module_entry,
)
from ci.python_retention_dynamic_substitution import optional_import_substitution
from ci.python_retention_owner_contract import validate_owner_context


def _source(root: Path, path: str, digest: str, candidates: set[str]) -> bytes:
    full = root / path
    if (path not in candidates or not full.is_file() or full.is_symlink()
            or full.resolve() != root.resolve() / path):
        raise ValueError("dynamic target absent, outside candidate or aliased")
    source = full.read_bytes()
    if hashlib.sha256(source).hexdigest() != digest:
        raise ValueError("dynamic source identity drift")
    return source


def _declares(tree: ast.Module, symbol: str, visiting: frozenset[str] = frozenset()) -> bool:
    if symbol in visiting:
        return False
    # Existing executor exports use simple same-module function aliases.
    aliases = [n for n in tree.body if isinstance(n, ast.Assign)
               and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
               and n.targets[0].id == symbol and isinstance(n.value, ast.Name)]
    if len(aliases) == 1:
        value = aliases[0].value
        assert isinstance(value, ast.Name)
        return _declares(tree, value.id, visiting | {symbol})
    body = tree.body
    for part in symbol.split('.'):
        nodes = [n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                  ast.ClassDef)) and n.name == part]
        if len(nodes) != 1:
            return False
        body = nodes[0].body
    return True


def validate_boundary(root: Path, candidates: set[str], graph: Mapping[str, Any],
                      record: dict[str, Any],
                      active_records: Sequence[dict[str, Any]] = ()) -> list[str]:
    """Independently resolve a declaration; return edges, never governance credit."""
    source = _source(root, record["owner"], record["owner_sha256"], candidates)
    _source(root, record["test"], record["test_sha256"], candidates)
    if not record["test"].startswith("src/test/unit/python/"):
        raise ValueError("dynamic contract requires a maintained unit test owner")
    if (record["test"] != record["owner"] and record["owner"] not in
            graph["static_dependencies"].get(record["test"], ())):
        raise ValueError("dynamic test must statically depend on its owner")
    tree = ast.parse(source)
    operations = graph["dynamic_operations"].get(record["owner"], [])
    matches = [op for op in operations if all(op[k] == record[k]
               for k in ("kind", "symbol", "fingerprint"))]
    if len(matches) != 1:
        raise ValueError("dynamic operation absent, ambiguous or drifted")
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.Call, ast.Subscript))
             and fingerprint(n) == record["fingerprint"] and n.lineno == matches[0]["lineno"]]
    if len(nodes) != 1:
        raise ValueError("dynamic call must be unambiguous")
    modules = graph["module_to_path"]
    if (record["recipe"] in {"file_loader_spec", "optional_import_substitution"}
            or (record["recipe"] == "literal_coverage_fixture"
                and record["parameters"].get("case") in {
                    "caller_mod", "decision_mod", "capability_mod"})):
        validate_owner_context(record["owner"], tree)
    if record["recipe"] in {"literal_module_entry", "guarded_symbol_import"} and not isinstance(nodes[0], ast.Call):
        raise ValueError("existing recipe requires a call")
    if record["recipe"] == "literal_coverage_fixture":
        required = coverage_fixture(nodes[0], tree, record["parameters"])
        _require_complete_chain(record, active_records)
    elif record["recipe"] == "generated_false_code_identity":
        if not isinstance(nodes[0], ast.Call):
            raise ValueError("false identity recipe requires a call")
        required = generated_false_code_identity(nodes[0], tree, record["parameters"], root, modules)
        _require_complete_chain(record, active_records)
    elif record["recipe"] == "file_loader_spec":
        required = file_loader_spec(nodes[0], tree, record["parameters"], root, modules)
        _require_complete_chain(record, active_records)
    elif record["recipe"] == "optional_import_substitution":
        required = optional_import_substitution(nodes[0], tree, record["parameters"], root, modules)
        _require_complete_chain(record, active_records)
    elif record["recipe"] == "literal_module_entry":
        assert isinstance(nodes[0], ast.Call)
        required = literal_module_entry(nodes[0], tree, record["parameters"], modules)
    elif record["recipe"] == "guarded_symbol_import":
        assert isinstance(nodes[0], ast.Call)
        required = guarded_symbol_import(nodes[0], tree, record["parameters"], root, modules)
    else:
        raise ValueError("unsupported dynamic recipe")
    found: set[tuple[str, str]] = set()
    edges: set[str] = set()
    for target in record["targets"]:
        if not isinstance(target, dict) or set(target) != {"module", "symbol", "path", "sha256"}:
            raise ValueError("invalid dynamic target keys")
        if any(not isinstance(target[k], str) for k in target):
            raise ValueError("invalid dynamic target value")
        pair = target["module"], target["symbol"]
        if pair in found or modules.get(target["module"]) != target["path"]:
            raise ValueError("duplicate or mismatched dynamic module/source")
        target_source = _source(root, target["path"], target["sha256"], candidates)
        if target["symbol"] and not _declares(ast.parse(target_source), target["symbol"]):
            raise ValueError("dynamic symbol absent from declared source")
        found.add(pair)
        edges.add(target["path"])
        edges.update(graph["package_inits"].get(target["path"], ()))
    if found != required:
        raise ValueError("declared dynamic targets differ from independently resolved targets")
    if record["recipe"] == "guarded_symbol_import":
        edges.add(record["parameters"]["domain_path"])
    return sorted(edges)


def _require_complete_chain(record: dict[str, Any], records: Sequence[dict[str, Any]]) -> None:
    """A closed multi-operation recipe is admitted only as one complete declaration group."""
    chain = record["parameters"].get("chain")
    if not isinstance(chain, list) or not chain:
        raise ValueError("closed recipe requires a complete operation chain")
    peers = [r for r in records if r["owner"] == record["owner"]
             and r["symbol"] == record["symbol"]]
    if any(r["recipe"] != record["recipe"] or r["parameters"] != record["parameters"]
           for r in peers):
        raise ValueError("ambiguous closed recipe chain")
    actual = [{k: r[k] for k in ("kind", "fingerprint")} for r in peers]
    canonical = lambda items: sorted(json.dumps(item, sort_keys=True) for item in items)
    if canonical(actual) != canonical(chain):
        raise ValueError("partial or duplicate closed recipe chain")


def apply_dynamic_boundaries(root: Path, candidate_paths: Sequence[str],
                             graph: dict[str, Any]) -> dict[str, Any]:
    """Apply exact declarations while retaining every undeclared dynamic operation."""
    inventory = root / "tools/ci/python_retention_inventory.json"
    if not inventory.exists():
        return graph
    try:
        document = json.loads(inventory.read_bytes())
        records = active_boundaries(document)
    except (OSError, ValueError, TypeError) as error:
        for path in candidate_paths:
            graph["errors"][path] = f"dynamic authority invalid: {type(error).__name__}"
        return graph
    resolved: dict[str, list[str]] = {}
    discharged: dict[str, set[tuple[str, str, str]]] = {}
    candidates = set(candidate_paths)
    for record in records:
        owner = record["owner"]
        try:
            edges = validate_boundary(root, candidates, graph, record, records)
        except (OSError, ValueError, TypeError, KeyError, SyntaxError) as error:
            for path in ([owner] if owner in candidates else candidate_paths):
                graph["errors"][path] = f"dynamic declaration {record['id']}: {error}"
            continue
        resolved[record["id"]] = edges
        graph["dependencies"][owner] = sorted(set(graph["dependencies"][owner]) | set(edges))
        discharged.setdefault(owner, set()).add(tuple(record[k] for k in ("kind", "symbol", "fingerprint")))
    for owner, identities in discharged.items():
        remaining = [op for op in graph["dynamic_operations"][owner]
                     if tuple(op[k] for k in ("kind", "symbol", "fingerprint")) not in identities]
        if remaining:
            graph["dynamic_uncertainty"][owner] = [f"undeclared dynamic {op['kind']}" for op in remaining]
        else:
            graph["dynamic_uncertainty"].pop(owner, None)
    graph["resolved_dynamic_dependencies"] = resolved
    return graph
