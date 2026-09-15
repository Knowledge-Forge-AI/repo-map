"""Shared AST/value helpers for Python web framework extraction."""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import PurePath
from typing import Any, Mapping

from repomap_kg.extractors.languages.python_symbols import _ast_name


PYTHON_WEB_MAX_METADATA_STRING = 160
WEB_HTTP_METHODS = frozenset(
    ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD")
)
PYTHON_WEB_SECRET_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "key",
    "private_key",
    "access_key",
    "secret_key",
    "client_secret",
    "credential",
    "connection_string",
    "auth",
    "bearer",
    "session",
    "cookie",
    "database_url",
    "django_secret_key",
    "flask_secret_key",
    "sqlalchemy_database_uri",
)


def _python_web_import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                if alias.name in ("flask", "fastapi", "django"):
                    aliases[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local_name = alias.asname or alias.name
                aliases[local_name] = f"{node.module}.{alias.name}"
    return aliases


def _qualified_ast_name(node: ast.AST, aliases: Mapping[str, str]) -> str:
    raw_name = _ast_name(node)
    if not raw_name:
        return ""
    first, *rest = raw_name.split(".")
    mapped = aliases.get(first)
    if mapped is None:
        return raw_name
    return ".".join((mapped, *rest))


def _fastapi_dependencies(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: Mapping[str, str],
) -> tuple[dict[str, Any], ...]:
    dependencies: list[dict[str, Any]] = []
    defaults = [*node.args.defaults, *[item for item in node.args.kw_defaults if item]]
    for default in defaults:
        if (
            isinstance(default, ast.Call)
            and _qualified_ast_name(default.func, aliases) == "fastapi.Depends"
        ):
            target_node = _call_arg(default, 0)
            target_name = _safe_reference_name(target_node) if target_node else "unknown"
            dependencies.append(
                {
                    "node": default,
                    "name": target_name,
                    "target": target_name if target_name != "unknown" else None,
                    "kind": "depends_default",
                }
            )
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and _qualified_ast_name(child.func, aliases) == "fastapi.Depends"
        ):
            if any(item["node"] is child for item in dependencies):
                continue
            target_node = _call_arg(child, 0)
            target_name = _safe_reference_name(target_node) if target_node else "unknown"
            dependencies.append(
                {
                    "node": child,
                    "name": target_name,
                    "target": target_name if target_name != "unknown" else None,
                    "kind": "depends_call",
                }
            )
    return tuple(dependencies)


def _assignment_value(node: ast.Assign | ast.AnnAssign) -> ast.expr | None:
    if isinstance(node, ast.Assign):
        return node.value
    return node.value


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    names = []
    for target in _assignment_target_nodes(node):
        if isinstance(target, ast.Name):
            names.append(target.id)
    return names


def _assignment_target_nodes(node: ast.Assign | ast.AnnAssign) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Assign):
        return tuple(node.targets)
    return (node.target,)


def _assigns_name(node: ast.Assign | ast.AnnAssign, name: str) -> bool:
    return name in _assignment_names(node)


def _call_receiver_attr(call: ast.Call) -> tuple[str, str]:
    if isinstance(call.func, ast.Attribute):
        return _ast_name(call.func.value), call.func.attr
    return "", ""


def _call_arg(call: ast.Call, index: int) -> ast.expr | None:
    return call.args[index] if len(call.args) > index else None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _methods_from_keyword(call: ast.Call, *, default: tuple[str, ...]) -> tuple[str, ...]:
    methods = _literal_string_list(_keyword(call, "methods"))
    if not methods:
        return default
    normalized = tuple(
        method.upper()
        for method in methods
        if method.upper() in WEB_HTTP_METHODS
    )
    return normalized or default


def _route_path_metadata(
    node: ast.expr | None,
    *,
    regex: bool = False,
) -> dict[str, Any]:
    value = _literal_string(node)
    if value is None:
        return {"route_path_kind": "dynamic", "dynamic": True}
    if _looks_credentialed_url(value):
        return {"route_path_kind": "redacted", "dynamic": False, "redacted": True}
    return {
        "route_path": _bounded_metadata_string(value),
        "route_path_kind": "regex_literal" if regex else "literal",
        "dynamic": False,
    }


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_string_list(node: ast.AST | None) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return None
    values = []
    for item in node.elts:
        value = _literal_string(item)
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def _safe_reference_name(node: ast.AST | None) -> str:
    if node is None:
        return "unknown"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _bounded_metadata_string(node.value)
    name = _ast_name(node)
    return _bounded_metadata_string(name or "unknown")


def _expression_kind(node: ast.AST | None) -> str:
    if node is None:
        return "unknown"
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return "literal_string"
        if isinstance(node.value, bool):
            return "literal_bool"
        if isinstance(node.value, (int, float)):
            return "literal_number"
        if node.value is None:
            return "literal_null"
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return "collection_shape"
    if isinstance(node, ast.Call):
        return "function_call"
    if isinstance(node, (ast.Name, ast.Attribute)):
        return "traversal_reference"
    if isinstance(node, ast.BinOp):
        return "dynamic_expression"
    return "unknown"


def _is_secret_like_name(value: str) -> bool:
    normalized = value.lower()
    return any(marker in normalized for marker in PYTHON_WEB_SECRET_MARKERS)


def _value_looks_credentialed(node: ast.AST | None) -> bool:
    value = _literal_string(node)
    return bool(value and _looks_credentialed_url(value))


def _looks_credentialed_url(value: str) -> bool:
    return bool(re.search(r"^[A-Za-z][A-Za-z0-9+.-]*://[^/@\s]+:[^/@\s]+@", value))


def _looks_like_django_settings_path(relative_path: str) -> bool:
    return PurePath(relative_path.replace("\\", "/")).name == "settings.py"


def _bounded_metadata_string(value: str) -> str:
    if len(value) <= PYTHON_WEB_MAX_METADATA_STRING:
        return value
    return f"{value[:PYTHON_WEB_MAX_METADATA_STRING]}..."


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _line_slug(node: ast.AST) -> str:
    line = getattr(node, "lineno", None)
    return str(line) if isinstance(line, int) else "module"
