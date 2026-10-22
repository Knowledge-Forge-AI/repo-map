"""Exact author-correction proof document and raw commit reconstruction (ADR 0085)."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from ci.retained_python_contract import LineagePolicyError

PROOF_PATH = "tools/ci/public_author_corrections.json"
SCHEMA = "repomap-public-author-correction-proof-v1"
PROOF_ID = "REPOMAP-PRODUCT6-NAVIGATION40-CI57-PUBLIC-AUTHOR-CORRECTION1"
DECISION = "docs/adr/2026/10/0085-public-author-metadata-correction.md"
TARGET_AUTHOR = "Samuel Leighton Lair <sam.lair@knowledge-forge.ai>"
COMMITTER = "committer"
WITNESS = "inherited_projection_author"
SIGNATURES = (b"gpgsig", b"gpgsig-sha256")
RESTORABLE_SIGNATURE = b"gpgsig"
_FIELDS = {"schema", "proof", "decision", "target_author", "committer_policy", "old_tip",
           "new_tip", "rows"}
_ROW_FIELDS = {"old", "new", "old_author_source", "removed_signature_headers"}
_OID = re.compile(r"[0-9a-f]{40}")
_IDENT = re.compile(rb"([^<>\n]+ <[^<>\n]*>) ([0-9]+) ([+-][0-9]{4})")
_STRUCTURAL = {b"tree", b"parent", b"author", b"committer", *SIGNATURES}


def require(condition: object, message: str) -> None:
    if not condition:
        raise LineagePolicyError("author correction proof " + message)


@dataclass(frozen=True)
class Row:
    old: str
    new: str
    source: str
    signatures: tuple[tuple[int, bytes], ...]


@dataclass(frozen=True)
class Proof:
    old_tip: str
    new_tip: str
    rows: tuple[Row, ...]


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "contains duplicate JSON fields")
        result[key] = value
    return result


def _fields(value: object, expected: set[str]) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == expected, "fields are invalid")
    assert isinstance(value, dict)
    return value


def _oid(value: object) -> str:
    require(isinstance(value, str) and _OID.fullmatch(value), "object ID is invalid")
    assert isinstance(value, str)
    return value


def _signature(value: object) -> tuple[int, bytes]:
    item = _fields(value, {"position", "header_base64"})
    position, encoded = item["position"], item["header_base64"]
    require(type(position) is int and position >= 0 and isinstance(encoded, str),
            "signature preimage is invalid")
    try:
        header = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeError) as error:
        raise LineagePolicyError("author correction proof signature encoding is invalid") from error
    require(header.split(b" ", 1)[0] == RESTORABLE_SIGNATURE and not header.endswith(b"\n")
            and all(line.startswith(b" ") for line in header.split(b"\n")[1:]),
            "signature preimage is not a signature header")
    return position, header


def parse_proof(raw: bytes) -> Proof:
    """Parse the fully pinned proof; the target, rule and decision are not caller-chosen."""
    try:
        data = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError) as error:
        raise LineagePolicyError("author correction proof JSON is invalid") from error
    data = _fields(data, _FIELDS)
    require(data["schema"] == SCHEMA and data["proof"] == PROOF_ID and data["decision"] == DECISION
            and data["target_author"] == TARGET_AUTHOR and data["committer_policy"] == "preserve",
            "pinned identity or policy is invalid")
    require(isinstance(data["rows"], list) and data["rows"], "rows are missing")
    rows: list[Row] = []
    for value in data["rows"]:
        item = _fields(value, _ROW_FIELDS)
        require(item["old_author_source"] in {COMMITTER, WITNESS}, "author source is invalid")
        removed = item["removed_signature_headers"]
        require(isinstance(removed, list), "signature preimages are invalid")
        signatures = tuple(_signature(entry) for entry in removed)
        positions = [position for position, _ in signatures]
        require(positions == sorted(set(positions)), "signature positions are not ordered")
        rows.append(Row(_oid(item["old"]), _oid(item["new"]), item["old_author_source"], signatures))
    olds, news = [row.old for row in rows], [row.new for row in rows]
    require(len(set(olds)) == len(rows) and len(set(news)) == len(rows), "mapping is duplicate")
    require(not set(olds) & set(news), "mapping is cyclic or ambiguous")
    return Proof(_oid(data["old_tip"]), _oid(data["new_tip"]), tuple(rows))


def object_id(payload: bytes) -> str:
    return hashlib.sha1(b"commit %d\0" % len(payload) + payload).hexdigest()


@dataclass(frozen=True)
class RawCommit:
    headers: tuple[bytes, ...]
    message: bytes

    def render(self) -> bytes:
        return b"\n".join(self.headers) + b"\n\n" + self.message


def parse_commit(payload: bytes) -> RawCommit:
    """Split raw headers losslessly; continuation lines stay inside their header."""
    block, separator, message = payload.partition(b"\n\n")
    require(separator and block, "commit object is malformed")
    headers: list[bytes] = []
    for line in block.split(b"\n"):
        if line.startswith(b" "):
            require(headers, "commit object is malformed")
            headers[-1] += b"\n" + line
        else:
            require(b" " in line, "commit header is malformed")
            headers.append(line)
    commit = RawCommit(tuple(headers), message)
    require(commit.render() == payload, "commit object is not canonical")
    return commit


def _key(header: bytes) -> bytes:
    return header.split(b" ", 1)[0]


def parents(commit: RawCommit) -> tuple[str, ...]:
    result: list[str] = []
    for header in commit.headers[1:]:
        if _key(header) != b"parent":
            break
        value = header[7:].decode("ascii", "replace")
        require(_OID.fullmatch(value), "parent header is invalid")
        result.append(value)
    return tuple(result)


def identity(commit: RawCommit, field: bytes) -> tuple[bytes, bytes]:
    """Return one exact ``Name <email>`` and its unchanged ``timestamp offset`` suffix."""
    values = [header[len(field) + 1:] for header in commit.headers if _key(header) == field]
    require(len(values) == 1, f"{field.decode()} header is not unique")
    match = _IDENT.fullmatch(values[0])
    require(match, f"{field.decode()} header is malformed")
    assert match is not None
    return match.group(1), match.group(2) + b" " + match.group(3)


def reconstruct(new: RawCommit, row: Row, old_by_new: dict[str, str], witness: bytes | None) -> bytes:
    """Rebuild the original object from corrected bytes plus fixed public preimages only."""
    headers = new.headers
    require(_key(headers[0]) == b"tree" and _OID.fullmatch(headers[0][5:].decode("ascii", "replace")),
            "tree header is invalid")
    parent_ids = parents(new)
    at = 1 + len(parent_ids)
    require(len(headers) >= at + 2 and _key(headers[at]) == b"author"
            and _key(headers[at + 1]) == b"committer", "header order is invalid")
    extras = headers[at + 2:]
    require(not any(_key(header) in _STRUCTURAL for header in extras),
            "corrected commit has an unexpected structural or signature header")
    author, stamp = identity(new, b"author")
    committer, _ = identity(new, b"committer")
    require(author == TARGET_AUTHOR.encode(), "corrected author is not the requested identity")
    previous = committer if row.source == COMMITTER else witness
    require(previous is not None and previous != author, "original author cannot be derived")
    assert previous is not None
    require(all(parent in old_by_new for parent in parent_ids), "parent is outside the corrected range")
    old_headers = [headers[0], *(b"parent " + old_by_new[p].encode() for p in parent_ids),
                   b"author " + previous + b" " + stamp, headers[at + 1], *extras]
    for position, header in row.signatures:
        require(at + 2 <= position <= len(old_headers), "signature position is invalid")
        old_headers.insert(position, header)
    payload = RawCommit(tuple(old_headers), new.message).render()
    require(object_id(payload) == row.old, "original object ID does not match its reconstruction")
    return payload


def witness_author(commit_text: str) -> bytes:
    """Read the author identity from an already published recovered-commit witness."""
    try:
        payload = commit_text.encode("utf-8")
    except UnicodeError as error:
        raise LineagePolicyError("author correction proof witness encoding is invalid") from error
    return identity(parse_commit(payload), b"author")[0]
