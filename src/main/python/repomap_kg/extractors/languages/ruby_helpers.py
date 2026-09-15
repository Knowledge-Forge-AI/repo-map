"""Shared scanner and reference helpers for Ruby extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit, urlunsplit

from repomap_kg.graph.keys import (
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
)


REFERENCE_SCHEMES = frozenset(("http", "https", "mailto"))
SECRET_MARKERS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "access_key",
    "refresh_token",
    "bearer",
    "auth",
    "client_secret",
    "secret_key",
    "access_token",
    "id_token",
    "session",
    "cookie",
    "connection_string",
    "jdbc_url",
    "datasource_password",
    "rack_secret",
    "session_secret",
    "sinatra_secret",
    "hanami_secret",
    "vagrant_cloud_token",
    "vagrant_token",
    "gem_credentials",
    "rubygems_api_key",
)


@dataclass
class _Scope:
    kind: str
    name: str
    canonical_key: str | None = None
    test_case_key: str | None = None
    route_key: str | None = None


def _strip_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in ("'", '"'):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if char == "#" and quote is None:
            return line[:index]
    return line


def _dynamic_reasons(line: str) -> tuple[str, ...]:
    reasons: list[str] = []
    if "#{" in line:
        reasons.append("interpolation")
    for token in (
        "define_method",
        "send",
        "class_eval",
        "instance_eval",
        "eval",
        "method_missing",
    ):
        if re.search(rf"\b{re.escape(token)}\b", line):
            reasons.append(token)
    return tuple(dict.fromkeys(reasons))


def _qualify_name(name: str, stack: list[_Scope]) -> str:
    if "::" in name:
        return name
    owner = _current_owner(stack)
    return f"{owner}::{name}" if owner else name


def _current_owner(stack: list[_Scope]) -> str | None:
    for scope in reversed(stack):
        if scope.kind in ("class", "module"):
            return scope.name
    return None


def _current_source_key(stack: list[_Scope]) -> str | None:
    for scope in reversed(stack):
        if scope.canonical_key:
            return scope.canonical_key
    return None


def _current_route_key(stack: list[_Scope]) -> str | None:
    for scope in reversed(stack):
        if scope.route_key:
            return scope.route_key
    return None


def _current_test_case_key(stack: list[_Scope]) -> str | None:
    for scope in reversed(stack):
        if scope.test_case_key:
            return scope.test_case_key
    return None


def _owner_key_for_scope(owner: str, stack: list[_Scope]) -> str | None:
    for scope in reversed(stack):
        if scope.name == owner and scope.canonical_key:
            return scope.canonical_key
    return None


def _method_owner(
    method_token: str,
    stack: list[_Scope],
) -> tuple[str | None, str | None, bool]:
    if method_token.startswith("self."):
        return _current_owner(stack), method_token.split(".", 1)[1], True
    if "." in method_token:
        owner, method_name = method_token.rsplit(".", 1)
        return owner, method_name, True
    return _current_owner(stack), method_token, False


def _pop_scope(stack: list[_Scope]) -> None:
    if stack:
        stack.pop()


def _opens_block(line: str) -> bool:
    if line.startswith(("module ", "class ", "def ")):
        return False
    return bool(re.search(r"\bdo\b", line)) or line.endswith(" do")


def _is_minitest_class(superclass: str | None, profile: str) -> bool:
    return superclass == "Minitest::Test" or profile == "minitest" and superclass is not None


def _looks_like_route_profile(profile: str, content: str, relative_path: str) -> bool:
    if profile in ("sinatra", "hanami"):
        return True
    if relative_path == "config/routes.rb":
        return True
    lowered = content.lower()
    return "sinatra" in lowered or "hanami" in lowered


def _is_dynamic_literal(value: str) -> bool:
    return "#{" in value


def _require_target(
    relative_path: str,
    require_form: str,
    raw_value: str,
    repository_paths: frozenset[str] | None,
) -> tuple[str, str]:
    if _is_dynamic_literal(raw_value):
        return dynamic_key("ruby.reference", "interpolated-require"), "dynamic"
    if require_form == "require_relative":
        candidate = _normalize_relative_path(
            relative_path,
            raw_value,
            default_suffix=".rb",
        )
        if candidate is None:
            return unknown_key("file", "repo-escaping-ruby-reference"), "repo-escaping"
        if repository_paths is None or candidate in repository_paths:
            return file_key(candidate), "repo-local"
        return file_key(candidate), "repo-local-candidate"
    if raw_value.startswith(("./", "../")):
        candidate = _normalize_relative_path(
            relative_path,
            raw_value,
            default_suffix=".rb",
        )
        if candidate is None:
            return unknown_key("file", "repo-escaping-ruby-reference"), "repo-escaping"
        return file_key(candidate), "repo-local"
    return external_key("ruby.require", raw_value), "external-ruby-require"


def _normalize_relative_path(
    relative_path: str,
    raw_value: str,
    *,
    default_suffix: str | None = None,
) -> str | None:
    base = PurePosixPath(relative_path).parent
    candidate = PurePosixPath(raw_value)
    if not candidate.suffix and default_suffix:
        candidate = candidate.with_suffix(default_suffix)
    normalized = _normalize_posix(base / candidate)
    if normalized is None or normalized.startswith("../"):
        return None
    return normalized


def _normalize_posix(path: PurePosixPath) -> str | None:
    parts: list[str] = []
    for part in path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _path_target(raw_path: str, repository_paths: frozenset[str] | None) -> str:
    if _is_dynamic_literal(raw_path) or raw_path.startswith(("~", "$")) or "*" in raw_path:
        return dynamic_key("ruby.reference", "dynamic-path")
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw_path):
        scheme = raw_path.split(":", 1)[0].lower()
        if scheme in REFERENCE_SCHEMES:
            return external_url_key(_sanitize_url(raw_path))
        return unknown_key("ruby.reference", "unsupported-scheme")
    path = PurePosixPath(raw_path)
    if path.is_absolute():
        return external_key("file", "absolute-ruby-reference")
    normalized = _normalize_posix(path)
    if normalized is None:
        return unknown_key("file", "repo-escaping-ruby-reference")
    if not normalized:
        return unknown_key("file", "repository-root-ruby-reference")
    if repository_paths is None or normalized in repository_paths:
        return file_key(normalized)
    return file_key(normalized)


def _sanitize_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "about:invalid"
    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    query = "&".join(
        f"{key}=REDACTED" if _is_secret_prone(key) else pair
        for pair in parsed.query.split("&")
        if pair
        for key in [pair.split("=", 1)[0]]
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))


def _safe_summary(value: str | None) -> str | None:
    if value is None:
        return None
    if _is_secret_prone(value):
        return "REDACTED"
    value = value.strip()
    if len(value) > 120:
        return value[:117] + "..."
    return value


def _literal_type(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith(("'", '"')):
        return "string"
    if stripped in ("true", "false"):
        return "boolean"
    if re.fullmatch(r"-?\d+", stripped):
        return "integer"
    if stripped.startswith("["):
        return "array"
    if stripped.startswith("{"):
        return "hash"
    return "expression"


def _first_literal(text: str) -> str | None:
    match = re.search(r'(["\'])(.*?)\1', text)
    if not match:
        return None
    return match.group(2)


def _is_secret_prone(value: str | None) -> bool:
    if not value:
        return False
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower())
    return any(marker in normalized for marker in SECRET_MARKERS)
