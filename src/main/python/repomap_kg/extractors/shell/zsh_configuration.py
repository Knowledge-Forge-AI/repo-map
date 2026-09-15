"""Zsh configuration, plugin, theme, and prompt observation helpers."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.zsh_commands import ASSIGNMENT_RE
from repomap_kg.extractors.shell.zsh_common import (
    EXTRACTOR,
    PLUGIN_MANAGER_NAMES,
    PROMPT_VARIABLES,
    configuration_metadata,
    is_dynamic_value,
    plugin_metadata,
    redaction_for_assignment,
    redaction_for_value,
    safe_short_value,
    secret_like_observation,
    split_words,
    strip_wrapping_quotes,
    target_display,
    token_target_kind,
    value_kind,
    zsh_metadata,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


def zsh2_configuration_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    observations.extend(autoload_observations(relative_path, line_number, line))
    observations.extend(fpath_observations(relative_path, line_number, line))
    observations.extend(zstyle_observations(relative_path, line_number, line))
    observations.extend(zmodload_observations(relative_path, line_number, line))
    observations.extend(bindkey_observations(relative_path, line_number, line))
    observations.extend(compinit_observations(relative_path, line_number, line))
    observations.extend(plugin_theme_prompt_observations(relative_path, line_number, line))
    return tuple(observations)


def autoload_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(line)
    if not words or words[0] != "autoload":
        return ()
    flags = [word for word in words[1:] if word.startswith("-")]
    candidates = [word for word in words[1:] if not word.startswith("-")]
    static_functions: list[str] = []
    redacted_count = 0
    dynamic_count = 0
    for candidate in candidates:
        redacted, _reason = redaction_for_value(candidate)
        if redacted:
            redacted_count += 1
        elif is_dynamic_value(candidate):
            dynamic_count += 1
        else:
            static_functions.append(candidate)
    target_kind = "static"
    if redacted_count:
        target_kind = "redacted"
    elif dynamic_count:
        target_kind = "dynamic"
    elif not static_functions:
        target_kind = "unknown"
    metadata = configuration_metadata(
        {
            "function_names": static_functions,
            "flags": flags,
            "target_kind": target_kind,
            "static_function_count": len(static_functions),
            "dynamic_function_count": dynamic_count,
            "redacted_function_count": redacted_count,
            "autoload_executed": False,
            "function_loaded": False,
            "filesystem_checked": False,
        }
    )
    if target_kind == "dynamic":
        metadata["dynamic_reason"] = "computed_autoload"
    return (
        RawObservation(
            kind="zsh.autoload",
            source_id=f"{relative_path}#zsh-autoload:{line_number}:{slug('-'.join(static_functions) or target_kind)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name="autoload",
            confidence="extracted" if target_kind == "static" else "unknown",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=zsh_metadata(metadata),
        ),
    )


def fpath_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    match = re.match(r"^\s*(fpath|FPATH)\s*=\s*\((.*)\)\s*$", line)
    if match is None:
        return ()
    variable = match.group(1)
    entries = split_words(match.group(2))
    static_count = 0
    dynamic_count = 0
    redacted_count = 0
    for entry in entries:
        redacted, _reason = redaction_for_value(entry)
        if redacted:
            redacted_count += 1
        elif is_dynamic_value(entry):
            dynamic_count += 1
        else:
            static_count += 1
    operation = "assign"
    if entries and entries[-1] in {"$fpath", "$FPATH"}:
        operation = "prepend"
    elif entries and entries[0] in {"$fpath", "$FPATH"}:
        operation = "append"
    return (
        RawObservation(
            kind="zsh.fpath",
            source_id=f"{relative_path}#zsh-fpath:{line_number}:{slug(variable)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=variable,
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=zsh_metadata(
                configuration_metadata(
                    {
                        "operation": operation,
                        "path_count": len(entries),
                        "static_path_count": static_count,
                        "dynamic_path_count": dynamic_count,
                        "redacted_path_count": redacted_count,
                        "filesystem_checked": False,
                        "fpath_runtime_state_known": False,
                        "raw_value_stored": False,
                    }
                )
            ),
        ),
    )


def zstyle_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(line)
    if len(words) < 3 or words[0] != "zstyle":
        return ()
    context_pattern = words[1]
    style_name = words[2]
    values = words[3:]
    redacted = False
    reasons: list[str] = []
    for label, value in (("context", context_pattern), ("style", style_name)):
        is_redacted, reason = redaction_for_value(value)
        if is_redacted:
            redacted = True
            reasons.append(f"{label}:{reason}")
    for value in values:
        is_redacted, reason = redaction_for_value(value)
        if is_redacted:
            redacted = True
            reasons.append(reason)
    value_kind = "omitted"
    if values:
        if redacted:
            value_kind = "redacted"
        elif any(is_dynamic_value(value) for value in values):
            value_kind = "dynamic"
        else:
            value_kind = "static"
    metadata: dict[str, Any] = configuration_metadata(
        {
            "context_pattern": "[redacted]" if redacted else context_pattern,
            "style_name": style_name,
            "value_kind": value_kind,
            "value_count": len(values),
            "raw_value_stored": bool(values) and not redacted,
            "zstyle_applied": False,
        }
    )
    if not redacted and values and len(" ".join(values)) <= 120:
        metadata["value_summary"] = values
    if redacted:
        metadata["redacted"] = True
        metadata["redaction_reason"] = ",".join(dict.fromkeys(reasons)) or "secret-like-value"
    observation = RawObservation(
        kind="zsh.zstyle",
        source_id=f"{relative_path}#zsh-zstyle:{line_number}:{slug(style_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=style_name,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(metadata),
    )
    observations: list[RawObservation] = [observation]
    if redacted:
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                style_name,
                "zstyle",
                str(metadata["redaction_reason"]),
            )
        )
    return tuple(observations)


def zmodload_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(line)
    if not words or words[0] != "zmodload":
        return ()
    operation = "list"
    module_name = None
    for word in words[1:]:
        if word == "-u":
            operation = "unload"
            continue
        if word.startswith("-"):
            continue
        module_name = word
        if operation == "list":
            operation = "load"
        break
    target_kind = token_target_kind(module_name or "")
    return (
        RawObservation(
            kind="zsh.zmodload",
            source_id=f"{relative_path}#zsh-zmodload:{line_number}:{slug(module_name or operation)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=target_display(module_name or "", target_kind) if module_name else operation,
            confidence="extracted" if target_kind == "static" else "unknown",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=zsh_metadata(
                configuration_metadata(
                    {
                        "module_name": target_display(module_name or "", target_kind) if module_name else None,
                        "operation": operation,
                        "target_kind": target_kind,
                        "module_loaded": False,
                    }
                )
            ),
        ),
    )


def bindkey_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(line)
    if not words or words[0] != "bindkey":
        return ()
    keymap_mode = None
    key_sequence = None
    widget_name = None
    if len(words) > 1 and words[1] in {"-e", "-v"}:
        keymap_mode = "emacs" if words[1] == "-e" else "vi"
    elif len(words) > 2:
        key_sequence = safe_short_value(words[1])
        widget_name = safe_short_value(words[2])
    return (
        RawObservation(
            kind="zsh.bindkey",
            source_id=f"{relative_path}#zsh-bindkey:{line_number}:{slug(keymap_mode or key_sequence or 'binding')}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=keymap_mode or widget_name or "bindkey",
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=zsh_metadata(
                configuration_metadata(
                    {
                        "keymap_mode": keymap_mode,
                        "key_sequence": key_sequence,
                        "widget_name": widget_name,
                        "binding_applied": False,
                    }
                )
            ),
        ),
    )


def compinit_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(line)
    if not words or words[0] != "compinit":
        return ()
    return (
        RawObservation(
            kind="zsh.compinit",
            source_id=f"{relative_path}#zsh-compinit:{line_number}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name="compinit",
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=zsh_metadata(
                configuration_metadata(
                    {
                        "flags": [word for word in words[1:] if word.startswith("-")],
                        "compinit_executed": False,
                        "completion_system_initialized": False,
                        "filesystem_checked": False,
                    }
                )
            ),
        ),
    )


def plugin_theme_prompt_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    observations.extend(oh_my_zsh_plugin_array_observations(relative_path, line_number, line))
    observations.extend(theme_prompt_observations(relative_path, line_number, line))
    observations.extend(plugin_manager_command_observations(relative_path, line_number, line))
    return tuple(observations)


def oh_my_zsh_plugin_array_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    match = re.match(r"^\s*plugins\s*=\s*\((.*)\)\s*$", line)
    if match is None:
        return ()
    observations: list[RawObservation] = [
        plugin_manager_observation(relative_path, line_number, "oh_my_zsh", "array")
    ]
    for plugin in split_words(match.group(1)):
        target_kind = token_target_kind(plugin)
        if target_kind != "static":
            continue
        observations.append(
            plugin_observation(
                relative_path,
                line_number,
                "oh_my_zsh",
                plugin,
                "array",
            )
        )
    return tuple(observations)


def theme_prompt_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    match = ASSIGNMENT_RE.match(line.strip())
    if match is None:
        return ()
    variable, value = match.group(1), match.group(2).strip()
    observations: list[RawObservation] = []
    if variable == "ZSH_THEME":
        redacted, reason = redaction_for_assignment(variable, value)
        theme_name = "[redacted]" if redacted else strip_wrapping_quotes(value)
        metadata: dict[str, Any] = configuration_metadata(
            {
                "variable": variable,
                "theme_name": theme_name,
                "value_kind": "redacted" if redacted else value_kind(value),
                "declaration_kind": "assignment",
                "theme_loaded": False,
                "raw_value_stored": not redacted,
            }
        )
        if redacted:
            metadata["redacted"] = True
            metadata["redaction_reason"] = reason
        observations.append(
            RawObservation(
                kind="zsh.theme",
                source_id=f"{relative_path}#zsh-theme:{line_number}:{slug(variable)}",
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=theme_name,
                confidence="extracted" if not redacted else "unknown",
                extractor=EXTRACTOR,
                extractor_version=__version__,
                metadata=zsh_metadata(metadata),
            )
        )
    if variable in PROMPT_VARIABLES:
        redacted, reason = redaction_for_assignment(variable, value)
        metadata = configuration_metadata(
            {
                "variable": variable,
                "value_kind": "redacted" if redacted else value_kind(value),
                "raw_value_stored": False,
                "prompt_applied": False,
                "redacted": True,
                "redaction_reason": reason or "prompt-like-variable",
            }
        )
        observations.append(
            RawObservation(
                kind="zsh.prompt",
                source_id=f"{relative_path}#zsh-prompt:{line_number}:{slug(variable)}",
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=variable,
                confidence="heuristic",
                extractor=EXTRACTOR,
                extractor_version=__version__,
                metadata=zsh_metadata(metadata),
            )
        )
    return tuple(observations)


def plugin_manager_command_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(line)
    if not words:
        return ()
    observations: list[RawObservation] = []
    first = words[0]
    if first in {"source", "."} and len(words) > 1 and "oh-my-zsh.sh" in words[1]:
        observations.append(plugin_manager_observation(relative_path, line_number, "oh_my_zsh", "source"))
    if first == "eval" and "sheldon" in line:
        observations.append(plugin_manager_observation(relative_path, line_number, "sheldon", "eval"))
    if first == "zinit":
        observations.append(plugin_manager_observation(relative_path, line_number, "zinit", "command"))
        if len(words) > 2 and words[1] in {"light", "load"} and token_target_kind(words[2]) == "static":
            observations.append(plugin_observation(relative_path, line_number, "zinit", words[2], "command"))
    elif first == "antigen":
        observations.append(plugin_manager_observation(relative_path, line_number, "antigen", "command"))
        if len(words) > 2 and words[1] == "bundle" and token_target_kind(words[2]) == "static":
            observations.append(plugin_observation(relative_path, line_number, "antigen", words[2], "command"))
    elif first == "zplug":
        observations.append(plugin_manager_observation(relative_path, line_number, "zplug", "command"))
        if len(words) > 1 and words[1] != "load" and token_target_kind(words[1]) == "static":
            observations.append(plugin_observation(relative_path, line_number, "zplug", words[1], "command"))
    elif first == "antidote":
        observations.append(plugin_manager_observation(relative_path, line_number, "antidote", "command"))
    return tuple(observations)


def plugin_manager_observation(
    relative_path: str,
    line_number: int,
    manager: str,
    declaration_kind: str,
) -> RawObservation:
    return RawObservation(
        kind="zsh.plugin_manager",
        source_id=f"{relative_path}#zsh-plugin-manager:{line_number}:{slug(manager + '-' + declaration_kind)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=manager,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            plugin_metadata(
                {
                    "manager": manager,
                    "declaration_kind": declaration_kind,
                }
            )
        ),
    )


def plugin_observation(
    relative_path: str,
    line_number: int,
    manager: str,
    plugin_name: str,
    declaration_kind: str,
) -> RawObservation:
    redacted, reason = redaction_for_value(plugin_name)
    safe_plugin_name = "[redacted]" if redacted else plugin_name
    metadata: dict[str, Any] = plugin_metadata(
        {
            "manager": manager,
            "plugin_name": safe_plugin_name,
            "declaration_kind": declaration_kind,
            "raw_value_stored": not redacted,
        }
    )
    if redacted:
        metadata["redacted"] = True
        metadata["redaction_reason"] = reason
    return RawObservation(
        kind="zsh.plugin",
        source_id=f"{relative_path}#zsh-plugin:{line_number}:{slug(manager + '-' + safe_plugin_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=safe_plugin_name,
        confidence="heuristic" if not redacted else "unknown",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(metadata),
    )
