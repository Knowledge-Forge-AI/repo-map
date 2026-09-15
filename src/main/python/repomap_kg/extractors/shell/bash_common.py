"""Shared Bash extractor metadata and redaction helpers."""

from __future__ import annotations

import re
import shlex
from typing import Any

from repomap_kg.extractors.shared.redaction import (
    secret_name_redaction_reason,
    secret_value_redaction_reason,
)


EXTRACTOR = "repo-bash"
ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
ARRAY_ASSIGNMENT_RE = re.compile(
    r"^(?:(?P<declaration>declare|local|readonly|typeset)\s+(?P<flags>(?:-[A-Za-z]+\s+)*)?)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<operation>\+=|=)\s*\((?P<body>.*)\)\s*$"
)
COMMAND_SUB_RE = re.compile(r"\$\(")
BACKTICK_SUB_RE = re.compile(r"`[^`]+`")
SECRET_NAME_PARTS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "key",
        "credential",
        "apikey",
        "pat",
        "authorization",
        "auth",
    }
)
SENSITIVE_ENV_NAMES = frozenset(
    {
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "GITHUB_TOKEN",
        "GITLAB_TOKEN",
        "NPM_TOKEN",
        "PYPI_TOKEN",
        "DOCKER_PASSWORD",
        "SSH_AUTH_SOCK",
    }
)


def bash_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "dialect": "bash",
        "static_only": True,
        "shell_executed": False,
    }
    payload.update(metadata)
    return payload


def redaction_for_name(name: str) -> tuple[bool, str]:
    reason = secret_name_redaction_reason(
        name,
        SECRET_NAME_PARTS,
        exact_names=SENSITIVE_ENV_NAMES,
        exact_reason="sensitive-env-name",
    )
    return bool(reason), reason


def redaction_for_value(value: str) -> tuple[bool, str]:
    reason = secret_value_redaction_reason(value, SECRET_NAME_PARTS)
    return bool(reason), reason


def is_dynamic_value(value: str) -> bool:
    return value.startswith("$") or "${" in value or "`" in value or "$(" in value


def split_words(raw_line: str) -> list[str]:
    try:
        return shlex.split(raw_line, comments=False, posix=True)
    except ValueError:
        return []


def value_kind(value: str | None) -> str:
    if value is None:
        return "omitted"
    if COMMAND_SUB_RE.search(value) or BACKTICK_SUB_RE.search(value):
        return "dynamic"
    if "$" in value:
        return "dynamic"
    return "static"


def safe_raw_line(raw_line: str, variable: str, redacted: bool) -> str:
    stripped = raw_line.strip()
    if not redacted:
        return stripped
    return re.sub(
        rf"({re.escape(variable)}=).*",
        rf"\1[redacted]",
        stripped,
        count=1,
    )
