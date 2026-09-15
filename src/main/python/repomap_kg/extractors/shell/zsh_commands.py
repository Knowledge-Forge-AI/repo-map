"""Zsh command syntax classification helpers."""

from __future__ import annotations

import re

from repomap_kg.extractors.shell.zsh_common import is_dynamic_value, split_words


ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
COMMAND_WRAPPERS = frozenset({"command", "builtin", "env", "sudo", "time", "noglob"})
ZSH_BUILTINS = frozenset(
    {
        ".",
        "[",
        "[[",
        "autoload",
        "bindkey",
        "builtin",
        "cd",
        "compinit",
        "echo",
        "emulate",
        "exit",
        "export",
        "local",
        "print",
        "printf",
        "promptinit",
        "pwd",
        "read",
        "readonly",
        "return",
        "setopt",
        "shift",
        "source",
        "test",
        "typeset",
        "unsetopt",
        "zmodload",
        "zstyle",
    }
)
EXTERNAL_COMMANDS = frozenset(
    {
        "antidote",
        "antigen",
        "brew",
        "cargo",
        "cat",
        "chmod",
        "chown",
        "cp",
        "curl",
        "docker",
        "git",
        "go",
        "kubectl",
        "mkdir",
        "mv",
        "npm",
        "pip",
        "pipx",
        "python",
        "python3",
        "rm",
        "sed",
        "sheldon",
        "terraform",
        "touch",
        "wget",
        "zinit",
        "zplug",
    }
)
CONTROL_KEYWORDS = frozenset(
    {
        "case",
        "do",
        "done",
        "elif",
        "else",
        "esac",
        "fi",
        "for",
        "if",
        "then",
        "until",
        "while",
    }
)


def should_skip_command_syntax(stripped: str) -> bool:
    if not stripped:
        return True
    if stripped.startswith("#compdef") or stripped.startswith("_arguments"):
        return True
    words = split_words(stripped)
    if not words:
        return True
    if words[0] in CONTROL_KEYWORDS:
        return True
    if is_case_label_line(stripped):
        return True
    if ASSIGNMENT_RE.match(stripped):
        return True
    return False


def is_case_label_line(stripped: str) -> bool:
    if not stripped.endswith(")"):
        return False
    if stripped.startswith(("if ", "while ", "for ", "case ")):
        return False
    return bool(
        re.match(
            r"^[A-Za-z0-9_*?|@+!.-]+(?:\|[A-Za-z0-9_*?|@+!.-]+)*\)\s*$",
            stripped,
        )
    )


def split_command_segments(line: str) -> tuple[list[str], list[str]]:
    segments: list[str] = []
    operators: list[str] = []
    start = 0
    index = 0
    single = False
    double = False
    escaped = False
    while index < len(line):
        char = line[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if char == "'" and not double:
            single = not single
            index += 1
            continue
        if char == '"' and not single:
            double = not double
            index += 1
            continue
        if not single and not double:
            two = line[index : index + 2]
            if two in {"&&", "||"}:
                segments.append(line[start:index].strip())
                operators.append(two)
                index += 2
                start = index
                continue
            if char == "|" and not line[index : index + 2] == "||":
                segments.append(line[start:index].strip())
                operators.append("|")
                index += 1
                start = index
                continue
        index += 1
    segments.append(line[start:].strip())
    return [segment for segment in segments if segment], operators


def words_without_redirects(segment: str) -> list[str]:
    words = split_words(segment)
    output: list[str] = []
    skip_next = False
    for word in words:
        if skip_next:
            skip_next = False
            continue
        if word in {">", ">>", "<", "2>", "2>>", "&>", "<<<"}:
            skip_next = True
            continue
        if word == "2>&1" or word.startswith(
            (">", ">>", "<", "2>", "2>>", "&>", "<<<", "<<")
        ):
            continue
        output.append(word)
    return output


def first_command_index(words: list[str]) -> int | None:
    for index, word in enumerate(words):
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word):
            continue
        return index
    return None


def wrapped_command_index(words: list[str], wrapper_index: int) -> int | None:
    index = wrapper_index + 1
    while index < len(words):
        word = words[index]
        if words[wrapper_index] == "env" and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word):
            index += 1
            continue
        if word == "--":
            index += 1
            continue
        if word.startswith("-") and words[wrapper_index] in {
            "command",
            "builtin",
            "env",
            "sudo",
            "time",
        }:
            index += 1
            continue
        if is_dynamic_command_token(word):
            return None
        return index
    return None


def is_dynamic_command_token(token: str) -> bool:
    return token.startswith("$") or token.startswith("${") or is_dynamic_value(token)


def is_command_token(token: str) -> bool:
    return bool(re.match(r"^[A-Za-z_.][A-Za-z0-9_./+-]*$", token))


def command_family(command_name: str) -> str:
    if command_name in COMMAND_WRAPPERS:
        return "wrapper"
    if command_name in ZSH_BUILTINS:
        return "builtin"
    if command_name in EXTERNAL_COMMANDS:
        return "external"
    return "unknown"


def redirect_mode(operator: str) -> str:
    return {
        "<": "read",
        ">": "truncate",
        ">>": "append",
        "2>": "truncate",
        "2>>": "append",
        "2>&1": "duplicate",
        "&>": "combined_output",
        "<<<": "here_string",
    }.get(operator, "unknown")
