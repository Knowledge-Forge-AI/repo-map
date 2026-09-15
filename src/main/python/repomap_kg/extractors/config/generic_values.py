"""Shared value and path helpers for structured config extraction."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from repomap_kg.extractors.config.format_contracts import YAML_SIMPLE_IMAGE_PATTERN
from repomap_kg.extractors.config.paths import _pointer_segments

SECRET_PRONE_KEYS = (
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
    "kubeconfig",
    "service_account",
    "dockerconfigjson",
    "registry_password",
    "connection_string",
    "jdbc_url",
    "datasource_password",
    "grafana_api_key",
    "arq_encryption_key",
    "arq_password",
    "arq_destination_password",
    "securejsondata",
)
PATH_KEY_MARKERS = ("path", "file", "cwd")
STABLE_ARRAY_MEMBER_KEYS = ("name", "id", "key", "project")
DYNAMIC_MARKERS = ("${", "$(", "{{", "}}", "*", "?", "~")


def _value_type(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    return "number"


def _yaml_documents(value: Any, *, document_count: int) -> tuple[Any, ...]:
    if (
        document_count > 1
        and isinstance(value, dict)
        and isinstance(value.get("documents"), dict)
    ):
        documents = value["documents"]
        return tuple(documents[str(index)] for index in range(document_count))
    return (value,)


def _safe_value_summary(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) <= 120 and all(character.isprintable() for character in value):
            return value
        return f"<string:{len(value)}>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _looks_like_secret_scalar(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if "-----BEGIN " in stripped and "PRIVATE KEY-----" in stripped:
        return True
    if len(stripped) >= 32 and re.fullmatch(r"[A-Za-z0-9_./+=:-]+", stripped):
        markers = ("token", "secret", "password", "key")
        return any(marker in stripped.lower() for marker in markers)
    return False


def _is_secret_pointer(pointer: str) -> bool:
    return any(_is_secret_key(segment) for segment in _pointer_segments(pointer))


def _is_secret_key(key: str) -> bool:
    normalized = _normalized_key(key)
    squashed = re.sub(r"[^0-9a-z]", "", normalized)
    return any(marker.replace("_", "") in squashed for marker in SECRET_PRONE_KEYS)


def _normalized_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


class _StableArrayMember:
    def __init__(self, *, key: str, segment: str, value: dict[str, Any]) -> None:
        self.key = key
        self.segment = segment
        self.value = value


def _stable_array_members(value: list[Any]) -> tuple[_StableArrayMember, ...]:
    members: list[_StableArrayMember] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return ()
        stable_key = _stable_member_key(item)
        if stable_key is None:
            return ()
        stable_value = item[stable_key]
        summary = _safe_value_summary(stable_value)
        if summary is None or isinstance(summary, bool):
            return ()
        segment = str(summary)
        if segment in seen:
            return ()
        seen.add(segment)
        members.append(
            _StableArrayMember(key=stable_key, segment=segment, value=item)
        )
    return tuple(members)


def _stable_member_key(value: dict[str, Any]) -> str | None:
    normalized_keys = {_normalized_key(str(key)): str(key) for key in value}
    for candidate in STABLE_ARRAY_MEMBER_KEYS:
        key = normalized_keys.get(candidate)
        if key is not None and not _is_secret_key(key):
            return key
    return None


def _is_url(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme in ("http", "https"):
        return bool(parsed.netloc)
    if parsed.scheme == "mailto":
        return bool(parsed.path)
    return False


def _looks_like_container_image(value: str) -> bool:
    if _is_url(value) or value.startswith(("./", "../", "/", "$", "~")):
        return False
    return bool(YAML_SIMPLE_IMAGE_PATTERN.match(value)) and (
        "/" in value or ":" in value or "@" in value
    )


def _is_dynamic_value(value: str) -> bool:
    return any(marker in value for marker in DYNAMIC_MARKERS)


def _looks_like_file_key(key_normalized: str, value: str) -> bool:
    if _is_url(value):
        return False
    if value.startswith(("./", "../", "/", "${", "~")):
        return True
    return "/" in value and any(marker in key_normalized for marker in PATH_KEY_MARKERS)


def _resolve_repo_path(relative_path: str, value: str) -> str | None:
    base = PurePosixPath(relative_path.replace("\\", "/")).parent
    return _normalize_repo_path(str(base / value))


def _normalize_repo_path(value: str) -> str | None:
    parts: list[str] = []
    for part in value.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        return "."
    return "/".join(parts)


def _document_role(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    normalized_name = _normalized_key(path.name)
    if (
        path.suffix in (".plist", ".xml")
        and "chrome" in normalized_name
        and "policy" in normalized_name
    ):
        return "chrome-policy"
    if path.suffix == ".plist":
        return "plist-config"
    if path.name == "config.json" and "mcp" in path.parts:
        return "mcp-config"
    if path.suffix == ".jsonl":
        return "log"
    return "config"
