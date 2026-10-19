"""Closed projection documents and offline Git inclusion evidence (ADR 0084)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import cast

from ci.retained_python_contract import LineagePolicyError, RatchetContractError, validate_baseline
from ci.retained_python_records import BaselineDocument, is_repository_path
from ci.retained_python_selection import selection_digest

PROOFS_PATH = "tools/ci/retained_python_projection_proofs.json"
EVIDENCE_PATH = "tools/ci/retained_python_projection_blobs"
SCHEMA = "repomap-retained-python-projection-proofs-v1"


def require(condition: object, message: str) -> None:
    if not condition:
        raise LineagePolicyError("projection proof " + message)


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        require(key not in result, "contains duplicate JSON fields")
        result[key] = value
    return result


def document(raw: bytes) -> dict:
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError) as error:
        raise LineagePolicyError("projection proof JSON is invalid") from error
    require(isinstance(value, dict), "document is not an object")
    return value


def fields(value: object, expected: set[str]) -> dict:
    require(isinstance(value, dict) and set(value) == expected, "fields are invalid")
    assert isinstance(value, dict)
    return value


def digest(value: object, size: int = 64) -> None:
    require(isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{size}}}", value),
            "digest is invalid")


def parse_proofs(raw: bytes | None) -> list[dict]:
    if raw is None:
        return []
    data = fields(document(raw), {"schema", "proofs"})
    require(data["schema"] == SCHEMA and isinstance(data["proofs"], list), "schema is invalid")
    identifiers: set[str] = set()
    edges: set[tuple[str, str]] = set()
    for proof in data["proofs"]:
        fields(proof, {"proof", "decision", "reason", "commit", "parent", "states", "hops"})
        for name in ("proof", "reason"):
            require(isinstance(proof[name], str) and proof[name].strip(), "text is invalid")
        decision = proof["decision"]
        require(is_repository_path(decision) and decision.startswith("docs/adr/")
                and decision.endswith(".md"), "decision path is invalid")
        for name in ("commit", "parent"):
            digest(proof[name], 40)
        edge = (proof["commit"], proof["parent"])
        require(proof["proof"] not in identifiers and edge not in edges, "is duplicate")
        identifiers.add(proof["proof"])
        edges.add(edge)
        states, hops = proof["states"], proof["hops"]
        require(isinstance(states, list) and len(states) >= 3, "needs intermediate states")
        require(isinstance(hops, list) and len(hops) == len(states) - 1, "hop count is invalid")
        for state in states:
            fields(state, {"baseline_sha256", "ownership_sha256", "selected_set_sha256"})
            for value in state.values():
                digest(value)
        require(len({s["baseline_sha256"] for s in states}) == len(states), "states form a cycle")
        for index, hop in enumerate(hops):
            fields(hop, {"phase", "source_commit"} | ({"source_objects"} if index else set()))
            require(isinstance(hop["phase"], str) and hop["phase"].strip(), "phase is invalid")
            digest(hop["source_commit"], 40)
            if index:
                objects = fields(hop["source_objects"], {"commit", "trees"})
                require(isinstance(objects["commit"], str) and isinstance(objects["trees"], dict),
                        "source objects are invalid")
    return data["proofs"]


def read_file(root: Path, path: str) -> bytes:
    target = root / path
    require(is_repository_path(path) and target.resolve() == root.resolve() / path
            and not target.is_symlink(), "evidence path is aliased")
    try:
        return target.read_bytes()
    except FileNotFoundError as error:
        raise LineagePolicyError("projection proof evidence is missing") from error
    except OSError as error:
        raise RatchetContractError("projection evidence I/O failed") from error


def state_document(baseline: bytes, ownership: bytes, state: dict) -> BaselineDocument:
    require(hashlib.sha256(baseline).hexdigest() == state["baseline_sha256"], "baseline digest mismatch")
    require(hashlib.sha256(ownership).hexdigest() == state["ownership_sha256"], "ownership digest mismatch")
    data = document(baseline)
    try:
        validate_baseline(data)
    except RatchetContractError as error:
        raise LineagePolicyError("projection baseline contract is invalid") from error
    require(data["ownership"]["sha256"] == state["ownership_sha256"], "embedded ownership mismatch")
    validated = cast(BaselineDocument, data)
    require(selection_digest(validated) == state["selected_set_sha256"], "selection digest mismatch")
    document(ownership)
    return validated


def object_id(root: Path, kind: str, payload: bytes) -> str:
    computed = hashlib.sha1(f"{kind} {len(payload)}\0".encode() + payload).hexdigest()
    run = subprocess.run(["git", "hash-object", "--stdin", "-t", kind], input=payload,
                         cwd=root, capture_output=True, check=False, timeout=60)
    require(run.returncode == 0, "Git object validation failed")
    require(run.stdout.decode().strip() == computed, "Git object digest mismatch")
    return computed


def tree_entries(payload: bytes) -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    while payload:
        try:
            header, tail = payload.split(b"\0", 1)
            mode, raw_name = header.split(b" ", 1)
            name = raw_name.decode("utf-8")
            require(len(tail) >= 20 and name not in entries and name not in {".", ".."}
                    and "/" not in name and "\\" not in name and bool(name), "tree entry is invalid")
            require(mode in {b"40000", b"100644", b"100755", b"120000", b"160000"}, "tree mode is invalid")
            entries[name] = mode.decode(), tail[:20].hex()
            payload = tail[20:]
        except (ValueError, UnicodeError) as error:
            raise LineagePolicyError("projection proof tree is malformed") from error
    return entries


def authenticate(root: Path, source: str, objects: dict, blobs: dict[str, bytes]) -> None:
    """Bind complete old-state bytes to a pre-existing record's source commit."""
    try:
        payload = objects["commit"].encode("utf-8")
    except UnicodeError as error:
        raise LineagePolicyError("projection proof commit encoding is invalid") from error
    require(object_id(root, "commit", payload) == source, "source commit binding mismatch")
    first = payload.split(b"\n", 1)[0]
    require(first.startswith(b"tree "), "source tree is missing")
    try:
        root_oid = first[5:].decode("ascii")
        trees = {path: bytes.fromhex(value) for path, value in objects["trees"].items()}
    except (ValueError, TypeError, UnicodeError) as error:
        raise LineagePolicyError("projection proof tree encoding is invalid") from error
    digest(root_oid, 40)
    used: set[str] = set()
    for path, content in blobs.items():
        require(is_repository_path(path), "source blob path is invalid")
        oid, directory = root_oid, "."
        parts = PurePosixPath(path).parts
        for index, part in enumerate(parts):
            require(directory in trees, "source tree evidence is missing")
            tree = trees[directory]
            require(object_id(root, "tree", tree) == oid, "source tree binding mismatch")
            used.add(directory)
            entry = tree_entries(tree).get(part)
            require(entry is not None, "source path inclusion is missing")
            assert entry is not None
            mode, oid = entry
            final = index == len(parts) - 1
            require(mode == ("100644" if final else "40000"), "source inclusion mode is invalid")
            if final:
                require(object_id(root, "blob", content) == oid, "source blob binding mismatch")
            directory = part if directory == "." else f"{directory}/{part}"
    require(used == set(trees), "has unused tree evidence")
