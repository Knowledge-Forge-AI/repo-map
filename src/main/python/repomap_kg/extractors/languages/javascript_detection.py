"""Format, profile, and module-system detection for JavaScript extraction."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from repomap_kg.extractors.languages.javascript_routes import (
    JS_EXTENSIONS,
    _next_route_metadata,
)


NEST_DECORATOR_RE = re.compile(
    r"""@(?P<name>Module|Controller|Injectable|Get|Post|Put|Patch|Delete|All|Param|Body|Query|UseGuards|UseInterceptors|UsePipes)\s*(?:\((?P<args>.*)\))?"""
)


def _detect_format(relative_path: str) -> str:
    suffix = PurePosixPath(relative_path).suffix.lower()
    if suffix in (".ts", ".mts", ".cts"):
        return "typescript"
    if suffix == ".jsx":
        return "jsx"
    if suffix == ".tsx":
        return "tsx"
    return "javascript"


def _detect_profile(relative_path: str, content: str, js_format: str) -> str:
    path = PurePosixPath(relative_path)
    lower_path = relative_path.lower()
    if _next_route_metadata(relative_path, js_format) is not None or re.search(
        r"""from\s+["']next(?:/[^"']*)?["']""", content
    ):
        return "next"
    if (
        "__tests__" in path.parts
        or ".test." in path.name
        or ".spec." in path.name
        or "@jest/globals" in content
        or re.search(r"\bdescribe\s*\(", content)
    ):
        return "jest"
    if "@nestjs/" in content or NEST_DECORATOR_RE.search(content):
        return "nestjs"
    if _has_jquery_marker(content):
        return "jquery"
    if _is_node_entrypoint(relative_path, content):
        return "node"
    if _has_express_marker(content):
        return "express"
    if "report" in lower_path or "coverage" in path.parts:
        return "test_report_asset"
    if ".repomap/source-artifacts/" in lower_path or "_files/" in lower_path:
        return "saved_page_asset"
    if "@angular/" in content or "@Component" in content or "Routes" in content:
        return "angular"
    if "from 'react'" in content or 'from "react"' in content or js_format in (
        "jsx",
        "tsx",
    ):
        return "react"
    if "from 'vue'" in content or 'from "vue"' in content or "defineComponent" in content:
        return "vue"
    if path.name.endswith((".config.js", ".config.ts", ".config.cjs", ".config.mjs")):
        return "node_config"
    if lower_path.startswith("public/") or "/public/" in lower_path:
        return "frontend_asset"
    if js_format == "typescript":
        return "generic_typescript"
    return "generic_javascript"


def _detect_module_system(content: str) -> str:
    has_esm = bool(re.search(r"^\s*(?:import|export)\b", content, re.MULTILINE))
    has_commonjs = (
        "require(" in content or "module.exports" in content or "exports." in content
    )
    if has_esm and has_commonjs:
        return "mixed"
    if has_esm:
        return "esm"
    if has_commonjs:
        return "commonjs"
    return "script"


def _has_express_marker(content: str) -> bool:
    return bool(
        re.search(r"""require\s*\(\s*["']express["']\s*\)""", content)
        or re.search(r"""from\s+["']express["']""", content)
        or "express()" in content
        or "express.Router" in content
    )


def _has_jquery_marker(content: str) -> bool:
    return bool(
        "jQuery(" in content
        or "$.ajax" in content
        or "$.get" in content
        or "$.post" in content
        or "$.fn." in content
        or re.search(
            r"""\$\([^)]*["'][^"']+["'][^)]*\)\.(?:on|click|submit|change|ready)""",
            content,
        )
    )


def _is_node_entrypoint(relative_path: str, content: str) -> bool:
    path = PurePosixPath(relative_path)
    stem = path.stem.lower()
    if stem not in ("server", "app", "index", "main"):
        return False
    if path.suffix.lower() not in JS_EXTENSIONS:
        return False
    return bool(
        re.search(r"""require\s*\(\s*["']node:""", content)
        or re.search(r"""from\s+["']node:""", content)
        or "process.env." in content
        or "import.meta.env." in content
        or "module.exports" in content
        or "exports." in content
    )


def _is_jest_profile(profile: str, relative_path: str, content: str) -> bool:
    return (
        profile == "jest"
        or _detect_profile(relative_path, content, _detect_format(relative_path)) == "jest"
    )
