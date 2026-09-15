"""Route metadata helpers for JavaScript extraction."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from repomap_kg.extractors.languages.javascript_references import _is_dynamic_literal


JS_EXTENSIONS = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")
ROUTE_METHODS = frozenset(
    ("get", "post", "put", "patch", "delete", "options", "head", "all")
)
JSX_ROUTE_RE = re.compile(
    r"""<Route\b[^>]*\bpath=(?P<quote>["'])(?P<path>.+?)(?P=quote)"""
)
OBJECT_ROUTE_RE = re.compile(
    r"""\bpath\s*:\s*(?P<quote>["'])(?P<path>.+?)(?P=quote)"""
)
EXPRESS_ROUTE_RE = re.compile(
    r"""\b(?P<receiver>[A-Za-z_$][\w$]*)\.(?P<method>get|post|put|patch|delete|options|head|all|use)\s*\((?P<args>.*)"""
)
NEST_HTTP_DECORATORS = frozenset(("Get", "Post", "Put", "Patch", "Delete", "All"))
STRING_LITERAL_RE = re.compile(r"""(?P<quote>["'])(?P<value>.*?)(?P=quote)""")


def _next_route_metadata(
    relative_path: str, js_format: str
) -> dict[str, Any] | None:
    path = PurePosixPath(relative_path)
    suffix = path.suffix.lower()
    if suffix not in JS_EXTENSIONS:
        return None
    parts = path.parts
    if not parts:
        return None
    if parts[0] == "pages" and len(parts) >= 2:
        route_parts = list(parts[1:])
        route_parts[-1] = _strip_js_suffix(route_parts[-1])
        route_pattern = _route_pattern_from_segments(route_parts)
        if len(route_parts) >= 2 and route_parts[0] == "api":
            return {
                "kind": "next.api_route",
                "framework": "next",
                "route_file_kind": "api",
                "route_pattern": route_pattern,
                "router": "pages",
            }
        if route_parts[-1].startswith("_"):
            return None
        return {
            "kind": "next.page",
            "framework": "next",
            "route_file_kind": "page",
            "route_pattern": route_pattern,
            "router": "pages",
        }
    if parts[0] == "app" and len(parts) >= 2:
        filename = _strip_js_suffix(parts[-1])
        if filename not in ("page", "layout", "route", "loading", "error"):
            return None
        route_parts = list(parts[1:-1])
        route_pattern = _route_pattern_from_segments(route_parts)
        if filename == "route":
            kind = "next.app_route"
        elif filename == "page":
            kind = "next.page"
        else:
            kind = "next.component"
        return {
            "kind": kind,
            "framework": "next",
            "route_file_kind": filename,
            "route_pattern": route_pattern,
            "router": "app",
        }
    return None


def _strip_js_suffix(name: str) -> str:
    for suffix in sorted(JS_EXTENSIONS, key=len, reverse=True):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _route_pattern_from_segments(segments: list[str]) -> str:
    clean_segments = [segment for segment in segments if segment and segment != "index"]
    if not clean_segments:
        return "/"
    return "/" + "/".join(clean_segments)


def _express_route_metadata(line: str) -> dict[str, Any] | None:
    match = EXPRESS_ROUTE_RE.search(line)
    if not match:
        return None
    receiver = match.group("receiver")
    method = match.group("method").upper()
    args = _split_js_args(match.group("args"))
    route_pattern: str | None = None
    handler_args = args
    if args:
        first_literal = _whole_string_literal(args[0])
        if first_literal is not None:
            route_pattern = first_literal
            handler_args = args[1:]
    dynamic = route_pattern is None
    identifiers = [_simple_identifier(arg) for arg in handler_args]
    identifiers = [identifier for identifier in identifiers if identifier is not None]
    handler_name = identifiers[-1] if identifiers else None
    middleware_count = max(0, len(identifiers) - (1 if handler_name else 0))
    error_handler = method == "USE" and any(
        _looks_like_express_error_handler(arg) for arg in handler_args
    )
    route_name = f"{method} {route_pattern or '<dynamic>'}"
    return {
        "receiver_name": receiver,
        "route_method": method,
        "route_pattern": route_pattern,
        "route_name": route_name,
        "handler_name": handler_name,
        "middleware_count": middleware_count,
        "dynamic": dynamic,
        "dynamic_reason": "dynamic-route-path" if dynamic else None,
        "error_handler": error_handler,
        "framework": "express",
    }


def _split_js_args(raw_args: str) -> list[str]:
    args: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    depth = 0
    for char in raw_args:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in ("'", '"', "`"):
            quote = char
            current.append(char)
            continue
        if char in "([{":
            depth += 1
            current.append(char)
            continue
        if char in ")]}":
            if depth <= 0:
                break
            depth -= 1
            current.append(char)
            continue
        if char == "," and depth == 0:
            value = "".join(current).strip()
            if value:
                args.append(value)
            current = []
            continue
        current.append(char)
    value = "".join(current).strip().rstrip(";")
    if value:
        args.append(value)
    return args


def _whole_string_literal(value: str) -> str | None:
    stripped = value.strip()
    if len(stripped) < 2 or stripped[0] not in ("'", '"') or stripped[-1] != stripped[0]:
        return None
    return stripped[1:-1]


def _first_string_literal(value: str | None) -> str | None:
    if not value:
        return None
    match = STRING_LITERAL_RE.search(value)
    if not match:
        return None
    return match.group("value")


def _simple_identifier(value: str) -> str | None:
    stripped = value.strip()
    if re.fullmatch(r"[A-Za-z_$][\w$]*", stripped):
        return stripped
    return None


def _looks_like_express_error_handler(value: str) -> bool:
    compact = re.sub(r"\s+", " ", value.strip())
    return bool(
        re.search(r"\(\s*err\s*,\s*req\s*,\s*res\s*,\s*next\s*\)", compact)
        or re.search(
            r"function\s*\(\s*err\s*,\s*req\s*,\s*res\s*,\s*next\s*\)",
            compact,
        )
    )


def _nest_class_metadata(
    class_name: str, decorators: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for decorator in decorators:
        name = decorator["name"]
        args = decorator.get("args", "")
        if name == "Module":
            return {
                "kind": "nest.module",
                "module_name": class_name,
                "imports": _extract_nest_array_names(args, "imports"),
                "controllers": _extract_nest_array_names(args, "controllers"),
                "providers": _extract_nest_array_names(args, "providers"),
            }
        if name == "Controller":
            return {
                "kind": "nest.controller",
                "controller_name": class_name,
                "controller_prefix": _first_string_literal(args),
                "dynamic": _first_string_literal(args) is None
                and bool(args.strip()),
            }
        if name == "Injectable":
            return {"kind": "nest.provider", "provider_name": class_name}
    return None


def _extract_nest_array_names(args: str, key: str) -> list[str]:
    match = re.search(rf"\b{re.escape(key)}\s*:\s*\[(?P<body>[^\]]*)\]", args)
    if not match:
        return []
    names: list[str] = []
    for part in match.group("body").split(","):
        name = part.strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
            names.append(name)
    return names


def _nest_route_metadata(
    controller_name: str,
    method_name: str,
    controller_prefix: str | None,
    decorators: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for decorator in decorators:
        name = decorator["name"]
        if name not in NEST_HTTP_DECORATORS:
            continue
        route_pattern = _first_string_literal(decorator.get("args", "")) or ""
        return {
            "controller_name": controller_name,
            "method_name": method_name,
            "controller_prefix": controller_prefix,
            "route_method": name.upper() if name != "All" else "ALL",
            "route_pattern": route_pattern,
            "dynamic": route_pattern == "" and bool(decorator.get("args", "").strip()),
            "framework": "nestjs",
        }
    return None


def _route_patterns(line: str, profile: str) -> tuple[str, ...]:
    patterns: list[str] = []
    if profile == "react":
        patterns.extend(match.group("path") for match in JSX_ROUTE_RE.finditer(line))
    if profile in ("angular", "vue", "react"):
        patterns.extend(match.group("path") for match in OBJECT_ROUTE_RE.finditer(line))
    return tuple(pattern for pattern in patterns if not _is_dynamic_literal(pattern))
