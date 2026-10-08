"""Conservative raw shell syntax lexer and semantic quote provenance validator."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re
import shlex


@dataclass(frozen=True)
class WordPart:
    """A contiguous span of a shell word with its quoting classification."""

    kind: str  # literal, single_quoted, double_quoted_text, escaped, param_expansion, cmd_substitution
    text: str
    raw: str


class ShellWord(str):
    """A shell word preserving raw text provenance and parsed components."""

    raw: str
    parts: tuple[WordPart, ...]

    def __new__(cls, value: str, raw: str, parts: tuple[WordPart, ...] = ()) -> ShellWord:
        obj = super().__new__(cls, value)
        obj.raw = raw
        obj.parts = parts
        return obj

    def has_single_quotes(self) -> bool:
        return any(p.kind == "single_quoted" for p in self.parts)

    def has_escaped_expansions(self) -> bool:
        return any(p.kind == "escaped" and p.text in {"$", "(", "{"} for p in self.parts)


def _scan_param_expansion(script: str, i: int) -> tuple[str, str, int]:
    start, i = i, i + 2
    var_start, n = i, len(script)
    while i < n and script[i] != "}":
        if script[i] == "\n":
            raise ValueError("No closing quotation")
        i += 1
    if i >= n:
        raise ValueError("No closing quotation")
    return script[var_start:i], script[start:i + 1], i + 1


def _scan_cmd_sub(script: str, i: int) -> tuple[str, str, int]:
    start, i = i, i + 2
    cmd_start, depth, n = i, 1, len(script)
    while i < n and depth > 0:
        c = script[i]
        if c == "\\":
            i += 2
        elif c in {"\x27", '"'}:
            quote = c
            i += 1
            while i < n and script[i] != quote:
                i += 2 if quote == '"' and script[i] == "\\" else 1
            if i >= n:
                raise ValueError("No closing quotation")
            i += 1
        elif c == "(":
            depth += 1
            i += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
            i += 1
        else:
            i += 1
    if depth != 0:
        raise ValueError("No closing quotation")
    return script[cmd_start:i], script[start:i + 1], i + 1


def _scan_dollar(script: str, i: int, in_double: bool = False) -> tuple[WordPart, int]:
    if i + 1 < len(script):
        if script[i + 1] == "(":
            cmd_text, raw_sub, next_i = _scan_cmd_sub(script, i)
            return WordPart("cmd_substitution", f"$({cmd_text})", raw_sub), next_i
        if script[i + 1] == "{":
            var_name, raw_param, next_i = _scan_param_expansion(script, i)
            return WordPart("param_expansion", f"${{{var_name}}}", raw_param), next_i
        if script[i + 1].isalpha() or script[i + 1] == "_":
            m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", script[i + 1:])
            assert m is not None
            raw_param = f"${m.group(0)}"
            return WordPart("param_expansion", raw_param, raw_param), i + 1 + len(m.group(0))
    kind = "double_quoted_text" if in_double else "literal"
    return WordPart(kind, "$", "$"), i + 1


def parse_shell_script(script: str) -> list[list[str]]:
    """Parse shell script into command lists preserving word quote provenance."""
    commands: list[list[str]] = []
    current_command: list[str] = []
    word_parts: list[WordPart] = []
    word_val: list[str] = []
    word_raw: list[str] = []

    def flush_word() -> None:
        nonlocal word_parts, word_val, word_raw
        if word_raw:
            val, raw = "".join(word_val), "".join(word_raw)
            current_command.append(ShellWord(val, raw, tuple(word_parts)))
            word_parts, word_val, word_raw = [], [], []

    def flush_command() -> None:
        nonlocal current_command
        flush_word()
        if current_command:
            commands.append(current_command)
            current_command = []

    i, n = 0, len(script)
    while i < n:
        c = script[i]
        if c == "\\" and i + 1 < n and script[i + 1] == "\n":
            i += 2
        elif c == "#" and not word_raw:
            while i < n and script[i] != "\n":
                i += 1
        elif c in " \t\r":
            flush_word()
            i += 1
        elif c == "\n":
            flush_command()
            i += 1
        elif c in ";|&":
            flush_word()
            i += 2 if i + 1 < n and script[i + 1] == c else 1
            flush_command()
        elif c == "\x27":
            start, i = i, i + 1
            content_start = i
            while i < n and script[i] != "\x27":
                i += 1
            if i >= n:
                raise ValueError("No closing quotation")
            content, raw = script[content_start:i], script[start:i + 1]
            i += 1
            word_parts.append(WordPart("single_quoted", content, raw))
            word_val.append(content)
            word_raw.append(raw)
        elif c == '"':
            word_raw.append('"')
            i += 1
            while i < n and script[i] != '"':
                ch = script[i]
                if ch == "\\" and i + 1 < n:
                    nxt = script[i + 1]
                    if nxt == "\n":
                        i += 2
                    elif nxt in "\"\\$`":
                        kind = "escaped" if nxt == "$" else "double_quoted_text"
                        val = "$" if nxt == "$" else nxt
                        word_parts.append(WordPart(kind, val, f"\\{nxt}"))
                        word_val.append(val)
                        word_raw.append(f"\\{nxt}")
                        i += 2
                    else:
                        word_parts.append(WordPart("double_quoted_text", f"\\{nxt}", f"\\{nxt}"))
                        word_val.append(f"\\{nxt}")
                        word_raw.append(f"\\{nxt}")
                        i += 2
                elif ch == "$":
                    part, i = _scan_dollar(script, i, in_double=True)
                    word_parts.append(part)
                    word_val.append(part.text)
                    word_raw.append(part.raw)
                else:
                    txt_start = i
                    while i < n and script[i] not in "\"\\$":
                        i += 1
                    txt = script[txt_start:i]
                    word_parts.append(WordPart("double_quoted_text", txt, txt))
                    word_val.append(txt)
                    word_raw.append(txt)
            if i >= n:
                raise ValueError("No closing quotation")
            word_raw.append('"')
            i += 1
        elif c == "\\":
            if i + 1 < n:
                nxt = script[i + 1]
                if nxt == "\n":
                    i += 2
                else:
                    kind = "escaped" if nxt == "$" else "literal"
                    val = "$" if nxt == "$" else nxt
                    word_parts.append(WordPart(kind, val, f"\\{nxt}"))
                    word_val.append(val)
                    word_raw.append(f"\\{nxt}")
                    i += 2
            else:
                word_parts.append(WordPart("literal", "\\", "\\"))
                word_val.append("\\")
                word_raw.append("\\")
                i += 1
        elif c == "$":
            part, i = _scan_dollar(script, i, in_double=False)
            word_parts.append(part)
            word_val.append(part.text)
            word_raw.append(part.raw)
        else:
            txt_start = i
            while i < n and script[i] not in " \t\r\n;|&\x27\"\\$":
                i += 1
            txt = script[txt_start:i]
            word_parts.append(WordPart("literal", txt, txt))
            word_val.append(txt)
            word_raw.append(txt)
    flush_command()
    return commands


def validate_var_expansion(word: str, expected_var: str) -> bool:
    """Validate that word is a double-quoted or safe unquoted expansion of expected_var."""
    if not isinstance(word, ShellWord) or word.has_single_quotes() or word.has_escaped_expansions():
        return False
    expansions = [p for p in word.parts if p.kind == "param_expansion"]
    if len(expansions) != 1 or expansions[0].text not in {f"${expected_var}", f"${{{expected_var}}}"}:
        return False
    return not any(p is not expansions[0] and p.text for p in word.parts)


def validate_key_value_var_expansion(word: str, expected_key: str, expected_var: str) -> bool:
    """Validate that word is KEY=VALUE where VALUE safely expands expected_var."""
    if not isinstance(word, ShellWord) or word.has_single_quotes() or word.has_escaped_expansions():
        return False
    if "\x27" in word.raw or not str(word).startswith(expected_key + "="):
        return False
    expansions = [p for p in word.parts if p.kind == "param_expansion"]
    if len(expansions) != 1 or expansions[0].text not in {f"${expected_var}", f"${{{expected_var}}}"}:
        return False
    prefix_parts = [p for p in word.parts if p is not expansions[0]]
    return "".join(p.text for p in prefix_parts) == expected_key + "="


def validate_cmd_substitution(word: str, expected_command: list[str]) -> bool:
    """Validate that word is a double-quoted or safe unquoted command substitution."""
    if not isinstance(word, ShellWord) or word.has_single_quotes() or word.has_escaped_expansions():
        return False
    substitutions = [p for p in word.parts if p.kind == "cmd_substitution"]
    if len(substitutions) != 1 or "\x27" in word.raw.replace(substitutions[0].raw, ""):
        return False
    if any(p is not substitutions[0] and p.text for p in word.parts):
        return False
    return shlex.split(substitutions[0].raw[2:-1]) == expected_command


def validate_key_value_cmd_sub(word: str, expected_key: str, expected_command: list[str]) -> bool:
    """Validate that word is KEY=$(...) where $(...) safely executes expected_command."""
    if not isinstance(word, ShellWord) or word.has_single_quotes() or word.has_escaped_expansions():
        return False
    if not str(word).startswith(expected_key + "="):
        return False
    substitutions = [p for p in word.parts if p.kind == "cmd_substitution"]
    if len(substitutions) != 1 or "\x27" in word.raw.replace(substitutions[0].raw, ""):
        return False
    prefix_parts = [p for p in word.parts if p is not substitutions[0]]
    if "".join(p.text for p in prefix_parts) != expected_key + "=":
        return False
    return shlex.split(substitutions[0].raw[2:-1]) == expected_command


def validate_command_option_var_expansion(
    arguments: Sequence[str], flag: str, expected_var: str
) -> bool:
    """Validate that flag is specified once with a valid variable expansion."""
    valid_count = 0
    total_flag_count = 0
    for index, token in enumerate(arguments):
        if token == flag:
            total_flag_count += 1
            if index + 1 < len(arguments) and validate_var_expansion(arguments[index + 1], expected_var):
                valid_count += 1
        elif token.startswith(flag + "="):
            total_flag_count += 1
            if validate_key_value_var_expansion(token, flag, expected_var):
                valid_count += 1
    return total_flag_count == 1 and valid_count == 1


def validate_command_option_cmd_sub(
    arguments: Sequence[str], flag: str, expected_command: list[str]
) -> bool:
    """Validate that flag is specified once with a valid command substitution."""
    valid_count = 0
    total_flag_count = 0
    for index, token in enumerate(arguments):
        if token == flag:
            total_flag_count += 1
            if index + 1 < len(arguments) and validate_cmd_substitution(arguments[index + 1], expected_command):
                valid_count += 1
        elif token.startswith(flag + "="):
            total_flag_count += 1
            if validate_key_value_cmd_sub(token, flag, expected_command):
                valid_count += 1
    return total_flag_count == 1 and valid_count == 1


def validate_var_path_expansion(word: str, variable: str, suffix: str) -> bool:
    """Require an expanded variable followed by the exact literal path suffix."""
    if not isinstance(word, ShellWord) or word.has_single_quotes() or word.has_escaped_expansions():
        return False
    expansions = [part for part in word.parts if part.kind == "param_expansion"]
    if len(expansions) != 1 or expansions[0].text not in {"$" + variable, "${" + variable + "}"}:
        return False
    return str(word) == expansions[0].text + suffix and "".join(
        part.text for part in word.parts if part is not expansions[0]
    ) == suffix
