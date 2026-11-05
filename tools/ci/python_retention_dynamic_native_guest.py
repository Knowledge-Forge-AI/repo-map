"""Closed ADR0155 native-guest import recipe; it never imports guest packages."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from ci.python_retention_dynamic_recipes import fingerprint, imported_names, qualified


_SCHEMA = "external-native-guest-import-v1"
_LOCK_ID = "rust-pilot-lock-1"
_LOCK_SHA256 = "f9c7040f9f57126aad99cdae0750a9280eaa5d067026ad05a3aaf001b881a0f8"
_LOCK_SOURCE_SHA256 = "5fe8660f90dcf163932446c7b057a390096cd3f9fd972f1077e215367108849a"
_LOCK_MODULE = "common_lore_index.extractors.rust_pilot.component_lock"
_LOCK_PATH = "src/main/python/common_lore_index/extractors/rust_pilot/component_lock.py"
_OWNER_PATHS = (
    "src/main/python/common_lore_index/extractors/rust_pilot/guest/parse_helper.py",
    "src/main/python/common_lore_index/extractors/rust_pilot/guest/runtime_probe.py",
)
_MODULES = ("tree_sitter", "tree_sitter_rust")


def _bound_source(root: Path, path: str, digest: str) -> bytes:
    """Read one exact repository-relative source commitment without aliasing."""
    if not isinstance(path, str) or not isinstance(digest, str):
        raise ValueError("native source commitment is malformed")
    candidate = Path(path)
    base = root.resolve()
    full = root / candidate
    if (not path or candidate.is_absolute() or ".." in candidate.parts
            or full.is_symlink() or not full.is_file()):
        raise ValueError("native source is absent, aliased or outside repository")
    if full.resolve() != base / candidate:
        raise ValueError("native source is aliased or outside repository")
    data = full.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("native source identity drift")
    return data


def _reject_selector_mutation(tree: ast.AST) -> None:
    """Reject aliases and mutation paths for the closed import selector."""
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.arg in {"importlib", "import_module"}:
            raise ValueError("native import selector is shadowed")
        if (isinstance(node, ast.Name) and node.id in {"importlib", "import_module"}
                and isinstance(node.ctx, (ast.Store, ast.Del))):
            raise ValueError("native import selector is rebound")
        if (isinstance(node, ast.Attribute) and node.attr == "import_module"
                and isinstance(node.ctx, (ast.Store, ast.Del))):
            raise ValueError("native import selector attribute is mutated")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {"setattr", "delattr"}):
            raise ValueError("native import selector mutator is forbidden")
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if isinstance(value, ast.Name) and value.id in {"setattr", "delattr"}:
                raise ValueError("native import selector mutator alias is forbidden")
            if isinstance(value, ast.Attribute) and value.attr in {"setattr", "delattr"}:
                raise ValueError("native import selector mutator alias is forbidden")
            if isinstance(value, ast.Attribute) and value.attr == "import_module":
                raise ValueError("native import selector alias is forbidden")


def _validate_loop(tree: ast.AST, call: ast.Call,
                   module_names: tuple[str, ...]) -> None:
    """Require one unaliased importlib loop with one closed literal tuple."""
    _reject_selector_mutation(tree)
    names = imported_names(tree)
    aliases = [alias for node in ast.walk(tree) if isinstance(node, ast.Import)
               for alias in node.names if alias.name == "importlib"]
    if len(aliases) != 1 or aliases[0].asname is not None:
        raise ValueError("native importer must bind importlib exactly once")
    if names.get("importlib") != "importlib":
        raise ValueError("native importer binding is rebound or ambiguous")
    if any(isinstance(node, ast.ImportFrom) and node.module == "importlib"
           for node in ast.walk(tree)):
        raise ValueError("native importer cannot import the selector directly")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
                alias.name.split(".")[0] in module_names for alias in node.names):
            raise ValueError("native packages must remain guest-only dynamic imports")
        if (isinstance(node, ast.ImportFrom) and node.module
                and node.module.split(".")[0] in module_names):
            raise ValueError("native packages must remain guest-only dynamic imports")
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"]
    if len(calls) != 1 or calls[0] is not call:
        raise ValueError("native importer must have one import site")
    if (qualified(call.func, names) != "importlib.import_module"
            or len(call.args) != 1 or call.keywords
            or not isinstance(call.args[0], ast.Name)
            or call.args[0].id != "name"):
        raise ValueError("native importer selector call differs from closed contract")
    loops = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "name" or not isinstance(node.iter, ast.Tuple):
            continue
        try:
            values = tuple(ast.literal_eval(item) for item in node.iter.elts)
        except (TypeError, ValueError, SyntaxError):
            continue
        if values == module_names:
            loops.append(node)
    if len(loops) != 1:
        raise ValueError("native importer requires one literal module tuple loop")
    loop = loops[0]
    if (loop.orelse or len(loop.body) != 1 or not isinstance(loop.body[0], ast.Expr)
            or not isinstance(loop.body[0].value, ast.Call)):
        raise ValueError("native importer loop body differs from closed contract")
    append = loop.body[0].value
    if (not isinstance(append.func, ast.Attribute)
            or not isinstance(append.func.value, ast.Name)
            or append.func.value.id != "modules" or append.func.attr != "append"
            or len(append.args) != 1 or append.keywords or append.args[0] is not call):
        raise ValueError("native importer loop must append the one selector call")
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                   and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == "modules"]
    if (len(assignments) != 1 or not isinstance(assignments[0].value, ast.List)
            or assignments[0].value.elts):
        raise ValueError("native importer accumulator must be one empty list")


def _validate_owner(source: bytes, record: Mapping[str, Any],
                    module_names: tuple[str, ...]) -> None:
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"]
    if (record.get("kind") != "import_module" or record.get("symbol") != "main"
            or len(calls) != 1 or fingerprint(calls[0]) != record.get("fingerprint")):
        raise ValueError("native owner dynamic operation differs from declaration")
    _validate_loop(tree, calls[0], module_names)


def external_native_guest_import(
    call: ast.Call,
    tree: ast.AST,
    parameters: Mapping[str, Any],
    repo_root: Path,
    module_paths: Mapping[str, str],
    *,
    record: Mapping[str, Any],
    active_records: Sequence[Mapping[str, Any]],
) -> set[tuple[str, str]]:
    """Close exactly the two ADR0155 guest imports without a project edge."""
    expected = {
        "schema", "component_lock_path", "component_lock_source_sha256",
        "component_lock_sha256", "component_lock_id", "guest_owners", "modules",
        "import_module", "loop",
    }
    if set(parameters) != expected:
        raise ValueError("native importer declaration keys are not closed")
    if (parameters["schema"] != _SCHEMA
            or parameters["component_lock_id"] != _LOCK_ID
            or parameters["component_lock_sha256"] != _LOCK_SHA256
            or parameters["component_lock_source_sha256"] != _LOCK_SOURCE_SHA256
            or parameters["component_lock_path"] != _LOCK_PATH
            or parameters["modules"] != list(_MODULES)
            or parameters["import_module"] != "importlib.import_module"
            or parameters["loop"] != "literal-tuple-once-v1"):
        raise ValueError("native importer declaration differs from ADR0155")
    if record.get("targets") != []:
        raise ValueError("native guest import cannot fabricate project targets")
    peers = [item for item in active_records
             if item.get("recipe") == "external_native_guest_import"]
    if (len(peers) != 2
            or {item.get("owner") for item in peers} != set(_OWNER_PATHS)
            or len({item.get("owner") for item in peers}) != 2
            or any(item.get("parameters") != dict(parameters)
                   or item.get("targets") != [] for item in peers)):
        raise ValueError("native importer must bind exactly the two guest owners")
    if len({(item.get("test"), item.get("test_sha256")) for item in peers}) != 1:
        raise ValueError("native importer owners must share one maintained witness")
    owners = parameters["guest_owners"]
    if (not isinstance(owners, list) or len(owners) != len(_OWNER_PATHS)
            or any(not isinstance(item, dict) or set(item) != {"path", "sha256"}
                   for item in owners)):
        raise ValueError("native guest owner commitments are not closed")
    if [item["path"] for item in owners] != list(_OWNER_PATHS):
        raise ValueError("native guest owner paths differ from ADR0155")
    if module_paths.get(_LOCK_MODULE) != parameters["component_lock_path"]:
        raise ValueError("native component lock module/source mismatch")
    _bound_source(repo_root, _LOCK_PATH, _LOCK_SOURCE_SHA256)
    peer_by_owner = {item["owner"]: item for item in peers}
    for owner, commitment in zip(_OWNER_PATHS, owners):
        peer = peer_by_owner[owner]
        if (record.get("owner") not in _OWNER_PATHS
                or commitment["sha256"] != peer.get("owner_sha256")):
            raise ValueError("native guest owner digest differs from declaration")
        _bound_source(repo_root, owner, commitment["sha256"])
    _validate_loop(tree, call, _MODULES)
    for peer in peers:
        source = _bound_source(repo_root, peer["owner"], peer["owner_sha256"])
        _validate_owner(source, peer, _MODULES)
    return set()
