#!/usr/bin/env python3
"""Inventory tracked scanner directives from operative comment syntax."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tokenize
from typing import Iterable, Iterator


ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).with_name("pre_review_baseline.json")
OUTPUT_LIMIT_BYTES = 1_000_000
HASH_COMMENT_SUFFIXES = {
    ".bash", ".cfg", ".conf", ".ini", ".nix", ".rb", ".sh", ".toml",
    ".yaml", ".yml", ".zsh",
}
SLASH_COMMENT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".go", ".h", ".hpp", ".java", ".js", ".jsx",
    ".kt", ".rs", ".swift", ".ts", ".tsx",
}
SCOPE_TOKEN = re.compile(r"[A-Za-z0-9_.-]+")
RUFF_SCOPE = re.compile(r"[A-Z]+[0-9]+")
DIRECTIVES = (
    ("hadolint", re.compile(r"\bhadolint\s+ignore\s*=\s*(?P<scope>[^\r\n]+)", re.I)),
    ("nolint", re.compile(r"//\s*nolint(?:\s*:\s*(?P<scope>[^\r\n*]+))?", re.I)),
    ("nosemgrep", re.compile(r"\bnosemgrep(?:\s*:\s*(?P<scope>[^\r\n*]+))?", re.I)),
    ("ruff-noqa", re.compile(r"#\s*noqa(?:\s*:\s*(?P<scope>[^\r\n]+))?", re.I)),
    ("security-nosec", re.compile(r"#\s*nosec(?:\s*:?\s*(?P<scope>[^\r\n]+))?", re.I)),
    ("type-ignore", re.compile(r"#\s*type\s*:\s*ignore(?:\[(?P<scope>[^\]]+)\])?", re.I)),
    ("zizmor", re.compile(r"#\s*zizmor\s*:\s*ignore(?:\[(?P<scope>[^\]]+)\])?", re.I)),
)


@dataclass(frozen=True, order=True)
class Directive:
    kind: str
    path: str
    line: int
    fingerprint: str
    scope: tuple[str, ...]

    @classmethod
    def create(
        cls,
        kind: str,
        path: str,
        line: int,
        scope: Iterable[str],
    ) -> Directive:
        normalized_scope = tuple(sorted(set(scope))) or ("*",)
        material = "\0".join((kind, path, str(line), ",".join(normalized_scope)))
        return cls(
            kind=kind,
            path=path,
            line=line,
            fingerprint=hashlib.sha256(material.encode("utf-8")).hexdigest(),
            scope=normalized_scope,
        )

    @classmethod
    def from_jsonable(cls, item: object) -> Directive:
        if not isinstance(item, dict):
            raise ValueError("suppression baseline record must be an object")
        if not isinstance(item.get("justification"), str) or not item[
            "justification"
        ].strip():
            raise ValueError("suppression baseline record requires justification")
        try:
            record = cls.create(
                str(item["kind"]),
                str(item["path"]),
                int(item["line"]),
                tuple(str(value) for value in item["scope"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("suppression baseline record is invalid") from error
        if item.get("fingerprint") != record.fingerprint:
            raise ValueError("suppression baseline fingerprint mismatch")
        return record

    def to_jsonable(self) -> dict[str, object]:
        return {
            "fingerprint": self.fingerprint,
            "kind": self.kind,
            "line": self.line,
            "path": self.path,
            "scope": list(self.scope),
        }


@dataclass(frozen=True)
class InventoryDelta:
    added: tuple[Directive, ...]
    broadened: tuple[Directive, ...]
    removed: tuple[Directive, ...]
    unchanged: tuple[Directive, ...]

    @property
    def blocking(self) -> bool:
        return bool(self.added or self.broadened)


def tracked_files() -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return tuple(ROOT / item.decode() for item in result.stdout.split(b"\0") if item)


def _python_comments(text: str) -> Iterator[tuple[int, str]]:
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                yield token.start[0], token.string
    except (IndentationError, tokenize.TokenError):
        return


def _hash_comment(line: str) -> tuple[str, str | None]:
    quote = None
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote == '"':
            escaped = True
            continue
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "#":
            return line[:index], line[index:]
    return line, None


def _hash_comments(text: str, *, yaml: bool) -> Iterator[tuple[int, str]]:
    block_indent = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        indentation = len(line) - len(line.lstrip(" "))
        if block_indent is not None:
            if not line.strip() or indentation > block_indent:
                continue
            block_indent = None
        code, comment = _hash_comment(line)
        if yaml and re.search(r":\s*[|>][+-]?\s*\Z", code):
            block_indent = indentation
        if comment is not None:
            yield line_number, comment


def _slash_comments(text: str) -> Iterator[tuple[int, str]]:
    in_block = False
    quote = None
    escaped = False
    line_number = 1
    index = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if character == "\n":
            line_number += 1
            index += 1
            continue
        if in_block:
            end = text.find("*/", index)
            if end < 0:
                yield line_number, text[index:]
                return
            comment = text[index:end]
            yield line_number, comment
            line_number += comment.count("\n")
            index = end + 2
            in_block = False
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
            index += 1
            continue
        if character == "/" and following == "/":
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            yield line_number, text[index:end]
            index = end
            continue
        if character == "/" and following == "*":
            in_block = True
            index += 2
            continue
        index += 1


def _dash_comments(text: str) -> Iterator[tuple[int, str]]:
    for line_number, line in enumerate(text.splitlines(), start=1):
        quote = None
        for index, character in enumerate(line):
            if quote is not None:
                if character == quote:
                    quote = None
                continue
            if character in {"'", '"'}:
                quote = character
            elif line[index:index + 2] == "--":
                yield line_number, line[index:]
                break


def _comments(path: Path, text: str) -> Iterable[tuple[int, str]]:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return _python_comments(text)
    if path.name == "Dockerfile" or path.name.startswith("Dockerfile."):
        return _hash_comments(text, yaml=False)
    if suffix in HASH_COMMENT_SUFFIXES:
        return _hash_comments(text, yaml=suffix in {".yaml", ".yml"})
    if suffix in SLASH_COMMENT_SUFFIXES:
        return _slash_comments(text)
    if suffix == ".sql":
        return _dash_comments(text)
    return ()


def _scope(kind: str, match: re.Match[str]) -> tuple[str, ...]:
    captured = match.groupdict().get("scope")
    if kind == "ruff-noqa":
        return tuple(RUFF_SCOPE.findall(captured or "")) or ("*",)
    return tuple(SCOPE_TOKEN.findall(captured or "")) or ("*",)


def scan_paths(paths: Iterable[Path], *, root: Path = ROOT) -> tuple[Directive, ...]:
    records = []
    for path in sorted(paths):
        try:
            relative = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        for line, comment in _comments(path, text):
            for kind, pattern in DIRECTIVES:
                match = pattern.search(comment)
                if match is not None:
                    records.append(
                        Directive.create(kind, relative, line, _scope(kind, match))
                    )
    return tuple(sorted(records, key=lambda item: (item.path, item.line, item.kind)))


def _by_location(records: Iterable[Directive]) -> dict[tuple[str, str, int], Directive]:
    indexed = {}
    for record in records:
        key = (record.kind, record.path, record.line)
        if key in indexed:
            raise ValueError("duplicate suppression directive location")
        indexed[key] = record
    return indexed


def _adds_scope(previous: tuple[str, ...], current: tuple[str, ...]) -> bool:
    if current == previous or "*" in previous:
        return False
    if "*" in current:
        return True
    return bool(set(current) - set(previous))


def classify(
    current: Iterable[Directive],
    baseline: Iterable[Directive],
) -> InventoryDelta:
    current_by_location = _by_location(current)
    baseline_by_location = _by_location(baseline)
    added: list[Directive] = []
    broadened: list[Directive] = []
    removed: list[Directive] = []
    unchanged: list[Directive] = []
    locations = set(current_by_location) | set(baseline_by_location)
    for location in sorted(locations, key=lambda item: (item[1], item[2], item[0])):
        now = current_by_location.get(location)
        before = baseline_by_location.get(location)
        if before is None:
            if now is not None:
                added.append(now)
        elif now is None:
            removed.append(before)
        elif now.scope == before.scope:
            unchanged.append(now)
        elif _adds_scope(before.scope, now.scope):
            broadened.append(now)
        else:
            removed.append(before)
    return InventoryDelta(
        added=tuple(added),
        broadened=tuple(broadened),
        removed=tuple(removed),
        unchanged=tuple(unchanged),
    )


def load_baseline(path: Path = BASELINE_PATH) -> tuple[Directive, ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "repomap-pre-review-baseline-v2":
        raise ValueError("pre-review baseline schema is not v2")
    records = document["ratchets"]["scanner-suppressions"]["inventory"]
    if not isinstance(records, list):
        raise ValueError("suppression baseline inventory must be a list")
    return tuple(Directive.from_jsonable(item) for item in records)


def _document(
    inventory: tuple[Directive, ...],
    delta: InventoryDelta | None,
) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": "repomap-scanner-suppression-inventory-v2",
        "inventory": [record.to_jsonable() for record in inventory],
        "total": len(inventory),
    }
    if delta is not None:
        for name in ("added", "broadened", "removed", "unchanged"):
            document[name] = [
                record.to_jsonable() for record in getattr(delta, name)
            ]
        document["blocking"] = delta.blocking
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    args = parser.parse_args(argv)
    inventory = scan_paths(tracked_files())
    delta = None if args.inventory_only else classify(inventory, load_baseline(args.baseline))
    rendered = json.dumps(_document(inventory, delta), separators=(",", ":"), sort_keys=True)
    if len(rendered.encode("utf-8")) > OUTPUT_LIMIT_BYTES:
        raise RuntimeError("suppression inventory exceeded its machine-output limit")
    print(rendered)
    return 1 if delta is not None and delta.blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
