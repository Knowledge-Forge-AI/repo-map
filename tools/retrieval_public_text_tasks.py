"""Selected-only calibration task loading over the hash-pinned raw catalog (study section 3).

``load_task_catalog`` decodes held-out tasks, so it is not used. A byte-level locator tracks only
JSON string/escape state and depth, compares each element's raw ``task_id`` token with the
canonical selected-id encodings, and never decodes, stores or counts an unselected token or body.
Only the raw byte hash is recomputed; the historical semantic identity is carried, never compared.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from common_lore_index.storage.semantic_candidates import digest_json
from retrieval_evaluation_schema import TASK_CATALOG_SCHEMA_VERSION, EvaluationTask
from retrieval_public_text_census import retained_task_sha256

TASK_PINS_SCHEMA = "cloe-public-text-selected-task-pins-v1"
SELECTED_TASK_SET_SCHEMA = "cloe-public-text-selected-task-set-v1"
CATALOG_FILE_SHA256 = "10a34e261ee625dbfffb31e30d450bca270878291890f165e6031a86b3bf6d38"
HISTORICAL_SEMANTIC_CATALOG_IDENTITY = "sha256:8da52c1a477a78ba5f467892690e2f59045326d18ba371d693dda157736a80a1"
ORIGINAL_MANIFEST_SHA256 = "33b417da06658f8aac3be851d4df5ad3655b2cbd1157d2009b0da65cbffa1155"
SELECTED_TASKS: tuple[tuple[str, int, str], ...] = (
    ("cal-01", 1, "sha256:86f343b80be32c5a785fd886603a511e7bac9354c0ed42864c9f897e821dce0e"),
    ("cal-02", 1, "sha256:92c19d7af627b4306330f0d9f87b973df88bf5a5bb331a80fefc5cb557a36ca2"),
    ("cal-03", 1, "sha256:cc0a3905abd7564143df29ce99f16191b8ddaad233abb55536adac47e5a10188"),
    ("cal-04", 1, "sha256:455a5d7ba69583612cbea6b1bbf0dbbebd5f1d9cf23fbdf094bb72548e429c82"),
    ("cal-05", 1, "sha256:6d6f5c4b1e9efd29d3334d6b6c7fb76da119c0c5aa6f488450bfeaeb2011af98"),
    ("cal-06", 1, "sha256:9c1fb3c236bb1469a1190b4b8fd2661f1b4cbd0316ff337cdfe56120c55f084a"),
    ("cal-07", 1, "sha256:81215c2291a73204191443b9539dee390a6d1c198000e21676f6db0731bbd9eb"),
    ("cal-08", 1, "sha256:877744572e3fdc7abb3c91595a944fb01b77858b8644334053f59fb772d4a13d"),
    ("cal-09", 1, "sha256:8eb256815a9b6869b17ec4edf159e146e3a4532f4da38fa1f587016417a4795b"),
    ("cal-10", 1, "sha256:74fbfb669ff04b803a4ab7480e9ca05d4d609441a79a31868d6ebdad48a63fcf"),
    ("cal-11", 1, "sha256:69bc0aa1e97aa9768acad50ec3e1a146833e08646fc93877769487dd93874e69"),
    ("cal-12", 1, "sha256:d5b778d84623ff380d0ca2b550d759302c04a2c2d0a58ce04563f35cd8513e8e"),
    ("cal-13", 1, "sha256:fe176f87553dee59dfd54cf3df9be6b6911a9920b04ddb8c82a857da5e796069"),
    ("cal-14", 1, "sha256:e2cffa3685bf46217416e882b9446355d9d5d5877d449710eead2297e3ebd726"),
    ("cal-15", 1, "sha256:f99a7614cbf0d58a245d9cc830e3c65341e938c5611619bb650d9fcaa53906d0"),
    ("cal-16", 1, "sha256:766de752781b87a3055cf4010380deca4e620b54ca87d65963040f9f010b0c59"),
    ("cal-17", 1, "sha256:d19c8888c0af02388c5d2e01b1cfa98f3d5ac80374f93e87ffed8080828d1302"),
    ("cal-18", 1, "sha256:143d964c74a8a3f883a0aa8bbadd807b6fcffca115baa23d086853aaa5813cdf"),
    ("cal-19", 1, "sha256:025f6bb3535853b9d1a68fbc0660ef3d0efc4e469ef1491b8238ab7b9f8eb63b"),
    ("cal-20", 1, "sha256:5f18b608154eea8c1254c2f741676ceb775eb0d13d5ccf91029e3c95468533a3"),
    ("cal-21", 1, "sha256:9405f7722f3a614c24db974f99df979bd4817b02f61badbdd0ab42dd7e78bbb5"),
    ("cal-22", 1, "sha256:ec150d9a6c3d6bb632771e19b9ae73b56faa19fe26f41c418b42c13e0f02e937"),
    ("cal-23", 2, "sha256:5bb268734bdfef24cfa9ac3521da0c15036c846756c3880634245b280e90ac66"),
    ("cal-24", 1, "sha256:ffe7481f32dfdd3924a9fbe0cf50f2c04a17e2dc3c7bc1ef863ce219725efcef"),
)
MAX_CATALOG_BYTES = 4 * 1024 * 1024
MAX_PINS_BYTES = 64 * 1024
MAX_SELECTED_TASKS = 24
MAX_DEPTH = 64

TASK_SELECTION_CODES = (
    "task_pins_invalid", "task_catalog_unavailable", "task_catalog_changed", "task_catalog_hash_mismatch",
    "task_catalog_structure", "task_selected_missing", "task_selected_duplicate", "task_selected_invalid",
    "task_split_mismatch", "task_generation_mismatch", "task_digest_mismatch",
)
(TASK_PINS_INVALID, TASK_CATALOG_UNAVAILABLE, TASK_CATALOG_CHANGED, TASK_CATALOG_HASH_MISMATCH,
 TASK_CATALOG_STRUCTURE, TASK_SELECTED_MISSING, TASK_SELECTED_DUPLICATE, TASK_SELECTED_INVALID,
 TASK_SPLIT_MISMATCH, TASK_GENERATION_MISMATCH, TASK_PIN_DIGEST_MISMATCH) = TASK_SELECTION_CODES

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_PIN_KEYS = frozenset({
    "catalog_file_sha256", "held_out_decoded", "historical_semantic_catalog_identity", "original_manifest_sha256",
    "schema", "tasks",
})
_WS = frozenset(b" \t\r\n")
_SCALAR = re.compile(rb"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null")
_TASK_ID_KEY = b'"task_id"'


class TaskSelectionRefusal(ValueError):
    """Closed refusal; the message is the closed code and never carries catalog content."""

    def __init__(self, code: str) -> None:
        if code not in TASK_SELECTION_CODES:
            raise ValueError("unknown task selection code")
        super().__init__(code)
        self.code = code


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _no_constant(_value: str) -> Any:
    raise ValueError("non-finite JSON constant")


def _decode_json(raw: bytes) -> Any:
    """The only decoder applied to catalog task spans; held-out spans never reach it."""
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_no_constant)


@dataclass(frozen=True)
class SelectedTaskPins:
    """Closed registered pin set; ``held_out_decoded`` is always False."""

    catalog_file_sha256: str
    historical_semantic_catalog_identity: str
    original_manifest_sha256: str
    tasks: tuple[tuple[str, int, str], ...]

    def __post_init__(self) -> None:
        if not _valid_pins(self):
            raise TaskSelectionRefusal(TASK_PINS_INVALID)

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_file_sha256": self.catalog_file_sha256, "held_out_decoded": False,
            "historical_semantic_catalog_identity": self.historical_semantic_catalog_identity,
            "original_manifest_sha256": self.original_manifest_sha256, "schema": TASK_PINS_SCHEMA,
            "tasks": [{"generation": g, "task_id": t, "task_sha256": d} for t, g, d in self.tasks],
        }

    def identity(self) -> str:
        return str(digest_json(self.to_dict()))


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _valid_pins(pins: SelectedTaskPins) -> bool:
    rows = pins.tasks
    return (
        _matches(_HEX64, pins.catalog_file_sha256) and _matches(_HEX64, pins.original_manifest_sha256)
        and _matches(_DIGEST, pins.historical_semantic_catalog_identity)
        and type(rows) is tuple and 1 <= len(rows) <= MAX_SELECTED_TASKS
        and all(
            type(row) is tuple and len(row) == 3 and _matches(_TASK_ID, row[0]) and type(row[1]) is int
            and row[1] in (1, 2) and _matches(_DIGEST, row[2]) for row in rows
        )
        and len({row[0] for row in rows}) == len(rows)
    )


def registered_task_pins() -> SelectedTaskPins:
    return SelectedTaskPins(CATALOG_FILE_SHA256, HISTORICAL_SEMANTIC_CATALOG_IDENTITY, ORIGINAL_MANIFEST_SHA256,
                            SELECTED_TASKS)


def parse_task_pins(raw: bytes) -> SelectedTaskPins:
    """Strict closed parser for the registered task-pins input shape."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_PINS_BYTES:
        raise TaskSelectionRefusal(TASK_PINS_INVALID)
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_no_constant)
    except (ValueError, RecursionError) as error:
        raise TaskSelectionRefusal(TASK_PINS_INVALID) from error
    if (
        not isinstance(value, dict) or set(value) != _PIN_KEYS or value["schema"] != TASK_PINS_SCHEMA
        or value["held_out_decoded"] is not False or not isinstance(value["tasks"], list)
    ):
        raise TaskSelectionRefusal(TASK_PINS_INVALID)
    rows: list[tuple[str, int, str]] = []
    for item in value["tasks"]:
        if not isinstance(item, dict) or set(item) != {"generation", "task_id", "task_sha256"}:
            raise TaskSelectionRefusal(TASK_PINS_INVALID)
        rows.append((item["task_id"], item["generation"], item["task_sha256"]))
    return SelectedTaskPins(value["catalog_file_sha256"], value["historical_semantic_catalog_identity"],
                            value["original_manifest_sha256"], tuple(rows))


@dataclass(frozen=True)
class SelectedTaskSet:
    """Exactly the pinned calibration tasks, in pin order."""

    pins: SelectedTaskPins
    tasks: tuple[EvaluationTask, ...] = field(repr=False)

    def for_generation(self, generation: int) -> tuple[EvaluationTask, ...]:
        return tuple(task for task in self.tasks if task.generation == generation)

    def retained_digests(self, generation: int) -> dict[str, str]:
        return {task_id: digest for task_id, g, digest in self.pins.tasks if g == generation}

    def to_dict(self) -> dict[str, Any]:
        return {
            "pins": self.pins.to_dict(), "task_pins_identity": self.pins.identity(),
            "selected_task_set_identity": self.identity(),
            "tasks": [{"task_id": t.task_id, "generation": t.generation, "task_sha256": retained_task_sha256(t)}
                      for t in self.tasks],
        }

    def identity(self) -> str:
        return str(digest_json({
            "schema": SELECTED_TASK_SET_SCHEMA, "task_pins_identity": self.pins.identity(),
            "tasks": [[t.task_id, t.generation, retained_task_sha256(t)] for t in self.tasks],
        }))


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_catalog(path: Path, max_bytes: int) -> tuple[bytes, tuple[int, ...]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise TaskSelectionRefusal(TASK_CATALOG_UNAVAILABLE) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise TaskSelectionRefusal(TASK_CATALOG_UNAVAILABLE)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(max_bytes + 1)
        after = os.fstat(descriptor)
    except OSError as error:
        raise TaskSelectionRefusal(TASK_CATALOG_UNAVAILABLE) from error
    finally:
        os.close(descriptor)
    if len(raw) > max_bytes:
        raise TaskSelectionRefusal(TASK_CATALOG_UNAVAILABLE)
    if _stat_identity(before) != _stat_identity(after) or len(raw) != before.st_size:
        raise TaskSelectionRefusal(TASK_CATALOG_CHANGED)
    return raw, _stat_identity(after)


class _Locator:
    """Lexical JSON walker: string/escape state and container depth only; no value is built."""

    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def ws(self, i: int) -> int:
        while i < len(self.raw) and self.raw[i] in _WS:
            i += 1
        return i

    def expect(self, i: int, byte: bytes) -> int:
        if self.raw[i:i + 1] != byte:
            raise TaskSelectionRefusal(TASK_CATALOG_STRUCTURE)
        return i + 1

    def string_end(self, i: int) -> int:
        i = self.expect(i, b'"')
        while i < len(self.raw):
            byte = self.raw[i]
            if byte == 0x22:
                return i + 1
            if byte < 0x20:
                raise TaskSelectionRefusal(TASK_CATALOG_STRUCTURE)
            i += 2 if byte == 0x5C else 1
        raise TaskSelectionRefusal(TASK_CATALOG_STRUCTURE)

    def key(self, i: int) -> tuple[bytes, int]:
        end = self.string_end(i)
        token = self.raw[i:end]
        if b"\\" in token:
            raise TaskSelectionRefusal(TASK_CATALOG_STRUCTURE)
        return token, self.expect(self.ws(end), b":")

    def value_end(self, i: int, depth: int) -> int:
        head = self.raw[i:i + 1]
        if head == b'"':
            return self.string_end(i)
        if head in (b"{", b"["):
            return self.container_end(i, depth + 1)
        match = _SCALAR.match(self.raw, i)
        if match is None:
            raise TaskSelectionRefusal(TASK_CATALOG_STRUCTURE)
        return match.end()

    def members(self, i: int, opening: bytes, depth: int, handle: Callable[[bytes | None, int], int]) -> int:
        """Walk one object/array at ``i``; ``handle(key token or None, value start)`` returns the value end."""
        keyed = opening == b"{"
        close = b"}" if keyed else b"]"
        i = self.ws(self.expect(i, opening))
        if depth > MAX_DEPTH:
            raise TaskSelectionRefusal(TASK_CATALOG_STRUCTURE)
        if self.raw[i:i + 1] == close:
            return i + 1
        while True:
            token = None
            if keyed:
                token, i = self.key(i)
                i = self.ws(i)
            i = self.ws(handle(token, i))
            if self.raw[i:i + 1] != b",":
                return self.expect(i, close)
            i = self.ws(i + 1)

    def container_end(self, i: int, depth: int) -> int:
        return self.members(i, self.raw[i:i + 1], depth, lambda _token, start: self.value_end(start, depth))


def _locate(raw: bytes, wanted: dict[bytes, str]) -> dict[str, tuple[int, int]]:
    """Return selected element spans; refuse structure, duplicates and trailing bytes."""
    loc = _Locator(raw)
    spans: dict[str, tuple[int, int]] = {}
    seen: set[bytes | None] = set()

    def element(_token: bytes | None, start: int) -> int:
        task_ids: list[bytes] = []

        def member(key: bytes | None, value_start: int) -> int:
            end = loc.value_end(value_start, 3)
            if key == _TASK_ID_KEY:
                task_ids.append(raw[value_start:end])
            return end

        end = loc.members(start, b"{", 3, member)
        if len(task_ids) != 1 or not task_ids[0].startswith(b'"'):
            raise TaskSelectionRefusal(TASK_CATALOG_STRUCTURE)
        task_id = wanted.get(task_ids[0])
        if task_id is not None:
            if task_id in spans:
                raise TaskSelectionRefusal(TASK_SELECTED_DUPLICATE)
            spans[task_id] = (start, end)
        return end

    def top(key: bytes | None, start: int) -> int:
        if key in seen:
            raise TaskSelectionRefusal(TASK_CATALOG_STRUCTURE)
        seen.add(key)
        if key == b'"schema_version"':
            end = loc.string_end(start)
            if json.loads(raw[start:end]) != TASK_CATALOG_SCHEMA_VERSION:
                raise TaskSelectionRefusal(TASK_CATALOG_STRUCTURE)
            return end
        if key == b'"tasks"':
            return loc.members(start, b"[", 2, element)
        return loc.value_end(start, 1)

    end = loc.members(loc.ws(0), b"{", 1, top)
    if loc.ws(end) != len(raw) or not {b'"schema_version"', b'"tasks"'} <= seen:
        raise TaskSelectionRefusal(TASK_CATALOG_STRUCTURE)
    return spans


def _decode_selected(span: bytes, task_id: str, generation: int, digest: str) -> EvaluationTask:
    try:
        value = _decode_json(span)
    except (ValueError, RecursionError) as error:
        raise TaskSelectionRefusal(TASK_SELECTED_INVALID) from error
    if not isinstance(value, dict) or value.get("task_id") != task_id:
        raise TaskSelectionRefusal(TASK_SELECTED_INVALID)
    try:
        task = EvaluationTask.from_mapping(value)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise TaskSelectionRefusal(TASK_SELECTED_INVALID) from error
    if task.split != "calibration":
        raise TaskSelectionRefusal(TASK_SPLIT_MISMATCH)
    if type(value.get("generation")) is not int or task.generation != generation:
        raise TaskSelectionRefusal(TASK_GENERATION_MISMATCH)
    if retained_task_sha256(task) != digest:
        raise TaskSelectionRefusal(TASK_PIN_DIGEST_MISMATCH)
    return task


def load_selected_calibration_tasks(
    catalog_path: Path, pins: SelectedTaskPins, *, max_bytes: int = MAX_CATALOG_BYTES,
) -> SelectedTaskSet:
    """Decode exactly the pinned calibration records; every other byte is skipped lexically."""
    if type(pins) is not SelectedTaskPins:
        raise TaskSelectionRefusal(TASK_PINS_INVALID)
    if type(max_bytes) is not int or max_bytes < 1:
        raise TaskSelectionRefusal(TASK_CATALOG_UNAVAILABLE)
    path = Path(catalog_path)
    raw, identity = _read_catalog(path, max_bytes)
    if hashlib.sha256(raw).hexdigest() != pins.catalog_file_sha256:
        raise TaskSelectionRefusal(TASK_CATALOG_HASH_MISMATCH)
    wanted = {json.dumps(task_id, ensure_ascii=True).encode("ascii"): task_id for task_id, _g, _d in pins.tasks}
    try:
        spans = _locate(raw, wanted)
    except (IndexError, ValueError, RecursionError) as error:
        if isinstance(error, TaskSelectionRefusal):
            raise
        raise TaskSelectionRefusal(TASK_CATALOG_STRUCTURE) from error
    if any(task_id not in spans for task_id, _g, _d in pins.tasks):
        raise TaskSelectionRefusal(TASK_SELECTED_MISSING)
    tasks = tuple(
        _decode_selected(raw[slice(*spans[task_id])], task_id, generation, digest)
        for task_id, generation, digest in pins.tasks
    )
    again, again_identity = _read_catalog(path, max_bytes)
    if again_identity != identity or hashlib.sha256(again).hexdigest() != pins.catalog_file_sha256:
        raise TaskSelectionRefusal(TASK_CATALOG_CHANGED)
    return SelectedTaskSet(pins, tasks)
