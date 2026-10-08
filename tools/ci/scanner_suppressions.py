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
    target: str = ""
    occurrence: int = 1

    @classmethod
    def create(
        cls, kind: str, path: str, line: int, scope: Iterable[str], *, target: str = "", occurrence: int = 1
    ) -> Directive:
        norm_scope = tuple(sorted(set(scope))) or ("*",)
        norm_tgt = re.sub(r"\s+", " ", target).strip()
        mat = "\0".join((kind, path, norm_tgt, str(occurrence), ",".join(norm_scope)))
        fp = hashlib.sha256(mat.encode("utf-8")).hexdigest()
        return cls(kind, path, line, fp, norm_scope, norm_tgt, occurrence)

    @classmethod
    def from_jsonable(cls, item: object) -> Directive:
        if not isinstance(item, dict):
            raise ValueError("suppression baseline record must be an object")
        if not isinstance(item.get("justification"), str) or not item["justification"].strip():
            raise ValueError("suppression baseline record requires justification")
        try:
            record = cls.create(
                str(item["kind"]), str(item["path"]), int(item["line"]),
                tuple(str(v) for v in item["scope"]),
                target=str(item.get("target", "")), occurrence=int(item.get("occurrence", 1)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("suppression baseline record is invalid") from error
        if item.get("fingerprint") != record.fingerprint:
            raise ValueError("suppression baseline fingerprint mismatch")
        return record

    def to_jsonable(self) -> dict[str, object]:
        return {
            "fingerprint": self.fingerprint, "kind": self.kind, "line": self.line,
            "occurrence": self.occurrence, "path": self.path, "scope": list(self.scope),
            "target": self.target,
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


def _extract_target(lines: list[str], line_num: int, comment: str) -> str:
    if not (1 <= line_num <= len(lines)):
        return ""
    line = lines[line_num - 1]
    c_idx = line.find(comment)
    prefix = line[:c_idx].strip() if c_idx >= 0 else line.strip()
    if prefix:
        return re.sub(r"\s+", " ", prefix).strip()
    for idx in range(line_num, min(line_num + 10, len(lines))):
        cand = lines[idx].strip()
        if not cand or cand.startswith(("#", "//", "--", "/*", "*")):
            continue
        m = re.search(r"(#|//|--)", cand)
        return re.sub(r"\s+", " ", cand[:m.start()].strip() if m else cand).strip()
    return ""


def scan_paths(paths: Iterable[Path], *, root: Path = ROOT) -> tuple[Directive, ...]:
    records = []
    for path in sorted(paths):
        try:
            relative = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        lines = text.splitlines()
        file_records: list[tuple[int, str, re.Match[str], str]] = []
        for line, comment in _comments(path, text):
            for kind, pattern in DIRECTIVES:
                match = pattern.search(comment)
                if match is not None:
                    file_records.append((line, kind, match, _extract_target(lines, line, comment)))
        file_records.sort(key=lambda item: item[0])
        occ_counts: dict[tuple[str, str], int] = {}
        for line, kind, match, target in file_records:
            occ_key = (kind, target)
            occ_counts[occ_key] = occ_counts.get(occ_key, 0) + 1
            records.append(Directive.create(
                kind, relative, line, _scope(kind, match), target=target, occurrence=occ_counts[occ_key],
            ))
    return tuple(sorted(records, key=lambda item: (item.path, item.line, item.kind)))


def _adds_scope(previous: tuple[str, ...], current: tuple[str, ...]) -> bool:
    if current == previous or "*" in previous:
        return False
    return True if "*" in current else bool(set(current) - set(previous))


def classify(
    current: Iterable[Directive],
    baseline: Iterable[Directive],
) -> InventoryDelta:
    current_list, baseline_list = list(current), list(baseline)
    added, broadened, removed, unchanged = [], [], [], []
    matched_cur, matched_base = set(), set()

    def _record_match(c: Directive, b: Directive, c_idx: int, b_idx: int) -> None:
        matched_cur.add(c_idx)
        matched_base.add(b_idx)
        if c.scope == b.scope:
            unchanged.append(c)
        elif _adds_scope(b.scope, c.scope):
            broadened.append(c)
        else:
            removed.append(b)

    # Pass 1: exact location match (path, kind, line, [target], occurrence)
    base_by_loc: dict[tuple[str, str, int, int], list[int]] = {}
    seen_base_keys: set[tuple[str, str, int, str, int]] = set()
    for idx, b in enumerate(baseline_list):
        base_key = (b.path, b.kind, b.line, b.target, b.occurrence)
        if base_key in seen_base_keys:
            raise ValueError("duplicate suppression directive location in baseline")
        seen_base_keys.add(base_key)
        base_by_loc.setdefault((b.path, b.kind, b.line, b.occurrence), []).append(idx)

    for c_idx, c in enumerate(current_list):
        candidates = base_by_loc.get((c.path, c.kind, c.line, c.occurrence), [])
        matched_b_idx: int | None = None
        for b_idx in candidates:
            if b_idx not in matched_base:
                b = baseline_list[b_idx]
                if not b.target or b.target == c.target:
                    matched_b_idx = b_idx
                    break
        if matched_b_idx is not None:
            _record_match(c, baseline_list[matched_b_idx], c_idx, matched_b_idx)

    # Pass 2: relocation match on (path, kind, target, occurrence)
    base_by_target: dict[tuple[str, str, str, int], int] = {}
    for b_idx, b in enumerate(baseline_list):
        if b_idx not in matched_base and b.target:
            tgt_key = (b.path, b.kind, b.target, b.occurrence)
            if tgt_key in base_by_target:
                raise ValueError("duplicate suppression directive target in baseline")
            base_by_target[tgt_key] = b_idx

    for c_idx, c in enumerate(current_list):
        if c_idx not in matched_cur and c.target:
            tgt_key = (c.path, c.kind, c.target, c.occurrence)
            if tgt_key in base_by_target:
                b_idx = base_by_target.pop(tgt_key)
                _record_match(c, baseline_list[b_idx], c_idx, b_idx)

    # Pass 3: remaining unmatched
    for c_idx, c in enumerate(current_list):
        if c_idx not in matched_cur:
            added.append(c)
    for b_idx, b in enumerate(baseline_list):
        if b_idx not in matched_base:
            removed.append(b)

    _sort = lambda items: tuple(sorted(items, key=lambda it: (it.path, it.line, it.kind)))
    return InventoryDelta(_sort(added), _sort(broadened), _sort(removed), _sort(unchanged))


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
            document[name] = [record.to_jsonable() for record in getattr(delta, name)]
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
