"""JavaScript reference target and safe-summary helpers."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit, urlunsplit

from repomap_kg.graph.keys import (
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
)


LOCAL_RESOLUTION_EXTENSIONS = (
    "",
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".ts",
    ".mts",
    ".cts",
    ".tsx",
    ".json",
    ".css",
    ".html",
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
    "apitoken",
    "authtoken",
    "bearertoken",
    "sessiontoken",
    "csrftoken",
    "xsrftoken",
    "firebaseapikey",
    "sentrydsn",
    "stripesecret",
    "npmtoken",
    "githubtoken",
    "jesttoken",
    "angulartoken",
    "vuetoken",
)


def _specifier_target(
    relative_path: str,
    specifier: str,
    repository_paths: frozenset[str] | None,
) -> tuple[str, str]:
    sanitized = _sanitize_url(specifier)
    if _is_dynamic_literal(specifier):
        return dynamic_key("js.reference", "dynamic-specifier"), "dynamic"
    scheme = urlsplit(sanitized).scheme.lower()
    if scheme in REFERENCE_SCHEMES:
        return external_url_key(sanitized), "external-url"
    if scheme:
        return unknown_key("js.reference", "unsupported-scheme"), "unsupported-scheme"
    if specifier.startswith("~") or "*" in specifier:
        return dynamic_key("js.reference", "dynamic-path"), "dynamic"
    if specifier.startswith("/"):
        return external_key("file", "absolute-js-reference"), "absolute-file"
    if specifier.startswith("."):
        target = _local_path_target(relative_path, specifier, repository_paths)
        reason = "repo-escaping" if target.startswith("unknown:file:") else "repo-local"
        return target, reason
    clean_specifier = specifier.split("#", 1)[0].split("?", 1)[0]
    if PurePosixPath(clean_specifier).suffix and not specifier.startswith("@"):
        return (
            _local_path_target(relative_path, f"./{specifier}", repository_paths),
            "repo-local",
        )
    if "/" in specifier and not specifier.startswith("@"):
        return external_key("js-package", _package_name(specifier)), "external-js-package"
    if specifier:
        return external_key("js-package", _package_name(specifier)), "external-js-package"
    return unknown_key("js.reference", "empty-specifier"), "unknown"


def _local_path_target(
    relative_path: str,
    raw_path: str,
    repository_paths: frozenset[str] | None,
) -> str:
    clean_path = raw_path.split("#", 1)[0].split("?", 1)[0]
    base = PurePosixPath(relative_path).parent
    normalized = base.joinpath(clean_path)
    parts: list[str] = []
    for part in normalized.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return unknown_key("file", "repo-escaping-js-reference")
            parts.pop()
            continue
        parts.append(part)
    candidate = PurePosixPath(*parts).as_posix()
    if repository_paths is None:
        return file_key(candidate)
    for possible in _candidate_paths(candidate):
        if possible in repository_paths:
            return file_key(possible)
    return file_key(candidate)


def _candidate_paths(candidate: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for extension in LOCAL_RESOLUTION_EXTENSIONS:
        candidates.append(candidate + extension)
    for extension in (".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"):
        candidates.append(f"{candidate}/index{extension}")
    return tuple(dict.fromkeys(candidates))


def _package_name(specifier: str) -> str:
    if specifier.startswith("@"):
        parts = specifier.split("/")
        if len(parts) >= 2:
            return "/".join(parts[:2])
    return specifier.split("/", 1)[0]


def _literal_type(value: str) -> str:
    stripped = value.strip().rstrip(";")
    if not stripped:
        return "unknown"
    if stripped[0:1] in ("'", '"', "`"):
        return "string"
    if stripped in ("true", "false"):
        return "boolean"
    if stripped == "null":
        return "null"
    if re.fullmatch(r"-?\d+", stripped):
        return "integer"
    if re.fullmatch(r"-?\d+\.\d+", stripped):
        return "decimal"
    if stripped.startswith("["):
        return "array"
    if stripped.startswith("{"):
        return "object"
    if "=>" in stripped or stripped.startswith("function"):
        return "function"
    return "expression"


def _is_dynamic_literal(value: str) -> bool:
    return "${" in value or "*" in value or value.startswith("`") or value.endswith("`")


def _is_secret_prone(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return any(marker.replace("_", "") in normalized for marker in SECRET_MARKERS)


def _looks_like_secret_literal(value: str) -> bool:
    if "PRIVATE KEY" in value or "BEGIN " in value and " KEY" in value:
        return True
    return bool(re.search(r"[A-Za-z0-9_-]{32,}", value)) and any(
        marker in value.lower() for marker in ("token", "secret", "key")
    )


def _safe_summary(value: str | None, *, max_length: int = 120) -> str | None:
    if value is None:
        return None
    summary = value.strip()
    if _is_secret_prone(summary):
        return "REDACTED"
    if len(summary) > max_length:
        return summary[: max_length - 3] + "..."
    return summary


def _sanitize_url(raw_url: str) -> str:
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return raw_url
    if parsed.scheme.lower() not in REFERENCE_SCHEMES:
        return raw_url
    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    query_parts: list[str] = []
    for part in parsed.query.split("&"):
        if not part:
            continue
        key, separator, value = part.partition("=")
        if _is_secret_prone(key) or _is_secret_prone(value):
            query_parts.append(f"{key}=REDACTED" if separator else key)
        else:
            query_parts.append(part)
    return urlunsplit(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            "&".join(query_parts),
            parsed.fragment,
        )
    )
