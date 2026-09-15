"""Fail-closed reader and accessors for this repository's own workflow YAML.

The CI topology contracts must inspect workflow structure, not text. PyYAML is
not a declared dependency and the PR Fast lane installs only the
``static-analysis`` extra, so this module implements the exact restricted YAML
subset the repository's workflows use. Every construct outside that subset
raises instead of being guessed at: a reader that silently mis-parses is weaker
than the grep assertions it replaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WorkflowParseError(RuntimeError):
    """The document uses a construct outside the supported YAML subset."""


_KEY_PATTERN = re.compile(
    r"""^(?P<key>"[^"]*"|'[^']*'|[^:\s"'][^:]*?)\s*:(?:\s+(?P<value>\S.*))?$"""
)
_BLOCK_PATTERN = re.compile(
    r"""^(?P<key>"[^"]*"|'[^']*'|[^:\s"'][^:]*?)\s*:\s*\|(?P<chomp>[-+])?$"""
)
_DASH_PATTERN = re.compile(r"^-(\s+|$)")
_REJECTED_PREFIXES = ("&", "*", "!", "{", ">", "?")


@dataclass(frozen=True, slots=True)
class _Token:
    indent: int
    kind: str
    key: str | None
    value: Any
    line: int


def _strip_comment(raw: str) -> str:
    in_single = False
    in_double = False
    for index, character in enumerate(raw):
        if character == "'" and not in_double:
            in_single = not in_single
        elif character == '"' and not in_single:
            in_double = not in_double
        elif character == "#" and not in_single and not in_double:
            if index == 0 or raw[index - 1] in " \t":
                return raw[:index]
    return raw


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1].replace("''", "'")
    return text


def _parse_scalar(text: str, line: int) -> Any:
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        if "[" in inner or "]" in inner or "{" in inner:
            return _reject("nested flow collection", line)
        return [_parse_scalar(item, line) for item in inner.split(",")]
    if text.startswith(_REJECTED_PREFIXES):
        return _reject(f"unsupported scalar {text!r}", line)
    if text.startswith(('"', "'")):
        return _unquote(text)
    if text in {"true", "True"}:
        return True
    if text in {"false", "False"}:
        return False
    if text in {"null", "~", ""}:
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def _reject(reason: str, line: int) -> Any:
    raise WorkflowParseError(f"line {line}: {reason}")


def _collect_block_scalar(lines: list[str], start: int, indent: int) -> tuple[str, int]:
    body: list[str] = []
    index = start
    while index < len(lines):
        raw = lines[index]
        if raw.strip() and len(raw) - len(raw.lstrip(" ")) <= indent:
            break
        body.append(raw)
        index += 1
    while body and not body[-1].strip():
        body.pop()
    if not body:
        return "", index
    widths = [len(line) - len(line.lstrip(" ")) for line in body if line.strip()]
    margin = min(widths)
    return "\n".join(line[margin:] if line.strip() else "" for line in body), index


def _tokenize(text: str) -> list[_Token]:
    lines = text.splitlines()
    tokens: list[_Token] = []
    index = 0
    while index < len(lines):
        raw = lines[index]
        number = index + 1
        if "\t" in raw:
            _reject("tab indentation", number)
        if raw.strip() in {"---", "..."}:
            _reject("multi-document YAML", number)
        content = _strip_comment(raw).rstrip()
        if not content.strip():
            index += 1
            continue
        indent = len(content) - len(content.lstrip(" "))
        body = content.strip()
        while True:
            dash = _DASH_PATTERN.match(body)
            if dash is None:
                break
            if not dash.group(1):
                _reject("empty sequence item", number)
            tokens.append(_Token(indent, "dash", None, None, number))
            indent += len(dash.group(0))
            body = body[len(dash.group(0)) :]
        block = _BLOCK_PATTERN.match(body)
        if block is not None:
            if block.group("chomp"):
                _reject("block chomping indicators are unsupported", number)
            value, index = _collect_block_scalar(lines, index + 1, indent)
            tokens.append(
                _Token(indent, "key", _unquote(block.group("key")), value, number)
            )
            continue
        entry = _KEY_PATTERN.match(body)
        if entry is not None:
            raw_value = entry.group("value")
            parsed_value = None if raw_value is None else _parse_scalar(raw_value, number)
            tokens.append(
                _Token(indent, "key", _unquote(entry.group("key")), parsed_value, number)
            )
        else:
            tokens.append(_Token(indent, "scalar", None, _parse_scalar(body, number), number))
        index += 1
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._position = 0

    def _peek(self) -> _Token | None:
        if self._position >= len(self._tokens):
            return None
        return self._tokens[self._position]

    def parse(self) -> Any:
        token = self._peek()
        if token is None:
            return None
        document = self._node(token.indent)
        if self._peek() is not None:
            _reject("trailing content", self._tokens[self._position].line)
        return document

    def _node(self, indent: int) -> Any:
        token = self._peek()
        if token is None or token.indent < indent:
            return None
        if token.kind == "dash":
            return self._sequence(token.indent)
        if token.kind == "scalar":
            self._position += 1
            return token.value
        return self._mapping(token.indent)

    def _sequence(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while True:
            token = self._peek()
            if token is None or token.indent != indent or token.kind != "dash":
                break
            self._position += 1
            nested = self._peek()
            if nested is None or nested.indent <= indent:
                _reject("sequence item has no value", token.line)
                break
            items.append(self._node(nested.indent))
        return items

    def _mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while True:
            token = self._peek()
            if token is None or token.indent < indent or token.kind == "dash":
                break
            if token.indent > indent:
                _reject("unexpected indentation", token.line)
            if token.kind != "key":
                _reject("expected a mapping key", token.line)
            self._position += 1
            key = token.key
            if key in result:
                _reject(f"duplicate key {key!r}", token.line)
            if token.value is not None:
                result[str(key)] = token.value
                continue
            nested = self._peek()
            if nested is not None and nested.indent > indent:
                result[str(key)] = self._node(nested.indent)
            elif nested is not None and nested.kind == "dash" and nested.indent == indent:
                result[str(key)] = self._sequence(indent)
            else:
                result[str(key)] = None
        return result


def parse_yaml(text: str) -> Any:
    """Parse the supported YAML subset, raising on anything else."""
    return _Parser(_tokenize(text)).parse()


@dataclass(frozen=True, slots=True)
class Workflow:
    """One parsed workflow document plus the accessors contracts need."""

    path: Path
    document: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.document.get("name", ""))

    @property
    def triggers(self) -> dict[str, Any]:
        # The repository writes the trigger key unquoted; this reader treats it
        # as the plain string "on" rather than a YAML 1.1 boolean.
        value = self.document.get("on")
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise WorkflowParseError(f"{self.path.name}: unsupported trigger form")
        return value

    @property
    def permissions(self) -> dict[str, Any]:
        value = self.document.get("permissions")
        return value if isinstance(value, dict) else {}

    @property
    def jobs(self) -> dict[str, Any]:
        value = self.document.get("jobs")
        return value if isinstance(value, dict) else {}

    def steps(self) -> tuple[dict[str, Any], ...]:
        collected: list[dict[str, Any]] = []
        for job in self.jobs.values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or ():
                if isinstance(step, dict):
                    collected.append(step)
        return tuple(collected)

    def run_commands(self) -> tuple[str, ...]:
        return tuple(
            str(step["run"]) for step in self.steps() if step.get("run") is not None
        )

    def action_uses(self) -> tuple[str, ...]:
        return tuple(
            str(step["uses"]) for step in self.steps() if step.get("uses") is not None
        )


def load_workflow(path: Path) -> Workflow:
    """Load and structurally parse one workflow file."""
    document = parse_yaml(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise WorkflowParseError(f"{path.name}: workflow must be a mapping")
    return Workflow(path=path, document=document)


def load_workflows(workflow_dir: Path) -> tuple[Workflow, ...]:
    """Load every workflow in ``workflow_dir`` in stable filename order."""
    paths = sorted(
        path
        for path in workflow_dir.iterdir()
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    )
    return tuple(load_workflow(path) for path in paths)
