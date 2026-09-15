"""Shared Zsh extractor metadata, redaction, and lexical helpers."""

from __future__ import annotations

import re
from pathlib import Path
import shlex
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shared.observations import (
    secret_like_observation as build_secret_like_observation,
)
from repomap_kg.extractors.shared.redaction import (
    secret_name_redaction_reason,
    secret_value_redaction_reason,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


EXTRACTOR = "repo-zsh"
ZSH_STARTUP_FILENAMES = frozenset(
    {".zshenv", ".zprofile", ".zshrc", ".zlogin", ".zlogout"}
)
DYNAMIC_TARGET_CHARS = frozenset("$`*?[")
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
PROMPT_VARIABLES = frozenset(
    {"PROMPT", "PROMPT2", "PROMPT3", "PROMPT4", "RPROMPT", "PS1", "PS2", "PS3", "PS4"}
)
PLUGIN_MANAGER_NAMES = frozenset({"sheldon", "zinit", "antigen", "antidote", "zplug"})


def secret_like_observation(
    relative_path: str,
    line_number: int,
    name: str,
    secret_source: str,
    reason: str,
) -> RawObservation:
    return build_secret_like_observation(
        relative_path=relative_path,
        line_number=line_number,
        name=name,
        secret_source=secret_source,
        reason=reason,
        source_prefix="zsh",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata_builder=zsh_metadata,
        slugger=slug,
    )


def configuration_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "configuration_intent": True,
        "runtime_state_known": False,
        "plugin_loaded": False,
        "plugin_installed": False,
        "network_called": False,
        "completion_loaded": False,
        "compinit_executed": False,
        "module_loaded": False,
        "binding_applied": False,
        "autoload_executed": False,
        "function_loaded": False,
    }
    payload.update(metadata)
    return payload


def syntax_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    payload = configuration_metadata(
        {
            "syntax_only": True,
            "value_expanded": False,
            "glob_expanded": False,
            "filesystem_checked": False,
            "target_count_known": False,
            "command_executed": False,
            "host_mutation_proven": False,
            "network_called": False,
            "package_manager_executed": False,
            "file_opened": False,
            "file_mutated": False,
            "plugin_loaded": False,
            "plugin_installed": False,
        }
    )
    payload.update(metadata)
    return payload


def side_effect_metadata(relative_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "configuration_intent": True,
        "runtime_intent": True,
        "syntax_only": False,
        "runtime_state_known": False,
        "command_executed": False,
        "host_mutation_proven": False,
        "network_called": False,
        "package_manager_executed": False,
        "filesystem_checked": False,
        "file_opened": False,
        "file_mutated": False,
        "plugin_loaded": False,
        "plugin_installed": False,
        "plugins_loaded": False,
        "raw_value_stored": False,
    }
    filename = Path(relative_path).name
    if filename in ZSH_STARTUP_FILENAMES:
        payload["startup_file_kind"] = filename.removeprefix(".")
    payload.update(metadata)
    return payload


def plugin_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    payload = configuration_metadata(
        {
            "plugin_loaded": False,
            "plugin_installed": False,
            "network_called": False,
            "shell_executed": False,
            "zsh_executed": False,
            "plugins_loaded": False,
        }
    )
    payload.update(metadata)
    return payload


def token_target_kind(token: str) -> str:
    if not token:
        return "unknown"
    redacted, _reason = redaction_for_value(token)
    if redacted:
        return "redacted"
    if (
        token.startswith("/")
        or token.startswith("~")
        or any(character in token for character in DYNAMIC_TARGET_CHARS)
    ):
        return "dynamic"
    return "static"


def safe_short_value(value: str | None) -> str | None:
    if value is None:
        return None
    redacted, _reason = redaction_for_value(value)
    if redacted:
        return "[redacted]"
    if is_dynamic_value(value):
        return "[dynamic]"
    if len(value) > 120:
        return "[omitted]"
    return value


def assignment_operation(variable: str, value: str) -> str:
    if value.lstrip().startswith("("):
        if variable in {"path", "fpath", "FPATH", "PATH"}:
            return "prepend"
        return "assign"
    return "assign"


def value_kind(value: str | None) -> str:
    if value is None:
        return "omitted"
    stripped = value.strip()
    if stripped.startswith("("):
        return "array"
    if has_command_substitution(stripped) or is_dynamic_value(stripped):
        return "dynamic"
    return "static"


def redaction_for_assignment(variable: str, value: str) -> tuple[bool, str]:
    name_redacted, name_reason = redaction_for_name(variable)
    if name_redacted:
        return True, name_reason
    value_redacted, value_reason = redaction_for_value(value)
    if value_redacted:
        return True, value_reason
    return False, ""


def redaction_for_name(name: str) -> tuple[bool, str]:
    reason = secret_name_redaction_reason(
        name,
        SECRET_NAME_PARTS,
        exact_names=PROMPT_VARIABLES,
        exact_reason="prompt-like-variable",
    )
    return bool(reason), reason


def redaction_for_value(value: str) -> tuple[bool, str]:
    reason = secret_value_redaction_reason(value, SECRET_NAME_PARTS)
    return bool(reason), reason


def target_display(target_token: str, target_kind: str) -> str:
    if target_kind == "static":
        return target_token
    if target_kind == "redacted":
        return "[redacted]"
    if target_kind == "dynamic":
        return "[dynamic]"
    return "[unknown]"


def is_dynamic_value(value: str) -> bool:
    return any(character in value for character in ("$", "`", "$("))


def has_command_substitution(line: str) -> bool:
    single = False
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'":
            single = not single
            continue
        if single:
            continue
        if char == "`":
            return True
        if char == "$" and index + 1 < len(line) and line[index + 1] == "(":
            return True
    return False


def strip_inline_comment(raw_line: str) -> str:
    single = False
    double = False
    escaped = False
    for index, char in enumerate(raw_line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not double:
            single = not single
            continue
        if char == '"' and not single:
            double = not double
            continue
        if char == "#" and not single and not double:
            if index == 0 or raw_line[index - 1].isspace():
                return raw_line[:index]
    return raw_line


def brace_delta(line: str) -> int:
    masked = mask_quoted_text(line)
    return masked.count("{") - masked.count("}")


def mask_quoted_text(line: str) -> str:
    output: list[str] = []
    single = False
    double = False
    escaped = False
    for char in line:
        if escaped:
            output.append(" ")
            escaped = False
            continue
        if char == "\\":
            output.append(" ")
            escaped = True
            continue
        if char == "'" and not double:
            single = not single
            output.append(" ")
            continue
        if char == '"' and not single:
            double = not double
            output.append(" ")
            continue
        output.append(" " if single or double else char)
    return "".join(output)


def is_quoted_at(line: str, offset: int) -> bool:
    single = False
    double = False
    escaped = False
    for index, char in enumerate(line):
        if index >= offset:
            return single or double
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not double:
            single = not single
            continue
        if char == '"' and not single:
            double = not double
            continue
    return single or double


def strip_wrapping_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def split_words(raw_line: str) -> list[str]:
    try:
        return shlex.split(raw_line, comments=False, posix=True)
    except ValueError:
        return []


def zsh_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "language": "zsh",
        "dialect": "zsh",
        "static_only": True,
        "shell_executed": False,
        "zsh_executed": False,
        "startup_executed": False,
        "plugins_loaded": False,
    }
    payload.update(metadata)
    return payload


def parse_export_word(word: str) -> tuple[str, str | None] | None:
    if "=" in word:
        variable, value = word.split("=", 1)
    else:
        variable, value = word, None
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", variable):
        return None
    return variable, value
