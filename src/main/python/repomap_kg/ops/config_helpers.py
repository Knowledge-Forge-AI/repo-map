"""Helper records and scalar utilities for RepoMap ops config parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

KNOWN_TOP_LEVEL_SECTIONS = frozenset(
    (
        "schema_version",
        "service",
        "postgres",
        "runtime",
        "graphs",
        "server_memory",
        "sources",
    )
)
KNOWN_SERVICE_FIELDS = frozenset(("mode", "mcp_transport", "log_level"))
KNOWN_POSTGRES_FIELDS = frozenset(
    ("host", "port", "database", "user", "password_env", "password_file", "password")
)
KNOWN_RUNTIME_FIELDS = frozenset(
    ("container_runtime", "postgres_host_port", "server_host_port", "bind_host", "postgres")
)
KNOWN_RUNTIME_POSTGRES_FIELDS = frozenset(
    ("direct_host_port_enabled", "host_port", "bind_host")
)
KNOWN_GRAPH_FIELDS = frozenset(
    (
        "id",
        "name",
        "root_path",
        "repository_name",
        "database",
        "privacy",
        "enabled",
        "mcp_visible",
        "extractor_profile",
        "refresh_policy",
        "exclude_paths",
        "source_bindings",
    )
)
KNOWN_SERVER_MEMORY_FIELDS = frozenset(("enabled", "path", "mode"))
SECRET_KEY_PARTS = (
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
)
REDACTED = "[REDACTED]"
PRIVATE_PRIVACY = frozenset(
    ("private-ops", "private-memory", "private-config", "sensitive-local")
)
PRIVATE_DATABASE_DISPLAY = "[private-database]"
PRIVATE_PATH_DISPLAY = "[private-path]"
PRIVATE_ROOT_DISPLAY = "[private-root]"
PRIVATE_SOURCE_DISPLAY = "[private-source]"


@dataclass(frozen=True)
class OpsConfigDiagnostic:
    severity: str
    code: str
    path: str
    message: str

    def to_jsonable(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": redact_text(self.message),
        }


def unknown_top_level_diagnostics(
    payload: Mapping[str, Any],
    *,
    source: str | None = None,
) -> list[OpsConfigDiagnostic]:
    diagnostics = []
    for key in sorted(payload):
        if key not in KNOWN_TOP_LEVEL_SECTIONS:
            path = f"{source}:{key}" if source else key
            location = f" in {source}" if source else ""
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "unknown-top-level-section",
                    path,
                    f"unknown top-level section {key!r}{location} is ignored",
                )
            )
    return diagnostics


def unknown_file_field_diagnostics(
    payload: Mapping[str, Any],
    source: str,
) -> list[OpsConfigDiagnostic]:
    diagnostics: list[OpsConfigDiagnostic] = []
    section_specs: tuple[tuple[str, frozenset[str]], ...] = (
        ("service", KNOWN_SERVICE_FIELDS),
        ("postgres", KNOWN_POSTGRES_FIELDS),
        ("runtime", KNOWN_RUNTIME_FIELDS),
        ("server_memory", KNOWN_SERVER_MEMORY_FIELDS),
    )
    for section_name, known_fields in section_specs:
        section = payload.get(section_name)
        if isinstance(section, dict):
            diagnostics.extend(
                unknown_field_diagnostics(
                    section,
                    known_fields,
                    f"{source}:{section_name}",
                )
            )
    graphs = payload.get("graphs")
    if isinstance(graphs, list):
        for index, graph in enumerate(graphs):
            if isinstance(graph, dict):
                diagnostics.extend(
                    unknown_field_diagnostics(
                        graph,
                        KNOWN_GRAPH_FIELDS,
                        f"{source}:graphs[{index}]",
                    )
                )
    sources = payload.get("sources")
    if isinstance(sources, dict):
        diagnostics.extend(
            unknown_field_diagnostics(
                sources,
                frozenset(("feed", "github", "api")),
                f"{source}:sources",
            )
        )
    return diagnostics


def unknown_field_diagnostics(
    payload: Mapping[str, Any],
    known_fields: frozenset[str],
    path: str,
) -> list[OpsConfigDiagnostic]:
    diagnostics = []
    path_for_code = path.rsplit(":", 1)[-1]
    path_code = re.sub(r"\[\d+\]", "", path_for_code).replace(".", "-")
    for key in sorted(payload):
        if key not in known_fields:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    f"unknown-{path_code}-field",
                    f"{path}.{key}",
                    f"unknown field {key!r} in {path} is ignored",
                )
            )
    return diagnostics


def require_mapping(
    payload: Any,
    path: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> Mapping[str, Any]:
    if payload is None:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error", "missing-section", path, f"{path} section is required"
            )
        )
        return {}
    if not isinstance(payload, dict):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error", "invalid-section", path, f"{path} must be a table"
            )
        )
        return {}
    return payload


def required_text(
    payload: Mapping[str, Any],
    key: str,
    path: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "missing-required-field",
                path,
                f"{path} is required and must be a non-empty string",
            )
        )
        return None
    return value


def optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def optional_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def required_int(
    payload: Mapping[str, Any],
    key: str,
    path: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> int | None:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "missing-required-field",
                path,
                f"{path} is required and must be an integer",
            )
        )
        return None
    return value


def required_bool(
    payload: Mapping[str, Any],
    key: str,
    path: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> bool | None:
    value = payload.get(key)
    if not isinstance(value, bool):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "missing-required-field",
                path,
                f"{path} is required and must be a boolean",
            )
        )
        return None
    return value


def expand_user_path(value: str) -> str:
    if value.startswith("~"):
        return str(Path(value).expanduser())
    return value


def redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: redact_value(key, value) for key, value in payload.items()}


def redact_value(key: str, value: Any) -> Any:
    if is_secret_key(key) or (isinstance(value, str) and is_credentialed_url(value)):
        return REDACTED
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(key, item) for item in value]
    return value


def redact_text(value: str | None) -> str:
    if not value:
        return ""
    result = value
    credentialed_url = re.compile(r"https?://[^\\s/@:]+:[^\\s/@]+@[^\\s]+")
    result = credentialed_url.sub(REDACTED, result)
    assignment = re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)"
        r"\\s*[:=]\\s*[^\\s,;]+"
    )
    result = assignment.sub(lambda match: match.group(1) + "=" + REDACTED, result)
    return result


def is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SECRET_KEY_PARTS)


def is_credentialed_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(parsed.scheme and parsed.netloc and "@" in parsed.netloc)


def format_counts(counts: Mapping[str, int]) -> str:
    if not counts:
        return "none"
    return " ".join(f"{key}={counts[key]}" for key in sorted(counts))


def bool_text(value: bool) -> str:
    return "true" if value else "false"
