"""Policy constants and primitive helpers for GitHub API ingestion."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from repomap_kg import __version__


EXTRACTOR = "github-api-fixture-ingestion"
EXTRACTOR_VERSION = "0.1.0"
DEFAULT_GITHUB_API_BASE_URL = "https://api.github.com"
DEFAULT_GITHUB_USER_AGENT = f"repomap-kg/{__version__}"
ALLOWED_SOURCE_TYPES = frozenset({"api.rest"})
ALLOWED_GITHUB_API_SOURCE_CLASSES = frozenset({"api.github.repository"})
ALLOWED_POLICY_STATUSES = frozenset({"allowed", "allowed_with_limits"})
ALLOWED_REPOSITORY_VISIBILITIES = frozenset({"public", "private", "internal"})
ALLOWED_ACQUISITION_TRANSPORTS = frozenset({"fixture", "github_public_rest"})
ALLOWED_CREDENTIAL_MODES = frozenset(
    {"none_public_readonly", "pat_readonly_ref", "github_app_installation_ref"}
)
ALLOWED_CREDENTIAL_REF_PREFIXES = (
    "local_secret_ref:",
    "os_keychain_ref:",
    "env_ref:",
)
ALLOWED_ENDPOINT_PATHS = {
    "/repos/{owner}/{repo}": "repository_metadata",
    "/repos/{owner}/{repo}/issues": "issues",
    "/repos/{owner}/{repo}/pulls": "pull_requests",
    "/repos/{owner}/{repo}/releases": "releases",
    "/repos/{owner}/{repo}/actions/runs": "actions",
}
GITHUB_ENDPOINT_KINDS = {
    "repository": "github.repository",
    "issues": "github.issue",
    "pulls": "github.pull_request",
    "releases": "github.release",
    "actions_runs": "github.workflow_run",
}
OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SECRET_MARKERS = frozenset(
    {
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
        "authorization",
        "set-cookie",
        "clone_url",
        "ssh_url",
        "git_url",
        "download_url",
        "archive_url",
        "tarball_url",
        "zipball_url",
        "patch_url",
        "diff_url",
        "logs_url",
        "artifacts_url",
    }
)
SENSITIVE_URL_MARKERS = (
    "token=",
    "access_token=",
    "authorization=",
    "signature=",
    "sig=",
    "X-Amz-Signature=",
)
RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-used",
    "x-ratelimit-reset",
    "x-ratelimit-resource",
)
BODY_FIELDS = frozenset({"body"})


class GitHubApiPolicyError(ValueError):
    """Raised when GitHub API fixture acquisition is not allowed and bounded."""


def validate_no_auth_headers(headers: Mapping[str, str]) -> None:
    for key in headers:
        if key.lower() in {"authorization", "cookie", "set-cookie"}:
            raise GitHubApiPolicyError("GitHub REST transport must not send auth headers")


def header_mapping(headers: Any) -> dict[str, str]:
    if hasattr(headers, "items"):
        items = headers.items()
    else:
        items = headers or ()
    return {str(key).lower(): str(value) for key, value in items}


def content_type_from_headers(headers: Mapping[str, str]) -> str:
    return headers.get("content-type", "application/octet-stream").split(";", 1)[0]


def rate_limit_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        name: headers[name]
        for name in RATE_LIMIT_HEADERS
        if name in headers
    }


def parse_json_response(body: bytes, endpoint_name: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GitHubApiPolicyError(
            f"endpoint {endpoint_name} returned invalid JSON"
        ) from error


def count_response_items(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        workflow_runs = payload.get("workflow_runs")
        if isinstance(workflow_runs, list):
            return len(workflow_runs)
        return 1
    return 1


def redact_github_value(value: Any, *, key: str | None = None) -> Any:
    if key is not None and key.lower() in BODY_FIELDS:
        body = "" if value is None else str(value)
        return {
            "body_present": bool(body),
            "body_length": len(body),
            "body_sha256": sha256_text(body) if body else "",
            "body_redacted": True,
        }
    if key is not None and is_secret_key(key):
        return {
            "redacted": True,
            "redaction_reason": "secret_key",
            "literal_type": literal_type(value),
        }
    if isinstance(value, str) and contains_sensitive_url_marker(value):
        return {
            "redacted": True,
            "redaction_reason": "sensitive_url",
            "literal_type": "string",
        }
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_github_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_github_value(item) for item in value]
    return value


def is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(marker in normalized for marker in SECRET_MARKERS)


def contains_sensitive_url_marker(value: str) -> bool:
    # Inspect only HTTP(S) authority, including malformed host/port text.
    # A lexical boundary avoids parser errors leaking credentialed bad URLs.
    authority = re.match(r"https?://([^/?#]*)", value.lstrip(), re.IGNORECASE)
    if authority is not None and "@" in authority.group(1):
        return True
    return value.startswith("http") and any(
        marker.lower() in value.lower() for marker in SENSITIVE_URL_MARKERS
    )


def literal_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def github_artifact_name(endpoint_name: str) -> str:
    return f"{endpoint_name.replace('_', '-')}.json"


def required_table(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise GitHubApiPolicyError(f"{key} table is required")
    return value


def required_endpoint_list(payload: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    endpoints = payload.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise GitHubApiPolicyError("at least one [[endpoints]] entry is required")
    for endpoint in endpoints:
        if not isinstance(endpoint, Mapping):
            raise GitHubApiPolicyError("endpoint entries must be tables")
    return endpoints


def required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GitHubApiPolicyError(f"{key} is required")
    return value


def optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GitHubApiPolicyError(f"{key} must be a non-empty string")
    return value


def required_positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise GitHubApiPolicyError(f"{key} must be a positive integer")
    return value


def optional_positive_int(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: int,
) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise GitHubApiPolicyError(f"{key} must be a positive integer")
    return value


def required_nonnegative_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GitHubApiPolicyError(f"{key} must be a non-negative integer")
    return value


def required_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise GitHubApiPolicyError(f"{key} must be a boolean")
    return value


def optional_bool(payload: Mapping[str, Any], key: str, *, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise GitHubApiPolicyError(f"{key} must be a boolean")
    return value


def string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GitHubApiPolicyError("expected a list of strings")
    return tuple(value)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(payload: str) -> str:
    return sha256_bytes(payload.encode("utf-8"))


def sha256_json(payload: Any) -> str:
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def ensure_contained(path: Path, parent: Path, label: str) -> None:
    if not is_contained(path, parent):
        raise GitHubApiPolicyError(f"{label} escapes its configured root")


def is_contained(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
